"""
任务观察者实现示例
展示如何使用观察者模式监听任务状态变更
"""
import json
from typing import Dict, Any
from datetime import datetime

from app.core.observer import TaskObserver, TaskEvent, TaskEventType
from app.core.logging import get_logger

logger = get_logger("task_observers")


# ==================== 示例观察者 ====================

class LoggingObserver(TaskObserver):
    """
    日志观察者
    
    将所有任务事件记录到日志中
    """
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """记录任务事件到日志"""
        log_msg = (
            f"📋 任务事件: {event.event_type.value} | "
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
        
        logger.info(log_msg)


class MetricsCollector(TaskObserver):
    """
    指标收集器观察者
    
    收集任务执行的统计指标（可用于 Prometheus 等监控系统）
    """
    
    def __init__(self):
        self._metrics: Dict[str, int] = {
            "tasks_created": 0,
            "tasks_started": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }
        self._task_durations: Dict[str, float] = {}
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """更新指标统计"""
        if event.event_type == TaskEventType.TASK_CREATED:
            self._metrics["tasks_created"] += 1
        
        elif event.event_type == TaskEventType.TASK_STARTED:
            self._metrics["tasks_started"] += 1
            # 记录开始时间
            self._task_durations[event.task_id] = datetime.now().timestamp()
        
        elif event.event_type == TaskEventType.TASK_COMPLETED:
            self._metrics["tasks_completed"] += 1
            # 计算执行时长
            if event.task_id in self._task_durations:
                start_time = self._task_durations.pop(event.task_id)
                duration = datetime.now().timestamp() - start_time
                logger.info(f"📊 任务 {event.task_id} 执行时长: {duration:.2f}秒")
        
        elif event.event_type == TaskEventType.TASK_FAILED:
            self._metrics["tasks_failed"] += 1
            # 清理记录
            self._task_durations.pop(event.task_id, None)
    
    def get_metrics(self) -> Dict[str, int]:
        """获取当前指标"""
        return self._metrics.copy()
    
    def get_observer_name(self) -> str:
        return "MetricsCollector"


class ProgressReporter(TaskObserver):
    """
    进度报告器观察者
    
    只关注进度更新事件，可用于 WebSocket 推送等场景
    """
    
    def __init__(self):
        self._progress_cache: Dict[str, int] = {}
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """处理进度更新"""
        if event.event_type == TaskEventType.TASK_PROGRESS_UPDATED:
            old_progress = self._progress_cache.get(event.task_id, 0)
            new_progress = event.progress or 0
            
            # 只在进度变化时报告（减少噪音）
            if new_progress != old_progress:
                self._progress_cache[event.task_id] = new_progress
                logger.info(
                    f"📈 任务进度更新: {event.task_id} "
                    f"[{old_progress}% → {new_progress}%] {event.message or ''}"
                )
        
        # 清理已完成任务的缓存
        elif event.event_type in [TaskEventType.TASK_COMPLETED, TaskEventType.TASK_FAILED]:
            self._progress_cache.pop(event.task_id, None)
    
    def get_observer_name(self) -> str:
        return "ProgressReporter"


class AlertObserver(TaskObserver):
    """
    告警观察者
    
    监听任务失败事件，触发告警（如邮件、短信、Webhook 等）
    """
    
    def __init__(self, alert_callback=None):
        """
        Args:
            alert_callback: 告警回调函数（可选）
        """
        self._alert_callback = alert_callback
        self._failed_tasks: list = []
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """处理任务失败事件"""
        if event.event_type == TaskEventType.TASK_FAILED:
            # 记录失败任务
            self._failed_tasks.append({
                "task_id": event.task_id,
                "task_type": event.task_type,
                "error": event.error,
                "timestamp": event.timestamp
            })
            
            # 发送告警
            alert_msg = (
                f"🚨 任务失败告警\n"
                f"任务ID: {event.task_id}\n"
                f"任务类型: {event.task_type}\n"
                f"错误信息: {event.error}\n"
                f"时间: {event.timestamp}"
            )
            
            logger.error(alert_msg)
            
            # 调用自定义告警回调
            if self._alert_callback:
                try:
                    await self._alert_callback(event.to_dict())
                except Exception as e:
                    logger.error(f"告警回调执行失败: {e}")
    
    def get_failed_tasks(self) -> list:
        """获取失败任务列表"""
        return self._failed_tasks.copy()
    
    def get_observer_name(self) -> str:
        return "AlertObserver"


class TaskHistoryRecorder(TaskObserver):
    """
    任务历史记录器观察者
    
    记录所有任务事件的完整历史（可用于审计、回溯等）
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: 最大历史记录数（超出后删除最旧的记录）
        """
        self._history: list = []
        self._max_history = max_history
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """记录事件到历史"""
        # 添加新记录
        self._history.append(event.to_dict())
        
        # 限制历史记录数量（FIFO）
        if len(self._history) > self._max_history:
            self._history.pop(0)
        
        logger.debug(f"📝 记录任务事件: {event.event_type.value} [{event.task_id}]")
    
    def get_history(self, task_id: str = None) -> list:
        """
        获取历史记录
        
        Args:
            task_id: 可选，只获取特定任务的历史
        
        Returns:
            历史记录列表
        """
        if task_id:
            return [
                record for record in self._history 
                if record["task_id"] == task_id
            ]
        return self._history.copy()
    
    def export_history_json(self, filepath: str) -> None:
        """导出历史记录到 JSON 文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self._history, f, indent=2, ensure_ascii=False)
        logger.info(f"📝 任务历史已导出到: {filepath}")
    
    def get_observer_name(self) -> str:
        return "TaskHistoryRecorder"


# ==================== WebSocket 推送观察者（示例）====================

class WebSocketNotifier(TaskObserver):
    """
    WebSocket 通知器观察者（示例）
    
    将任务事件推送到 WebSocket 客户端
    
    Note:
        这是一个示例实现，实际使用时需要集成真实的 WebSocket 连接管理器
    """
    
    def __init__(self, connection_manager=None):
        """
        Args:
            connection_manager: WebSocket 连接管理器（需要提供 broadcast 方法）
        """
        self._connection_manager = connection_manager
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """推送事件到 WebSocket 客户端"""
        if not self._connection_manager:
            logger.debug("WebSocket 连接管理器未配置，跳过推送")
            return
        
        try:
            # 构造推送消息
            message = {
                "type": "task_event",
                "data": event.to_dict()
            }
            
            # 广播给所有连接的客户端
            await self._connection_manager.broadcast(json.dumps(message))
            
            logger.debug(
                f"📡 WebSocket 推送: {event.event_type.value} [{event.task_id}]"
            )
        except Exception as e:
            logger.error(f"WebSocket 推送失败: {e}")
    
    def get_observer_name(self) -> str:
        return "WebSocketNotifier"
