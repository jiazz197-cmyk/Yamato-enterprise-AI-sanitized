"""Quotation task retention adapter: encapsulates SQLAlchemy queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus
from app.ports.domains.quotation import QuotationTaskPurgePort, QuotationTaskRetentionPort

logger = get_logger("quotation.retention")

_TERMINAL_STATUSES = (
    QuotationTaskStatus.completed.value,
    QuotationTaskStatus.failed.value,
    QuotationTaskStatus.cancelled.value,
)


class QuotationTaskRetentionAdapter(QuotationTaskRetentionPort):
    """Encapsulates SQLAlchemy queries for quotation task retention."""

    def __init__(self, purge_port: QuotationTaskPurgePort):
        self._purge = purge_port

    async def purge_old_terminal_tasks_global(self, max_total: int = 100, target: int = 50) -> int:
        async with AsyncSessionLocal() as db:
            total_result = await db.execute(select(func.count()).select_from(QuotationTask))
            total = int(total_result.scalar_one())
            if total <= max_total:
                return 0

            to_delete = total - target
            candidates_result = await db.execute(
                select(QuotationTask.task_id)
                .where(QuotationTask.status.in_(_TERMINAL_STATUSES))
                .order_by(QuotationTask.created_at.asc())
                .limit(to_delete)
            )
            candidates = candidates_result.all()

            purged = 0
            sample_ids: list[str] = []
            for (task_id,) in candidates:
                result = await self._purge.purge_task(task_id, allow_non_terminal=False)
                if result.get("purged"):
                    purged += 1
                    if len(sample_ids) < 5:
                        sample_ids.append(task_id)

            if purged:
                logger.info(
                    "Global terminal retention: purged=%s total_before=%s target=%s sample=%s",
                    purged, total, target, sample_ids,
                )
            return purged

    async def expire_awaiting_approval_tasks(self, ttl_hours: int = 24) -> int:
        async with AsyncSessionLocal() as db:
            cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
            expired_result = await db.execute(
                select(QuotationTask.task_id)
                .where(
                    QuotationTask.status == QuotationTaskStatus.awaiting_approval.value,
                    QuotationTask.awaiting_approval_at.isnot(None),
                    QuotationTask.awaiting_approval_at < cutoff,
                )
            )
            expired = expired_result.all()

            purged = 0
            sample_ids: list[str] = []
            for (task_id,) in expired:
                result = await self._purge.purge_task(task_id, allow_non_terminal=True)
                if result.get("purged"):
                    purged += 1
                    if len(sample_ids) < 5:
                        sample_ids.append(task_id)

            if purged:
                logger.info(
                    "Awaiting approval expiry: purged=%s ttl_hours=%s sample=%s",
                    purged, ttl_hours, sample_ids,
                )
            return purged
