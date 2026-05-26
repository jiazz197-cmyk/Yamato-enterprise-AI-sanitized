"""Centralized task ownership registry.

Decouples authorization data from executor concurrency lifecycle and from
TaskManager TTL caches. Each task domain registers a `TaskOwnerLookup`
provider that points at its real source of truth:

    quotation_generation_*  -> Postgres `quotation_tasks.owner_id`
    doc_process_*           -> TaskManager Redis metadata
    other (e.g. pdf_convert_*, image_upload_*)
                            -> in-memory cache only (no persistent truth)

The in-memory cache is a write-through optimisation; persistence lookups
are async to avoid blocking the event loop on DB/Redis I/O.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, List, Optional, Protocol

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.task_manager import task_manager
from app.models.orm.quotation_task import QuotationTask

logger = get_logger("task_owner_registry")


class TaskOwnerLookup(Protocol):
    """Source-of-truth provider for one task domain."""

    def matches(self, task_id: str) -> bool: ...

    async def get_owner_id(self, task_id: str) -> Optional[str]: ...


class _QuotationOwnerLookup:
    """quotation_generation_* tasks live in `quotation_tasks` table."""

    PREFIX = "quotation_generation_"

    def matches(self, task_id: str) -> bool:
        return task_id.startswith(self.PREFIX)

    async def get_owner_id(self, task_id: str) -> Optional[str]:
        # SQLAlchemy session is sync; run in a worker thread.
        return await asyncio.to_thread(self._sync_lookup, task_id)

    @staticmethod
    def _sync_lookup(task_id: str) -> Optional[str]:
        db = SessionLocal()
        try:
            row = (
                db.query(QuotationTask.owner_id)
                .filter(QuotationTask.task_id == task_id)
                .scalar()
            )
            value = str(row or "").strip()
            return value or None
        except Exception as exc:
            logger.warning(
                "[task_owner_registry] quotation lookup failed: task_id=%s err=%s",
                task_id,
                exc,
            )
            return None
        finally:
            db.close()


class _DocProcessingOwnerLookup:
    """doc_process_* tasks live in TaskManager Redis metadata."""

    PREFIX = "doc_process_"

    def matches(self, task_id: str) -> bool:
        return task_id.startswith(self.PREFIX)

    async def get_owner_id(self, task_id: str) -> Optional[str]:
        try:
            ts = await task_manager.get_task_status(task_id)
        except Exception as exc:
            logger.warning(
                "[task_owner_registry] doc_processing lookup failed: task_id=%s err=%s",
                task_id,
                exc,
            )
            return None
        if not ts:
            return None
        value = str(ts.metadata.get("owner_id", "")).strip()
        return value or None


class TaskOwnerRegistry:
    """In-memory cache fronted by an ordered chain of source-of-truth providers."""

    def __init__(self, lookups: List[TaskOwnerLookup]):
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._lookups: List[TaskOwnerLookup] = list(lookups)

    def cache(self, task_id: str, owner_id: str) -> None:
        """Warm the cache with an owner_id (no-op for empty strings)."""
        normalized = str(owner_id or "").strip()
        if not normalized:
            return
        with self._lock:
            self._cache[task_id] = normalized

    def forget(self, task_id: str) -> None:
        with self._lock:
            self._cache.pop(task_id, None)

    def peek_cache(self, task_id: str) -> str:
        """Sync cache-only read. Returns empty string on miss."""
        with self._lock:
            return self._cache.get(task_id, "")

    async def resolve(self, task_id: str) -> Optional[str]:
        """Cache -> first matching provider. Backfills cache on hit."""
        cached = self.peek_cache(task_id)
        if cached:
            return cached

        for lookup in self._lookups:
            if not lookup.matches(task_id):
                continue
            owner_id = await lookup.get_owner_id(task_id)
            if owner_id:
                self.cache(task_id, owner_id)
                return owner_id
            # First matching provider is authoritative for its domain.
            return None

        return None


task_owner_registry = TaskOwnerRegistry(
    [
        _QuotationOwnerLookup(),
        _DocProcessingOwnerLookup(),
    ]
)


async def resolve_task_owner_id(task_id: str) -> Optional[str]:
    """Convenience for callers (WS authz) that only need the resolved owner."""
    return await task_owner_registry.resolve(task_id)
