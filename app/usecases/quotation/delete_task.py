"""Usecase: delete terminal quotation task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.core.exceptions import APIException
from app.ports.contracts.tasking import TaskStatePort
from app.ports.domains.quotation import QuotationTaskRepoPort


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class DeleteQuotationTaskCommand:
    task_id: str


@dataclass
class DeleteQuotationTaskResult:
    success: bool
    message: str
    task_id: str
    cleanup: Dict[str, Any]
    task_record_removed: bool


class DeleteQuotationTaskUseCase:
    def __init__(self, task_repo: QuotationTaskRepoPort, task_state: TaskStatePort):
        self._task_repo = task_repo
        self._task_state = task_state

    async def execute(self, cmd: DeleteQuotationTaskCommand) -> DeleteQuotationTaskResult:
        task = self._task_repo.get_task(cmd.task_id)
        if task is None:
            raise APIException("任务不存在", status_code=404, error_code="NOT_FOUND")

        if task.status not in _TERMINAL_STATUSES:
            raise APIException(
                f"任务当前状态为 {task.status}，仅允许删除已结束任务",
                status_code=400,
                error_code="INVALID_TASK_STATUS",
            )

        cleanup_result = self._task_repo.cleanup_task_files(cmd.task_id)
        self._task_repo.delete_task(cmd.task_id)

        removed = False
        try:
            removed = await self._task_state.remove_task_record(cmd.task_id)
        except Exception:
            removed = False

        return DeleteQuotationTaskResult(
            success=True,
            message="任务已删除",
            task_id=cmd.task_id,
            cleanup=cleanup_result,
            task_record_removed=removed,
        )
