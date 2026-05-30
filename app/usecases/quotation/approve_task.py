"""Usecase: approve quotation phase-1 result and dispatch phase-2."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import APIException
from app.domain.quotation import build_summary_selection_items
from app.ports.contracts.tasking import TaskDispatchPort, TaskStatePort
from app.ports.domains.quotation import QuotationApprovalSelectionPort, QuotationTaskRepoPort


@dataclass
class ApproveQuotationTaskCommand:
    task_id: str
    approved_partids: list[str]
    extra_partids: list[str] = None

    def __post_init__(self) -> None:
        if self.extra_partids is None:
            self.extra_partids = []


@dataclass
class ApproveQuotationTaskResult:
    success: bool
    message: str
    task_id: str
    status: str
    approved_count: int


class ApproveQuotationTaskUseCase:
    def __init__(
        self,
        task_repo: QuotationTaskRepoPort,
        approval_selection: QuotationApprovalSelectionPort,
        task_state: TaskStatePort,
        task_dispatch: TaskDispatchPort,
    ):
        self._task_repo = task_repo
        self._approval_selection = approval_selection
        self._task_state = task_state
        self._task_dispatch = task_dispatch

    async def execute(self, cmd: ApproveQuotationTaskCommand) -> ApproveQuotationTaskResult:
        task = self._task_repo.get_task(cmd.task_id)
        if task is None:
            raise APIException("任务不存在", status_code=404, error_code="NOT_FOUND")

        if task.status != "awaiting_approval":
            raise APIException(
                f"任务当前状态为 {task.status}，无法执行审核同意",
                status_code=409,
                error_code="INVALID_TASK_STATUS",
            )

        payload = dict(task.result_payload or {})
        available_partids = payload.get("pdm_partids") if isinstance(payload, dict) else None
        if not isinstance(available_partids, list) or not available_partids:
            raise APIException(
                "任务缺少 PDM PARTID，无法继续 U8 查询",
                status_code=422,
                error_code="MISSING_PDM_PARTIDS",
            )

        available_set = {str(item).strip() for item in available_partids if str(item).strip()}
        seen: set[str] = set()
        approved_partids: list[str] = []
        unknown_partids: list[str] = []

        for raw in cmd.approved_partids:
            value = str(raw).strip()
            if not value or value in seen:
                continue
            if value not in available_set:
                unknown_partids.append(value)
                continue
            seen.add(value)
            approved_partids.append(value)

        if unknown_partids:
            raise APIException(
                f"审核列表包含未知 PARTID: {', '.join(unknown_partids)}",
                status_code=400,
                error_code="UNKNOWN_PARTIDS",
            )
        if not approved_partids and not cmd.extra_partids:
            raise APIException(
                "审核列表为空，至少需要保留 1 个 PARTID",
                status_code=422,
                error_code="EMPTY_APPROVAL_LIST",
            )

        # Merge manually supplied extra PARTIDs (not validated against pdm_partids)
        extra_clean: list[str] = []
        for raw in cmd.extra_partids:
            value = str(raw).strip()
            if value and value not in seen:
                seen.add(value)
                extra_clean.append(value)

        final_partids = approved_partids + extra_clean

        if not final_partids:
            raise APIException(
                "审核列表为空，至少需要保留 1 个 PARTID",
                status_code=422,
                error_code="EMPTY_APPROVAL_LIST",
            )

        summary_selection_items = build_summary_selection_items(
            approved_partids=final_partids,
            pdm_result=payload.get("pdm_result") if isinstance(payload.get("pdm_result"), dict) else {},
            keywords_payload=(
                payload.get("keywords_payload") if isinstance(payload.get("keywords_payload"), dict) else {}
            ),
        )
        self._approval_selection.save_approved_selection(
            task_id=cmd.task_id,
            approved_partids=final_partids,
            summary_selection_items=summary_selection_items,
        )

        progress = max(task.progress, 55)
        if extra_clean:
            message = f"已同意 {len(approved_partids)} 项 + {len(extra_clean)} 手动项，开始 U8 查询"
        else:
            message = f"已同意 {len(approved_partids)}/{len(available_partids)} 项，开始 U8 查询"

        updated = self._task_repo.patch_task(
            cmd.task_id,
            {
                "status": "running",
                "message": message,
                "progress": progress,
                "error": None,
                "awaiting_approval_at": None,
            },
        )

        await self._task_state.update_status(cmd.task_id, "running", message)
        self._task_dispatch.dispatch_phase2(cmd.task_id, updated.owner_id)

        return ApproveQuotationTaskResult(
            success=True,
            message="已触发 U8 BOM Inventory 查询",
            task_id=cmd.task_id,
            status=updated.status,
            approved_count=len(final_partids),
        )
