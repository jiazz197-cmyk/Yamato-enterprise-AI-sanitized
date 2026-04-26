"""
Compat re-exports for async task state (Redis / memory).
Prefer: ``from app.core.task_manager import task_manager, TaskManager``.
"""

from app.core.task_manager import (
    MemoryTaskStorage,
    TaskManager,
    TaskStatus,
    task_manager,
)

__all__ = [
    "MemoryTaskStorage",
    "TaskManager",
    "TaskStatus",
    "task_manager",
]
