"""Quotation task retention: global terminal purge and awaiting_approval expiry."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus
from app.usecases.quotation.purge import purge_quotation_task

logger = get_logger("quotation.retention")

_TERMINAL_STATUSES = (
    QuotationTaskStatus.completed.value,
    QuotationTaskStatus.failed.value,
    QuotationTaskStatus.cancelled.value,
)


async def purge_old_terminal_tasks_global(
    db: Session,
    *,
    max_total: int = 100,
    target: int = 50,
) -> int:
    """Drop oldest terminal tasks when global row count exceeds max_total."""
    total = db.query(QuotationTask).count()
    if total <= max_total:
        return 0

    to_delete = total - target
    candidates = (
        db.query(QuotationTask.task_id)
        .filter(QuotationTask.status.in_(_TERMINAL_STATUSES))
        .order_by(QuotationTask.created_at.asc())
        .limit(to_delete)
        .all()
    )

    purged = 0
    sample_ids: list[str] = []
    for (task_id,) in candidates:
        result = await purge_quotation_task(task_id, allow_non_terminal=False, db=db)
        if result.get("purged"):
            purged += 1
            if len(sample_ids) < 5:
                sample_ids.append(task_id)

    if purged:
        logger.info(
            "Global terminal retention: purged=%s total_before=%s target=%s sample=%s",
            purged,
            total,
            target,
            sample_ids,
        )
    return purged


async def expire_awaiting_approval_tasks(
    db: Session,
    *,
    ttl_hours: int = 24,
) -> int:
    """Hard-delete awaiting_approval tasks that exceeded the TTL."""
    cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
    expired = (
        db.query(QuotationTask.task_id)
        .filter(
            QuotationTask.status == QuotationTaskStatus.awaiting_approval.value,
            QuotationTask.awaiting_approval_at.isnot(None),
            QuotationTask.awaiting_approval_at < cutoff,
        )
        .all()
    )

    purged = 0
    sample_ids: list[str] = []
    for (task_id,) in expired:
        result = await purge_quotation_task(task_id, allow_non_terminal=True, db=db)
        if result.get("purged"):
            purged += 1
            if len(sample_ids) < 5:
                sample_ids.append(task_id)

    if purged:
        logger.info(
            "Awaiting approval expiry: purged=%s ttl_hours=%s sample=%s",
            purged,
            ttl_hours,
            sample_ids,
        )
    return purged
