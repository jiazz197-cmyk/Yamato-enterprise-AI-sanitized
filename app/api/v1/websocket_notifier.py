"""任务进度 WebSocket：按 task 订阅推送；连接管理在 app.core.websocket_task_manager。"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status, Depends

from app.core.logging import get_logger
from app.core.security import require_roles
from app.core.websocket_task_manager import (
    WebSocketTaskObserver,
    decode_ws_bearer_user_id,
    load_user_for_websocket,
    ws_manager,
)
from app.core.executor import executor_manager
from app.core.task_manager import task_manager
from app.models.orm.platform.user import User, UserRole

logger = get_logger("websocket_notifier")

router = APIRouter()

# Re-export for main.py / tests that imported from this module
__all__ = ["router", "WebSocketTaskObserver", "ws_manager"]


@router.websocket("/ws/{task_id}")
async def websocket_task_endpoint(websocket: WebSocket, task_id: str) -> None:
    client_ip = (websocket.client.host if websocket.client else "") or "unknown"
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="缺少认证令牌")
        return
    try:
        user_id = decode_ws_bearer_user_id(token)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason or "认证失败")
        return
    owner_id = executor_manager.get_task_owner(task_id)
    ws_user = load_user_for_websocket(user_id)
    if not owner_id:
        task_status = await task_manager.get_task_status(task_id)
        if task_status:
            owner_id = str(task_status.metadata.get("owner_id", "")).strip()
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
        await websocket.send_text(
            json.dumps(
                {
                    "type": "connection_established",
                    "task_id": task_id,
                    "message": f"已订阅任务 {task_id} 的实时更新",
                },
                ensure_ascii=False,
            )
        )
        while True:
            if not ws_manager.allow_message(client_ip):
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="消息频率超过限制",
                )
                break
            data = await websocket.receive_text()
            logger.debug("Received client message: %s", data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id)
        logger.info("[event] Client disconnected: task_id=%s", task_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        ws_manager.disconnect(websocket, task_id)


@router.get("/ws/stats")
async def get_websocket_stats(
    _: User = Depends(require_roles(UserRole.superuser)),
):
    return {
        "total_connections": ws_manager.get_connection_count(),
        "tasks_subscribed": len(ws_manager.active_connections),
        "connections_by_task": {
            tid: ws_manager.get_connection_count(tid) for tid in ws_manager.active_connections.keys()
        },
    }
