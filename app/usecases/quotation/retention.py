"""Quotation task retention: delegates to port."""

from __future__ import annotations

from app.ports.domains.quotation import QuotationTaskRetentionPort


class PurgeOldTerminalTasksUseCase:
    """Drop oldest terminal tasks when global row count exceeds threshold."""

    def __init__(self, retention_port: QuotationTaskRetentionPort):
        self._retention = retention_port

    async def execute(self, *, max_total: int = 100, target: int = 50) -> int:
        return await self._retention.purge_old_terminal_tasks_global(
            max_total=max_total, target=target
        )


class ExpireAwaitingApprovalTasksUseCase:
    """Hard-delete awaiting_approval tasks that exceeded the TTL."""

    def __init__(self, retention_port: QuotationTaskRetentionPort):
        self._retention = retention_port

    async def execute(self, *, ttl_hours: int = 24) -> int:
        return await self._retention.expire_awaiting_approval_tasks(ttl_hours=ttl_hours)


async def purge_old_terminal_tasks_global(
    retention_port: QuotationTaskRetentionPort,
    *,
    max_total: int = 100,
    target: int = 50,
) -> int:
    """Convenience function for backward compatibility."""
    return await retention_port.purge_old_terminal_tasks_global(
        max_total=max_total, target=target
    )


async def expire_awaiting_approval_tasks(
    retention_port: QuotationTaskRetentionPort,
    *,
    ttl_hours: int = 24,
) -> int:
    """Convenience function for backward compatibility."""
    return await retention_port.expire_awaiting_approval_tasks(ttl_hours=ttl_hours)
