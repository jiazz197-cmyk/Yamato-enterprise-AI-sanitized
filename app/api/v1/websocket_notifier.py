"""任务进度 WebSocket：按 task 订阅推送。"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status, Depends
from typing import Dict, Set
import json
import jwt
import time
import uuid
from app.core.observer import TaskObserver, TaskEvent
from app.core.logging import get_logger
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.executor import executor_manager
from app.api.taskmanager import task_manager
from app.core.security import require_roles
from app.models.orm.platform.user import User, UserRole

logger = get_logger("websocket_notifier")

router = APIRouter()


class WebSocketConnectionManager:
    """按 task_id 挂连接；按 IP 限连接数与每分钟消息数。"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.ip_connections: Dict[str, int] = {}
        self.ip_message_counters: Dict[str, Dict[str, int]] = {}

    async def connect(self, websocket: WebSocket, task_id: str, client_ip: str):
        """accept 并记入 task 与 IP 计数。"""
        current_count = self.ip_connections.get(client_ip, 0)
        if current_count >= settings.WS_MAX_CONNECTIONS_PER_IP:
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="连接数超过限制",
            )
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
        self.ip_connections[client_ip] = current_count + 1
        websocket.state.client_ip = client_ip
        logger.info(
            f"[success] WebSocket client connected: task_id={task_id}, "
            f"connections={len(self.active_connections[task_id])}"
        )

    def disconnect(self, websocket: WebSocket, task_id: str):
        """从 task 集合移除并递减 IP 计数。"""
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
            client_ip = getattr(websocket.state, "client_ip", "")
            if client_ip:
                next_count = max(self.ip_connections.get(client_ip, 1) - 1, 0)
                if next_count == 0:
                    self.ip_connections.pop(client_ip, None)
                else:
                    self.ip_connections[client_ip] = next_count
            logger.info(f"[error] WebSocket client disconnected: task_id={task_id}")

    def allow_message(self, client_ip: str) -> bool:
        """按 IP 每分钟固定窗口计数。"""
        current_window = int(time.time()) // 60
        counter = self.ip_message_counters.get(client_ip)
        if not counter or counter["window"] != current_window:
            self.ip_message_counters[client_ip] = {"window": current_window, "count": 1}
            return True
        counter["count"] += 1
        return counter["count"] <= settings.WS_MAX_MESSAGES_PER_MINUTE

    async def send_to_task(self, task_id: str, message: dict):
        """JSON 文本推给订阅该 task 的全部连接；失败则 disconnect。"""
        if task_id not in self.active_connections:
            return

        message_text = json.dumps(message, ensure_ascii=False)
        disconnected = []
        subscribers = list(self.active_connections.get(task_id, set()))

        for websocket in subscribers:
            try:
                await websocket.send_text(message_text)
                logger.debug(
                    f"[event] Message pushed to client: task_id={task_id}, "
                    f"event={message.get('event_type')}"
                )
            except Exception as e:
                logger.warning(f"Push failed: {e}")
                disconnected.append(websocket)

        for ws in disconnected:
            self.disconnect(ws, task_id)

    def get_connection_count(self, task_id: str = None) -> int:
        """指定 task 或全局连接数。"""
        if task_id:
            return len(self.active_connections.get(task_id, set()))
        return sum(len(conns) for conns in self.active_connections.values())

    async def disconnect_all(self):
        """关服时 1001 关闭并清空表。"""
        total_count = self.get_connection_count()
        if total_count == 0:
            logger.info("没有活跃的 WebSocket 连接需要关闭")
            return

        logger.info(f"正在关闭 {total_count} 个 WebSocket 连接...")

        for task_id, websockets in list(self.active_connections.items()):
            for websocket in list(websockets):
                try:
                    await websocket.close(code=1001, reason="Server shutdown")
                except Exception as e:
                    logger.debug(f"关闭 WebSocket 时出错: {e}")

        self.active_connections.clear()
        logger.info("[success] 所有 WebSocket 连接已关闭")


def _decode_ws_token(token: str) -> str:
    """解码 WebSocket Bearer Token，返回用户ID。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="无效令牌") from exc

    user_id = str(payload.get("sub", "")).strip()
    if not user_id:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="令牌缺少主体")
    return user_id


def _load_ws_user(user_id: str) -> User | None:
    """Fetch user for role checks in websocket authorization."""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except Exception as exc:
        logger.warning(f"加载 WebSocket 用户失败: {exc}")
        return None
    finally:
        db.close()


ws_manager = WebSocketConnectionManager()


class WebSocketTaskObserver(TaskObserver):
    """TaskObserver：把事件 JSON 推到 ws_manager。"""
    
    def __init__(self, connection_manager: WebSocketConnectionManager):
        self.manager = connection_manager
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """组装 payload 后 send_to_task。"""
        message = {
            "type": "task_event",
            "event_type": event.event_type.value,
            "task_id": event.task_id,
            "task_type": event.task_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.message,
            "result": event.result,
            "error": event.error,
            "timestamp": event.timestamp,
        }
        
        await self.manager.send_to_task(event.task_id, message)
    
    def get_observer_name(self) -> str:
        return "WebSocketTaskObserver"


@router.websocket("/ws/{task_id}")
async def websocket_task_endpoint(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint: clients subscribe to task progress
    
    Connection URL: ws://localhost:8000/api/v1/docs/ws/{task_id}
    
    Args:
        task_id: Task ID
    
    Clients will receive real-time task events:
    - task_created: Task created
    - task_started: Task started
    - task_progress_updated: Progress updated
    - task_completed: Task completed
    - task_failed: Task failed
    """
    client_ip = (websocket.client.host if websocket.client else "") or "unknown"
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="缺少认证令牌")
        return

    try:
        user_id = _decode_ws_token(token)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason or "认证失败")
        return

    owner_id = executor_manager.get_task_owner(task_id)
    ws_user = _load_ws_user(user_id)

    if not owner_id:
        task_status = await task_manager.get_task_status(task_id)
        if task_status:
            owner_id = str(task_status.metadata.get("owner_id", "")).strip()

    # 默认拒绝：owner 缺失时不允许订阅，防止 task_id 枚举旁路
    if not owner_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="任务缺少归属信息，禁止订阅")
        return

    is_admin_like = bool(ws_user and ws_user.role in (UserRole.admin, UserRole.superuser))

    if owner_id != user_id and not is_admin_like:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="无权订阅该任务")
        return

    try:
        await ws_manager.connect(websocket, task_id, client_ip)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason or "连接被拒绝")
        return

    try:
        # Send welcome message
        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "task_id": task_id,
            "message": f"已订阅任务 {task_id} 的实时更新"
        }, ensure_ascii=False))
        
        # Keep connection alive and receive client messages (optional)
        while True:
            if not ws_manager.allow_message(client_ip):
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="消息频率超过限制",
                )
                break
            data = await websocket.receive_text()
            logger.debug(f"Received client message: {data}")
            
            # Handle client control commands
            # Example: {"action": "cancel"} to cancel task
    
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id)
        logger.info(f"[event] Client disconnected: task_id={task_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        ws_manager.disconnect(websocket, task_id)


@router.get("/ws/stats")
async def get_websocket_stats(
    _: User = Depends(require_roles(UserRole.superuser)),
):
    """Get WebSocket connection statistics"""
    return {
        "total_connections": ws_manager.get_connection_count(),
        "tasks_subscribed": len(ws_manager.active_connections),
        "connections_by_task": {
            task_id: ws_manager.get_connection_count(task_id)
            for task_id in ws_manager.active_connections.keys()
        }
    }
