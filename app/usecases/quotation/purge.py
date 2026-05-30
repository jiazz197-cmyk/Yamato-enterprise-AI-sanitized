"""Shared quotation task purge: files, caches, Redis record, ORM row."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.executor import executor_manager
from app.core.task_manager import task_manager
from app.core.task_owner_registry import task_owner_registry
from app.core.quotation_task_cleanup import (
    safe_cleanup_quotation_task_files,
)
from app.models.orm.quotation_task import QuotationTask

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_RETENTION_PURGE_STATUSES = _TERMINAL_STATUSES | {"awaiting_approval"}


async def purge_quotation_task(
    task_id: str,
    *,
    allow_non_terminal: bool = False,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    own_session = db is None
    session = db or SessionLocal()
    try:
        task = session.query(QuotationTask).filter(QuotationTask.task_id == task_id).first()
        if task is None:
            return {"purged": False, "reason": "not_found", "task_id": task_id}

        allowed = _RETENTION_PURGE_STATUSES if allow_non_terminal else _TERMINAL_STATUSES
        if task.status not in allowed:
            return {
                "purged": False,
                "reason": "status_not_allowed",
                "task_id": task_id,
                "status": task.status,
            }

        cleanup_result = safe_cleanup_quotation_task_files(session, task, task_id)
        task_owner_registry.forget(task_id)
        executor_manager.forget_task(task_id)

        try:
            await task_manager.delete_task(task_id)
        except Exception:
            pass

        session.delete(task)
        session.commit()
        return {
            "purged": True,
            "task_id": task_id,
            "cleanup": cleanup_result,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
