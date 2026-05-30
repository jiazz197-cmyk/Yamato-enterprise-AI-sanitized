"""WebSocket task progress: connection manager + TaskObserver bridge (non-HTTP)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Dict, Set

import jwt
from fastapi import WebSocket, WebSocketException, status

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.observer import TaskEvent, TaskObserver
from app.models.orm.platform.user import User

logger = get_logger("websocket_task_manager")


class WebSocketConnectionManager:
    """按 task_id 挂连接；按 IP 限连接数与每分钟消息数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.ip_connections: Dict[str, int] = {}
        self.ip_message_counters: Dict[str, Dict[str, int]] = {}

    async def connect(self, websocket: WebSocket, task_id: str, client_ip: str) -> None:
        with self._lock:
            current_count = self.ip_connections.get(client_ip, 0)
            if current_count >= settings.WS_MAX_CONNECTIONS_PER_IP:
                raise WebSocketException(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="连接数超过限制",
                )
        await websocket.accept()
        self.register(websocket, task_id, client_ip)

    def register(self, websocket: WebSocket, task_id: str, client_ip: str) -> None:
        """注册已 accept 的 WebSocket（不调用 accept）。"""
        with self._lock:
            current_count = self.ip_connections.get(client_ip, 0)
            if task_id not in self.active_connections:
                self.active_connections[task_id] = set()
            self.active_connections[task_id].add(websocket)
            self.ip_connections[client_ip] = current_count + 1
            websocket.state.client_ip = client_ip

    def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        with self._lock:
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
        logger.info("[error] WebSocket client disconnected: task_id=%s", task_id)

    def _trim_message_counters_if_needed(self) -> None:
        """必须在持锁下调用。"""
        cap = settings.WS_MAX_TRACKED_IPS_FOR_COUNTERS
        if len(self.ip_message_counters) <= cap:
            return
        overflow = len(self.ip_message_counters) - cap + max(10, cap // 10)
        for key in list(self.ip_message_counters.keys())[:overflow]:
            self.ip_message_counters.pop(key, None)

    def allow_message(self, client_ip: str) -> bool:
        current_window = int(time.time()) // 60
        with self._lock:
            counter = self.ip_message_counters.get(client_ip)
            if not counter or counter["window"] != current_window:
                self.ip_message_counters[client_ip] = {"window": current_window, "count": 1}
                self._trim_message_counters_if_needed()
                return True
            counter["count"] += 1
            ok = counter["count"] <= settings.WS_MAX_MESSAGES_PER_MINUTE
            self._trim_message_counters_if_needed()
            return ok

    async def send_to_task(self, task_id: str, message: dict) -> None:
        with self._lock:
            if task_id not in self.active_connections:
                return
            subscribers = list(self.active_connections.get(task_id, set()))
        message_text = json.dumps(message, ensure_ascii=False)
        disconnected = []
        for ws in subscribers:
            try:
                await ws.send_text(message_text)
                logger.debug(
                    "[event] Message pushed: task_id=%s, event=%s",
                    task_id,
                    message.get("event_type"),
                )
            except Exception as e:
                logger.warning("Push failed: %s", e)
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws, task_id)

    def get_connection_count(self, task_id: str | None = None) -> int:
        with self._lock:
            if task_id:
                return len(self.active_connections.get(task_id, set()))
            return sum(len(conns) for conns in self.active_connections.values())

    async def disconnect_all(self) -> None:
        with self._lock:
            total_count = sum(len(conns) for conns in self.active_connections.values())
        if total_count == 0:
            logger.info("没有活跃的 WebSocket 连接需要关闭")
            return
        logger.info("正在关闭 %s 个 WebSocket 连接...", total_count)
        with self._lock:
            snapshot = list(self.active_connections.items())
        for _tid, websockets in snapshot:
            for ws in list(websockets):
                try:
                    await ws.close(code=1001, reason="Server shutdown")
                except Exception as e:
                    logger.debug("关闭 WebSocket 时出错: %s", e)
        with self._lock:
            self.active_connections.clear()
        logger.info("[success] 所有 WebSocket 连接已关闭")


def decode_ws_bearer_user_id(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="无效令牌") from exc
    user_id = str(payload.get("sub", "")).strip()
    if not user_id:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="令牌缺少主体")
    return user_id


def load_user_for_websocket(user_id: str) -> User | None:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except Exception as exc:
        logger.warning("加载 WebSocket 用户失败: %s", exc)
        return None
    finally:
        db.close()


ws_manager = WebSocketConnectionManager()


class WebSocketTaskObserver(TaskObserver):
    """Push TaskEvent JSON to ``ws_manager``."""

    def __init__(self, connection_manager: WebSocketConnectionManager) -> None:
        self.manager = connection_manager

    async def on_task_event(self, event: TaskEvent) -> None:
        message = {
            "type": "task_event",
            "event_type": event.event_type.value,
            "task_id": event.task_id,
            "task_type": event.task_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.message,
            "error": event.error,
            "timestamp": event.timestamp,
        }
        await self.manager.send_to_task(event.task_id, message)

    def get_observer_name(self) -> str:
        return "WebSocketTaskObserver"
