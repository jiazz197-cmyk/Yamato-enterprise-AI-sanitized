"""
观察者模式基础框架
提供事件发布-订阅机制，用于解耦组件间的通信
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import logging

logger = logging.getLogger("app.observer")


# ==================== 事件定义 ====================

class TaskEventType(str, Enum):
    """任务事件类型"""
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_PROGRESS_UPDATED = "task_progress_updated"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


@dataclass
class TaskEvent:
    """
    任务事件数据类
    
    携带任务状态变更的完整信息
    """
    event_type: TaskEventType
    task_id: str
    task_type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 可选字段
    status: Optional[str] = None
    progress: Optional[int] = None
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_type": self.event_type.value,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "timestamp": self.timestamp,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


# ==================== 观察者接口 ====================

class TaskObserver(ABC):
    """
    任务观察者抽象基类
    
    所有任务观察者必须实现 on_task_event 方法
    """
    
    @abstractmethod
    async def on_task_event(self, event: TaskEvent) -> None:
        """
        处理任务事件
        
        Args:
            event: 任务事件对象
        
        Note:
            此方法应该是异步的，避免阻塞事件分发
        """
        pass
    
    def get_observer_name(self) -> str:
        """获取观察者名称（用于日志和调试）"""
        return self.__class__.__name__


# ==================== 被观察者（Subject）====================

class TaskSubject:
    """
    任务事件发布者（被观察者）
    
    职责：
    - 管理观察者列表
    - 发布任务事件到所有观察者
    - 支持按事件类型过滤观察者
    
    特性：
    - 线程安全的观察者管理
    - 异步事件通知
    - 错误隔离（单个观察者失败不影响其他观察者）
    """
    
    def __init__(self):
        self._observers: List[TaskObserver] = []
        self._filtered_observers: Dict[TaskEventType, Set[TaskObserver]] = {}
        self._lock = asyncio.Lock()
        
        # 统计信息
        self._event_count = 0
        self._error_count = 0
    
    async def attach(
        self, 
        observer: TaskObserver, 
        event_types: Optional[List[TaskEventType]] = None
    ) -> None:
        """
        注册观察者
        
        Args:
            observer: 观察者实例
            event_types: 可选，只接收特定类型的事件（None = 接收所有事件）
        
        Example:
            ```python
            subject = TaskSubject()
            
            # 接收所有事件
            await subject.attach(MyObserver())
            
            # 只接收完成和失败事件
            await subject.attach(
                AlertObserver(), 
                event_types=[TaskEventType.TASK_COMPLETED, TaskEventType.TASK_FAILED]
            )
            ```
        """
        async with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                logger.info(f"✅ 注册观察者: {observer.get_observer_name()}")
            
            # 注册事件过滤
            if event_types:
                for event_type in event_types:
                    if event_type not in self._filtered_observers:
                        self._filtered_observers[event_type] = set()
                    self._filtered_observers[event_type].add(observer)
                logger.info(
                    f"  过滤器: {observer.get_observer_name()} → {[et.value for et in event_types]}"
                )
    
    async def detach(self, observer: TaskObserver) -> None:
        """
        注销观察者
        
        Args:
            observer: 要注销的观察者实例
        """
        async with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)
                logger.info(f"🔌 注销观察者: {observer.get_observer_name()}")
            
            # 清理过滤器
            for event_type_set in self._filtered_observers.values():
                event_type_set.discard(observer)
    
    async def detach_all(self) -> int:
        """
        注销所有观察者（用于关闭时清理）
        
        Returns:
            注销的观察者数量
        """
        async with self._lock:
            count = len(self._observers)
            self._observers.clear()
            self._filtered_observers.clear()
            logger.info(f"🔌 已注销所有观察者: {count} 个")
            return count
    
    async def notify(self, event: TaskEvent) -> None:
        """
        通知所有相关观察者
        
        Args:
            event: 任务事件
        
        工作流程：
        1. 确定需要通知的观察者（根据事件类型过滤）
        2. 并发通知所有观察者
        3. 错误隔离（单个观察者失败不影响其他观察者）
        """
        self._event_count += 1
        
        # 获取需要通知的观察者列表
        async with self._lock:
            observers_to_notify = self._get_observers_for_event(event)
        
        if not observers_to_notify:
            logger.debug(f"📡 事件 {event.event_type.value} 无订阅者")
            return
        
        logger.debug(
            f"📡 发布事件: {event.event_type.value} "
            f"[task_id={event.task_id}] → {len(observers_to_notify)} 个观察者"
        )
        
        # 并发通知所有观察者（错误隔离）
        tasks = []
        for observer in observers_to_notify:
            task = asyncio.create_task(
                self._notify_observer(observer, event)
            )
            tasks.append(task)
        
        # 等待所有通知完成（不抛出异常）
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def _get_observers_for_event(self, event: TaskEvent) -> List[TaskObserver]:
        """
        根据事件类型获取需要通知的观察者
        
        逻辑：
        - 如果观察者注册了事件过滤器，检查事件类型是否匹配
        - 如果观察者没有过滤器，接收所有事件
        """
        observers_to_notify = []
        
        for observer in self._observers:
            # 检查观察者是否有过滤器
            has_filter = any(
                observer in observer_set 
                for observer_set in self._filtered_observers.values()
            )
            
            if has_filter:
                # 有过滤器，检查事件类型是否匹配
                if event.event_type in self._filtered_observers:
                    if observer in self._filtered_observers[event.event_type]:
                        observers_to_notify.append(observer)
            else:
                # 无过滤器，接收所有事件
                observers_to_notify.append(observer)
        
        return observers_to_notify
    
    async def _notify_observer(self, observer: TaskObserver, event: TaskEvent) -> None:
        """
        通知单个观察者（带错误处理）
        
        错误隔离：单个观察者失败不影响其他观察者
        """
        try:
            await observer.on_task_event(event)
        except Exception as e:
            self._error_count += 1
            logger.error(
                f"❌ 观察者 {observer.get_observer_name()} "
                f"处理事件 {event.event_type.value} 失败: {e}",
                exc_info=True
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "observer_count": len(self._observers),
            "event_count": self._event_count,
            "error_count": self._error_count,
            "filtered_observers": {
                event_type.value: len(observers)
                for event_type, observers in self._filtered_observers.items()
            }
        }


# ==================== 函数式观察者包装器 ====================

class FunctionObserver(TaskObserver):
    """
    函数式观察者包装器
    
    允许使用普通函数作为观察者，无需创建类
    
    Example:
        ```python
        async def log_task_event(event: TaskEvent):
            print(f"任务事件: {event.event_type}")
        
        observer = FunctionObserver(log_task_event, name="LogObserver")
        await subject.attach(observer)
        ```
    """
    
    def __init__(
        self, 
        callback: Callable[[TaskEvent], Any],
        name: Optional[str] = None
    ):
        """
        Args:
            callback: 事件处理函数（可以是同步或异步）
            name: 观察者名称（可选）
        """
        self._callback = callback
        self._name = name or "FunctionObserver"
    
    async def on_task_event(self, event: TaskEvent) -> None:
        """调用回调函数"""
        if asyncio.iscoroutinefunction(self._callback):
            await self._callback(event)
        else:
            # 同步函数在线程池中执行
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._callback, event)
    
    def get_observer_name(self) -> str:
        return self._name
