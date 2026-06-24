"""SQL Server integration errors."""

from __future__ import annotations

from typing import Callable, List, Optional

from app.domain.exceptions import QueryCancelledError

__all__ = [
    "QueryCancelledError",
    "U8RootFailureBreakerError",
    "raise_if_cancelled",
]


def raise_if_cancelled(cancel_checker: Optional[Callable[[], bool]]) -> None:
    if cancel_checker is not None and cancel_checker():
        raise QueryCancelledError("cancelled")


class U8RootFailureBreakerError(RuntimeError):
    """连续根节点失败达上限，判定系统性故障（ERP 宕机/连接耗尽/饱和）而中止任务。

    携带已失败根编码样本与计数，供调用方向用户/任务上报"哪些根被跳过、为何中止"。
    """

    def __init__(self, message: str, failed_root_codes: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.failed_root_codes: List[str] = list(failed_root_codes or [])
