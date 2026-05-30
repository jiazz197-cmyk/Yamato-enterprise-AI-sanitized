"""Background scheduler for quotation task retention."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.usecases.quotation.retention import (
    expire_awaiting_approval_tasks,
    purge_old_terminal_tasks_global,
)

logger = get_logger("quotation.retention_scheduler")

_stop_event = asyncio.Event()
_loop_task: Optional[asyncio.Task] = None


async def run_retention_once() -> None:
    db = SessionLocal()
    try:
        await expire_awaiting_approval_tasks(
            db,
            ttl_hours=settings.QUOTATION_AWAITING_APPROVAL_TTL_HOURS,
        )
        await purge_old_terminal_tasks_global(
            db,
            max_total=settings.QUOTATION_RETENTION_MAX_TOTAL,
            target=settings.QUOTATION_RETENTION_TARGET,
        )
    except Exception:
        logger.exception("Quotation retention run failed")
    finally:
        db.close()


async def _retention_loop(interval_sec: int) -> None:
    while not _stop_event.is_set():
        await run_retention_once()
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


def start_retention_scheduler() -> asyncio.Task:
    global _loop_task
    _stop_event.clear()
    interval = settings.QUOTATION_RETENTION_INTERVAL_SEC
    _loop_task = asyncio.create_task(_retention_loop(interval))
    logger.info("Quotation retention scheduler started (interval=%ss)", interval)
    return _loop_task


async def stop_retention_scheduler() -> None:
    global _loop_task
    _stop_event.set()
    if _loop_task is not None:
        try:
            await asyncio.wait_for(_loop_task, timeout=5.0)
        except asyncio.TimeoutError:
            _loop_task.cancel()
        _loop_task = None
    logger.info("Quotation retention scheduler stopped")
