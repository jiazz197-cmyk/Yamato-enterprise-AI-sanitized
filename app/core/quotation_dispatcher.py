"""Queue dispatcher for quotation generation tasks."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus


@dataclass
class DispatchCandidate:
    """Task payload required by executor submission."""

    task_id: str
    owner_id: str


class QuotationDispatcher:
    """Controls per-user running quota and dequeues queued tasks.

    The lock only covers ORM queries and commit; avoid taking other locks
    (e.g. executor) while inside dequeue_for_owner to keep ordering obvious.
    """

    def __init__(self, max_running_per_user: int = 3):
        self._max_running_per_user = max_running_per_user
        self._lock = threading.Lock()

    def dequeue_for_owner(self, db: Session, owner_id: str) -> List[DispatchCandidate]:
        """Move queued tasks to running state when owner has free slots."""
        with self._lock:
            running_count = (
                db.query(QuotationTask)
                .filter(
                    QuotationTask.owner_id == owner_id,
                    QuotationTask.status == QuotationTaskStatus.running.value,
                )
                .count()
            )
            available = max(self._max_running_per_user - running_count, 0)
            if available <= 0:
                return []

            queued_tasks = (
                db.query(QuotationTask)
                .filter(
                    QuotationTask.owner_id == owner_id,
                    QuotationTask.status == QuotationTaskStatus.queued.value,
                )
                .order_by(QuotationTask.created_at.asc())
                .limit(available)
                .all()
            )

            if not queued_tasks:
                return []

            now = datetime.utcnow()
            for task in queued_tasks:
                task.status = QuotationTaskStatus.running.value
                task.started_at = now
                task.progress = max(task.progress, 1)
                task.message = "任务已开始处理"

            db.commit()

            return [DispatchCandidate(task_id=task.task_id, owner_id=task.owner_id) for task in queued_tasks]


quotation_dispatcher = QuotationDispatcher(max_running_per_user=3)

