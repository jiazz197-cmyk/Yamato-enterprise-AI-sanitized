"""Queue dispatcher for quotation generation tasks."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

logger = get_logger("quotation_dispatcher")


@dataclass
class DispatchCandidate:
    """Task payload required by executor submission."""

    task_id: str
    owner_id: str


class QuotationDispatcher:
    """Controls running quotas and dequeues queued tasks.

    Keep owner-based dispatch entrypoints for fairness, and enforce IP quota
    at actual dequeue stage.
    """

    def __init__(self, max_running_per_owner: int = 2, max_running_per_ip: int = 2):
        self._max_running_per_owner = max_running_per_owner
        self._max_running_per_ip = max_running_per_ip
        self._lock = threading.Lock()

    def dequeue_for_owner(self, db: Session, owner_id: str) -> List[DispatchCandidate]:
        """Move queued tasks to running state when owner/IP has free slots."""
        with self._lock:
            running_count = (
                db.query(QuotationTask)
                .filter(
                    QuotationTask.owner_id == owner_id,
                    QuotationTask.status == QuotationTaskStatus.running.value,
                )
                .count()
            )
            owner_available = max(self._max_running_per_owner - running_count, 0)
            if owner_available <= 0:
                return []

            queued_tasks = (
                db.query(QuotationTask)
                .filter(
                    QuotationTask.owner_id == owner_id,
                    QuotationTask.status == QuotationTaskStatus.queued.value,
                )
                .order_by(QuotationTask.created_at.asc())
                .all()
            )
            if not queued_tasks:
                return []

            candidate_ips = {
                str(task.owner_ip).strip()
                for task in queued_tasks
                if getattr(task, "owner_ip", None) and str(task.owner_ip).strip()
            }

            running_by_ip: dict[str, int] = {}
            if candidate_ips:
                ip_rows = (
                    db.query(QuotationTask.owner_ip, func.count(QuotationTask.id))
                    .filter(
                        QuotationTask.status == QuotationTaskStatus.running.value,
                        QuotationTask.owner_ip.in_(candidate_ips),
                    )
                    .group_by(QuotationTask.owner_ip)
                    .all()
                )
                running_by_ip = {
                    str(owner_ip).strip(): int(count)
                    for owner_ip, count in ip_rows
                    if owner_ip and str(owner_ip).strip()
                }

            selected_tasks: list[QuotationTask] = []
            for task in queued_tasks:
                if len(selected_tasks) >= owner_available:
                    break

                owner_ip = str(getattr(task, "owner_ip", "") or "").strip()
                if not owner_ip:
                    logger.warning(
                        "Task missing owner_ip, applying owner quota only: task_id=%s owner_id=%s",
                        task.task_id,
                        task.owner_id,
                    )
                    selected_tasks.append(task)
                    continue

                current_ip_running = running_by_ip.get(owner_ip, 0)
                if current_ip_running >= self._max_running_per_ip:
                    continue

                selected_tasks.append(task)
                running_by_ip[owner_ip] = current_ip_running + 1

            if not selected_tasks:
                return []

            now = datetime.utcnow()
            for task in selected_tasks:
                task.status = QuotationTaskStatus.running.value
                task.started_at = now
                task.progress = max(task.progress, 1)
                task.message = "任务已开始处理"

            db.commit()

            return [DispatchCandidate(task_id=task.task_id, owner_id=task.owner_id) for task in selected_tasks]


quotation_dispatcher = QuotationDispatcher(
    max_running_per_owner=settings.QUOTATION_MAX_RUNNING_PER_OWNER,
    max_running_per_ip=settings.QUOTATION_MAX_RUNNING_PER_IP,
)

