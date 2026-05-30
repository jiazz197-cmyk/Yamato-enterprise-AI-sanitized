"""Usecase: execute quotation Phase2 (PARTIDs → U8 BOM inventory)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.domain.quotation import (
    Phase2Result,
    QuotationPipelineCancelledError,
    QuotationPipelineError,
    convert_partids_to_u8_codes,
    group_u8_result_by_type,
    summarize_partid_list,
)
from app.ports.domains.quotation import CancelChecker, ProgressCallback
from app.ports.domains.sqlserver_queries import QueryCancelledError, U8BomInventoryQueryPort
from app.schemas.sqlserver import U8BomInventoryRequest

logger = get_logger("quotation.execute_phase2")

_U8_MAX_DEPTH = 3


def _response_to_dict(response: Any) -> Dict[str, Any]:
    dumper = getattr(response, "model_dump", None)
    if callable(dumper):
        return dumper()
    return response.dict()  # type: ignore[attr-defined]


@dataclass
class ExecuteQuotationPhase2Command:
    pdm_partids: List[str]
    keywords_payload: Optional[Dict[str, Any]] = None
    pdm_result: Optional[Dict[str, Any]] = None
    approved_partids: Optional[List[str]] = None
    progress_callback: ProgressCallback = None
    cancel_checker: CancelChecker = None


class ExecuteQuotationPhase2UseCase:
    def __init__(self, u8_query: U8BomInventoryQueryPort):
        self._u8_query = u8_query

    def _emit_progress(self, cb: ProgressCallback, progress: int, message: str) -> None:
        if cb:
            cb(progress, message)

    def _check_cancel(self, cancel_checker: CancelChecker) -> None:
        if cancel_checker and cancel_checker():
            raise QuotationPipelineCancelledError("任务已取消")

    def execute(self, cmd: ExecuteQuotationPhase2Command) -> Phase2Result:
        cb = cmd.progress_callback
        cancel = cmd.cancel_checker

        self._check_cancel(cancel)

        if not cmd.pdm_partids:
            raise QuotationPipelineError("PDM 结果未包含任何 PARTID，无法继续 U8 查询")

        selected_partids = [str(partid).strip() for partid in cmd.pdm_partids if str(partid).strip()]
        if not selected_partids:
            raise QuotationPipelineError("PDM 结果中的 PARTID 为空，无法继续 U8 查询")

        logger.info(
            "Phase2 输入 PARTID: raw_count=%s, normalized_count=%s, sample=%s",
            len(cmd.pdm_partids),
            len(selected_partids),
            selected_partids[:8],
        )

        converted_u8_codes, pdm_to_u8_mappings = convert_partids_to_u8_codes(selected_partids)
        if not converted_u8_codes:
            raise QuotationPipelineError("PDM PARTID 转换 U8 编码后为空，无法继续 U8 查询")

        logger.info(
            "Phase2 PARTID->U8 编码转换: input_count=%s, output_count=%s, sample=%s",
            len(selected_partids),
            len(converted_u8_codes),
            pdm_to_u8_mappings[:8],
        )

        parent_inv_codes = ",".join(converted_u8_codes)
        u8_summary = summarize_partid_list(converted_u8_codes)
        self._emit_progress(
            cb,
            70,
            f"正在执行 U8 BOM Inventory 查询 | 参数(U8编码): {u8_summary}",
        )
        self._check_cancel(cancel)

        parent_codes = [code.strip() for code in parent_inv_codes.split(",") if code.strip()]
        logger.info(
            "Phase2 U8 查询开始: parent_codes=%s, max_depth=%s, sample=%s",
            len(parent_codes),
            _U8_MAX_DEPTH,
            parent_codes[:5],
        )

        try:
            response = self._u8_query.run(
                U8BomInventoryRequest(parent_inv_codes=parent_inv_codes, max_depth=_U8_MAX_DEPTH),
                cancel_checker=cancel,
            )
        except QueryCancelledError as exc:
            raise QuotationPipelineCancelledError("U8 查询已取消") from exc

        self._check_cancel(cancel)

        u8_result = _response_to_dict(response)
        total = u8_result.get("total") if isinstance(u8_result, dict) else None
        items = u8_result.get("items") if isinstance(u8_result, dict) else None
        logger.info(
            "Phase2 U8 查询完成: total=%s, items_len=%s",
            total,
            len(items) if isinstance(items, list) else None,
        )

        if total == 0:
            logger.warning(
                "Phase2 U8 查询返回空结果: pdm_partids=%s, u8_parent_codes=%s",
                selected_partids,
                converted_u8_codes,
            )

        self._emit_progress(cb, 95, "U8 查询完成，正在收尾")

        u8_result_by_type: Dict[str, Any] = {"total": 0, "items": []}
        u8_result_type_summary: Dict[str, Any] = {"total_types": 0, "types": []}
        kw = cmd.keywords_payload
        if isinstance(kw, dict) and kw:
            u8_result_by_type, u8_result_type_summary = group_u8_result_by_type(
                keywords_payload=kw,
                pdm_result=cmd.pdm_result,
                approved_partids=cmd.approved_partids or selected_partids,
                u8_result=u8_result,
                pdm_to_u8_mappings=pdm_to_u8_mappings,
            )
            logger.info(
                "Phase2 U8 按 type 分组完成: total_types=%s, total_items=%s",
                u8_result_by_type.get("total"),
                u8_result_type_summary.get("total_items"),
            )

        return Phase2Result(
            u8_result=u8_result,
            u8_result_by_type=u8_result_by_type,
            u8_result_type_summary=u8_result_type_summary,
        )
