"""TaskManager 事件观察者：日志、指标、进度、告警、历史、WebSocket 等。"""
import json
from typing import Dict, Any
from datetime import datetime

from app.core.observer import TaskObserver, TaskEvent, TaskEventType
from app.core.logging import get_logger

logger = get_logger("task_observers")


class LoggingObserver(TaskObserver):
    """把任务事件打到日志；进度类事件用 debug 降噪。"""
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """组装一行摘要后 info/debug。"""
        log_msg = (
            f"[event] 任务事件: {event.event_type.value} | "
            f"ID: {event.task_id} | "
            f"类型: {event.task_type} | "
            f"状态: {event.status or 'N/A'}"
        )
        
        if event.progress is not None:
            log_msg += f" | 进度: {event.progress}%"
        
        if event.message:
            log_msg += f" | 消息: {event.message}"
        
        if event.error:
            log_msg += f" | 错误: {event.error}"
        
        if event.event_type == TaskEventType.TASK_PROGRESS_UPDATED:
            logger.debug(log_msg)
        else:
            logger.info(log_msg)


class MetricsCollector(TaskObserver):
    """内存里计数各生命周期事件，可选配合 Prometheus。"""
    
    def __init__(self):
        self._metrics: Dict[str, int] = {
            "tasks_created": 0,
            "tasks_started": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }
        self._task_durations: Dict[str, float] = {}
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """按事件类型累加计数并算耗时。"""
        if event.event_type == TaskEventType.TASK_CREATED:
            self._metrics["tasks_created"] += 1
        
        elif event.event_type == TaskEventType.TASK_STARTED:
            self._metrics["tasks_started"] += 1
            self._task_durations[event.task_id] = datetime.now().timestamp()
        
        elif event.event_type == TaskEventType.TASK_COMPLETED:
            self._metrics["tasks_completed"] += 1
            if event.task_id in self._task_durations:
                start_time = self._task_durations.pop(event.task_id)
                duration = datetime.now().timestamp() - start_time
                logger.info(f"[event] 任务 {event.task_id} 执行时长: {duration:.2f}秒")
        
        elif event.event_type == TaskEventType.TASK_FAILED:
            self._metrics["tasks_failed"] += 1
            self._task_durations.pop(event.task_id, None)
    
    def get_metrics(self) -> Dict[str, int]:
        """计数器快照。"""
        return self._metrics.copy()
    
    def get_observer_name(self) -> str:
        return "MetricsCollector"


class ProgressReporter(TaskObserver):
    """只在进度百分比变化时打日志。"""
    
    def __init__(self):
        self._progress_cache: Dict[str, int] = {}
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """TASK_PROGRESS_UPDATED 且数值变了才 info。"""
        if event.event_type == TaskEventType.TASK_PROGRESS_UPDATED:
            old_progress = self._progress_cache.get(event.task_id, 0)
            new_progress = event.progress or 0
            
            if new_progress != old_progress:
                self._progress_cache[event.task_id] = new_progress
                logger.info(
                    f"[event] 任务进度更新: {event.task_id} "
                    f"[{old_progress}% → {new_progress}%] {event.message or ''}"
                )
        
        elif event.event_type in [TaskEventType.TASK_COMPLETED, TaskEventType.TASK_FAILED]:
            self._progress_cache.pop(event.task_id, None)
    
    def get_observer_name(self) -> str:
        return "ProgressReporter"


class AlertObserver(TaskObserver):
    """失败事件记列表并可选用回调往外推。"""
    
    def __init__(self, alert_callback=None):
        """alert_callback 可为异步，入参为 event.to_dict()。"""
        self._alert_callback = alert_callback
        self._failed_tasks: list = []
    
    async def on_task_event(self, event: TaskEvent) -> None:
        if event.event_type == TaskEventType.TASK_FAILED:
            self._failed_tasks.append({
                "task_id": event.task_id,
                "task_type": event.task_type,
                "error": event.error,
                "timestamp": event.timestamp
            })
            
            alert_msg = (
                f"[alert] 任务失败告警\n"
                f"任务ID: {event.task_id}\n"
                f"任务类型: {event.task_type}\n"
                f"错误信息: {event.error}\n"
                f"时间: {event.timestamp}"
            )
            
            logger.error(alert_msg)
            
            if self._alert_callback:
                try:
                    await self._alert_callback(event.to_dict())
                except Exception as e:
                    logger.error(f"告警回调执行失败: {e}")
    
    def get_failed_tasks(self) -> list:
        """失败记录副本。"""
        return self._failed_tasks.copy()
    
    def get_observer_name(self) -> str:
        return "AlertObserver"


class TaskHistoryRecorder(TaskObserver):
    """FIFO 固定长度列表存 to_dict 快照。"""
    
    def __init__(self, max_history: int = 1000):
        """超 maxlen 丢最旧。"""
        self._history: list = []
        self._max_history = max_history
    
    async def on_task_event(self, event: TaskEvent) -> None:
        self._history.append(event.to_dict())
        
        if len(self._history) > self._max_history:
            self._history.pop(0)
        
        logger.debug(f"[event] 记录任务事件: {event.event_type.value} [{event.task_id}]")
    
    def get_history(self, task_id: str = None) -> list:
        """task_id 为空返回全量拷贝，否则过滤。"""
        if task_id:
            return [
                record for record in self._history 
                if record["task_id"] == task_id
            ]
        return self._history.copy()
    
    def export_history_json(self, filepath: str) -> None:
        """写 UTF-8 JSON。"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self._history, f, indent=2, ensure_ascii=False)
        logger.info(f"[event] 任务历史已导出到: {filepath}")
    
    def get_observer_name(self) -> str:
        return "TaskHistoryRecorder"


class WebSocketNotifier(TaskObserver):
    """需注入带 broadcast(str) 的连接管理器；本项目用 WebSocketTaskObserver 替代场景较多。"""
    
    def __init__(self, connection_manager=None):
        """connection_manager.broadcast(json_str)。"""
        self._connection_manager = connection_manager
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """JSON 包一层 type/data 后广播。"""
        if not self._connection_manager:
            logger.debug("WebSocket 连接管理器未配置，跳过推送")
            return
        
        try:
            message = {
                "type": "task_event",
                "data": event.to_dict()
            }
            
            await self._connection_manager.broadcast(json.dumps(message))
            
            logger.debug(
                f"[event] WebSocket 推送: {event.event_type.value} [{event.task_id}]"
            )
        except Exception as e:
            logger.error(f"WebSocket 推送失败: {e}")
    
    def get_observer_name(self) -> str:
        return "WebSocketNotifier"
