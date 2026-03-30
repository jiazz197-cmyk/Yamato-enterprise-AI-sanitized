"""
WebSocket Task Notifier
Real-time task progress and status updates for clients
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status, Depends
from typing import Dict, Set
import json
import jwt
from app.core.observer import TaskObserver, TaskEvent
from app.core.logging import get_logger
from app.core.config import settings
from app.core.executor import executor_manager
from app.api.taskmanager import task_manager
from app.core.security import require_roles
from app.models.orm.platform.user import User, UserRole

logger = get_logger("websocket_notifier")

router = APIRouter()


class WebSocketConnectionManager:
    """WebSocket connection manager"""

    def __init__(self):
        # {task_id: Set[WebSocket]}
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        """Connect client"""
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
        logger.info(
            f"✅ WebSocket client connected: task_id={task_id}, "
            f"connections={len(self.active_connections[task_id])}"
        )

    def disconnect(self, websocket: WebSocket, task_id: str):
        """Disconnect client"""
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
            logger.info(f"❌ WebSocket client disconnected: task_id={task_id}")

    async def send_to_task(self, task_id: str, message: dict):
        """Send message to all clients subscribed to a specific task"""
        if task_id not in self.active_connections:
            return

        message_text = json.dumps(message, ensure_ascii=False)
        disconnected = []

        for websocket in self.active_connections[task_id]:
            try:
                await websocket.send_text(message_text)
                logger.debug(
                    f"📡 Message pushed to client: task_id={task_id}, "
                    f"event={message.get('event_type')}"
                )
            except Exception as e:
                logger.warning(f"Push failed: {e}")
                disconnected.append(websocket)

        # Clean up disconnected connections
        for ws in disconnected:
            self.disconnect(ws, task_id)

    def get_connection_count(self, task_id: str = None) -> int:
        """Get connection count"""
        if task_id:
            return len(self.active_connections.get(task_id, set()))
        return sum(len(conns) for conns in self.active_connections.values())

    async def disconnect_all(self):
        """Disconnect all WebSocket connections gracefully"""
        total_count = self.get_connection_count()
        if total_count == 0:
            logger.info("没有活跃的 WebSocket 连接需要关闭")
            return

        logger.info(f"正在关闭 {total_count} 个 WebSocket 连接...")

        # Close all connections
        for task_id, websockets in list(self.active_connections.items()):
            for websocket in list(websockets):
                try:
                    await websocket.close(code=1001, reason="Server shutdown")
                except Exception as e:
                    logger.debug(f"关闭 WebSocket 时出错: {e}")

        # Clear all connections
        self.active_connections.clear()
        logger.info("✅ 所有 WebSocket 连接已关闭")


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


# Global connection manager
ws_manager = WebSocketConnectionManager()


class WebSocketTaskObserver(TaskObserver):
    """WebSocket task observer"""
    
    def __init__(self, connection_manager: WebSocketConnectionManager):
        self.manager = connection_manager
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """Receive task event and push to subscribed clients"""
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
        
        # Push to all clients subscribed to this task
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
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="缺少认证令牌")
        return

    try:
        user_id = _decode_ws_token(token)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason or "认证失败")
        return

    task_owner_map = getattr(executor_manager, "_task_owner_map", {})
    owner_id = str(task_owner_map.get(task_id, "")).strip()

    if not owner_id:
        task_status = await task_manager.get_task_status(task_id)
        if task_status:
            owner_id = str(task_status.metadata.get("owner_id", "")).strip()

    # 默认拒绝：owner 缺失时不允许订阅，防止 task_id 枚举旁路
    if not owner_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="任务缺少归属信息，禁止订阅")
        return

    if owner_id != user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="无权订阅该任务")
        return

    await ws_manager.connect(websocket, task_id)

    try:
        # Send welcome message
        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "task_id": task_id,
            "message": f"已订阅任务 {task_id} 的实时更新"
        }, ensure_ascii=False))
        
        # Keep connection alive and receive client messages (optional)
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received client message: {data}")
            
            # Handle client control commands
            # Example: {"action": "cancel"} to cancel task
    
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id)
        logger.info(f"🔌 Client disconnected: task_id={task_id}")
    
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
