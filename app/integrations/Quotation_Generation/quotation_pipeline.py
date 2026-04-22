"""Two-phase quotation generation pipeline.

Phase 1: PDF -> OCR -> SpecificationMapping -> keywords_payload -> PDM BOM lookup.
Phase 2 (after user approval): PDM PARTIDs -> U8 BOM Inventory lookup (final output).

The two phases invoke the SQLServer query helpers directly (in-process), which
allows cooperative cancellation between SQL calls via `cancel_checker`.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.integrations.Quotation_Generation.SpecificationMapping import SpecificationMapping
from app.integrations.ocr.image2url import upload_file_to_minio
from app.integrations.ocr.infoextraction import extract_info, extract_layout_info
from app.integrations.ocr.pdf2image import pdf_to_single_image


class QuotationPipelineCancelledError(RuntimeError):
    """Raised when a task is cancelled in pipeline execution."""


class QuotationPipelineError(RuntimeError):
    """Raised for unrecoverable pipeline errors."""


ProgressCallback = Optional[Callable[[int, str], None]]
CancelChecker = Optional[Callable[[], bool]]


_U8_MAX_DEPTH = 20


@dataclass
class Phase1Result:
    """Phase 1 output: keywords + PDM response + extracted PARTIDs."""

    keywords_payload: Dict[str, Any]
    pdm_result: Dict[str, Any]
    pdm_partids: List[str]
    temp_image_minio_path: str
    temp_image_url: str
    raw_extracted_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keywords_payload": self.keywords_payload,
            "pdm_result": self.pdm_result,
            "pdm_partids": self.pdm_partids,
            "temp_image_minio_path": self.temp_image_minio_path,
            "temp_image_url": self.temp_image_url,
            "raw_extracted_info": self.raw_extracted_info,
        }


@dataclass
class Phase2Result:
    """Phase 2 output: final U8 BOM inventory response."""

    u8_result: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"u8_result": self.u8_result}


def _check_cancel(cancel_checker: CancelChecker) -> None:
    if cancel_checker and cancel_checker():
        raise QuotationPipelineCancelledError("任务已取消")


def _emit_progress(progress_callback: ProgressCallback, progress: int, message: str) -> None:
    if progress_callback:
        progress_callback(progress, message)


def _is_ocr_result_complete(info: Dict[str, Any]) -> bool:
    meta = info.get("meta")
    spec = info.get("spec")
    return isinstance(meta, dict) and bool(meta) and isinstance(spec, dict) and bool(spec)


# Keep only printable ASCII (0x20..0x7e). Non-ASCII characters such as CJK,
# Arabic, Hebrew, emoji, and arrow glyphs are dropped to guard against OCR
# hallucinations like "闪耀 الله عز وجل No" sneaking into PDM keywords.
_HALLUCINATION_KEEP_RATIO = 0.5


def _clean_ocr_text(text: str) -> str:
    """Return the ASCII-cleaned form of `text` or "" if the original appears to
    be OCR hallucination (more than half the non-whitespace characters dropped).
    """
    original = text.strip()
    if not original:
        return ""
    cleaned_chars = [ch for ch in original if 0x20 <= ord(ch) < 0x7F]
    cleaned = re.sub(r"\s+", " ", "".join(cleaned_chars)).strip()
    if not cleaned:
        return ""
    if len(cleaned) / len(original) < _HALLUCINATION_KEEP_RATIO:
        return ""
    return cleaned


def _clean_extracted_info(info: Any) -> Any:
    """Recursively clean every string leaf in `extracted_info`.

    - dict / list: walk children, rebuild container
    - str: run through `_clean_ocr_text`
    - everything else: returned as-is
    """
    if isinstance(info, dict):
        return {key: _clean_extracted_info(value) for key, value in info.items()}
    if isinstance(info, list):
        return [_clean_extracted_info(item) for item in info]
    if isinstance(info, str):
        return _clean_ocr_text(info)
    return info


def _extract_info_with_fallback(
    image_url: str,
    api_url: str,
    max_retries: int,
    cancel_checker: CancelChecker = None,
) -> Dict[str, Any]:
    retries = max(1, max_retries)
    last_info: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        _check_cancel(cancel_checker)
        try:
            content = extract_layout_info(image_url, api_url)
            info = extract_info(content)
            last_info = info
            if _is_ocr_result_complete(info):
                return info
        except Exception as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(2)

    if last_info is not None:
        return last_info
    if last_error is not None:
        raise last_error
    return {"meta": {}, "spec": {}}


def _response_to_dict(response: Any) -> Dict[str, Any]:
    dumper = getattr(response, "model_dump", None)
    if callable(dumper):
        return dumper()
    return response.dict()  # type: ignore[attr-defined]


def _run_pdm_query(keywords_payload: Dict[str, Any], cancel_checker: CancelChecker) -> Dict[str, Any]:
    # Lazy-import to avoid a circular import between quotation_generation and quotation_pipeline.
    from app.api.v1.sqlserver_queries import (
        PdmBomRequest,
        QueryCancelledError,
        run_pdm_bom_query,
    )

    keywords = keywords_payload.get("keywords") if isinstance(keywords_payload, dict) else None
    if keywords is None:
        keywords = keywords_payload
    try:
        response = run_pdm_bom_query(
            PdmBomRequest(keywords=keywords),
            cancel_checker=cancel_checker,
        )
    except QueryCancelledError as exc:
        raise QuotationPipelineCancelledError("PDM 查询已取消") from exc
    return _response_to_dict(response)


def _run_u8_query(
    parent_inv_codes: str,
    max_depth: int,
    cancel_checker: CancelChecker,
) -> Dict[str, Any]:
    from app.api.v1.sqlserver_queries import (
        QueryCancelledError,
        U8BomInventoryRequest,
        run_u8_bom_inventory_query,
    )

    try:
        response = run_u8_bom_inventory_query(
            U8BomInventoryRequest(parent_inv_codes=parent_inv_codes, max_depth=max_depth),
            cancel_checker=cancel_checker,
        )
    except QueryCancelledError as exc:
        raise QuotationPipelineCancelledError("U8 查询已取消") from exc
    return _response_to_dict(response)


def _summarize_pdm_query_params(
    keywords_payload: Dict[str, Any],
    max_attrs: int = 3,
    max_total_chars: int = 380,
) -> str:
    """Turn keywords_payload into a short human-readable summary for UI display.

    Keeps the full rendering of the first N types and collapses the remainder into
    ``…等 M 个 type`` so the string stays under ``max_total_chars``.
    """
    keywords = keywords_payload.get("keywords") if isinstance(keywords_payload, dict) else None
    if isinstance(keywords, dict):
        keywords = [keywords]
    if not isinstance(keywords, list) or not keywords:
        return "（无参数）"

    parts: List[str] = []
    for entry in keywords:
        if not isinstance(entry, dict):
            continue
        type_name = str(entry.get("type") or "").strip() or "未命名"
        attr = entry.get("attr") if isinstance(entry.get("attr"), dict) else {}
        if attr:
            items = list(attr.items())[:max_attrs]
            attr_texts = [f"{k}={v}" for k, v in items]
            if len(attr) > max_attrs:
                attr_texts.append("…")
            parts.append(f"{type_name}[{', '.join(attr_texts)}]")
        else:
            parts.append(type_name)
    if not parts:
        return "（无参数）"

    sep = " | "
    kept: List[str] = []
    for idx, part in enumerate(parts):
        candidate = sep.join(kept + [part])
        remaining = len(parts) - idx - 1
        suffix = f"{sep}…等 {remaining} 个 type" if remaining > 0 else ""
        if len(candidate) + len(suffix) > max_total_chars and kept:
            tail = f"…等 {len(parts) - len(kept)} 个 type"
            return sep.join(kept) + sep + tail
        kept.append(part)
    return sep.join(kept)


def _summarize_partid_list(partids: List[str], max_items: int = 5) -> str:
    """Turn a list of PARTIDs into a short human-readable summary."""
    if not partids:
        return "（无参数）"
    head = partids[:max_items]
    if len(partids) > max_items:
        return f"{', '.join(head)} 等共 {len(partids)} 个"
    return ", ".join(head)


def _collect_pdm_partids(pdm_result: Dict[str, Any]) -> List[str]:
    """Extract unique PARTID values from PDM BOM response while keeping order."""
    items = pdm_result.get("items") if isinstance(pdm_result, dict) else None
    if not isinstance(items, list):
        return []

    seen: set[str] = set()
    partids: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        partid = item.get("PARTID")
        if partid is None:
            continue
        value = str(partid).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        partids.append(value)
    return partids


def run_phase1_keywords_and_pdm(
    pdf_bytes: bytes,
    original_filename: str,
    progress_callback: ProgressCallback = None,
    cancel_checker: CancelChecker = None,
) -> Phase1Result:
    """Phase 1: PDF -> OCR -> keywords_payload -> PDM BOM response."""
    _emit_progress(progress_callback, 10, "正在将PDF第1页转换为图片")
    _check_cancel(cancel_checker)

    image_bytes, _ = pdf_to_single_image(pdf_bytes, dpi=200, quality=85, page_number=1)
    _emit_progress(progress_callback, 20, "正在上传中间图片到MinIO")
    _check_cancel(cancel_checker)

    temp_image_minio_path = f"temp/quotation/{uuid.uuid4().hex}_{original_filename}_page_001.jpg"
    temp_image_url = upload_file_to_minio(image_bytes, temp_image_minio_path)

    _emit_progress(progress_callback, 30, "正在提取OCR结构化信息")
    _check_cancel(cancel_checker)
    extracted_info = _extract_info_with_fallback(
        image_url=temp_image_url,
        api_url=settings.DOTS_OCR_ENDPOINT,
        max_retries=3,
        cancel_checker=cancel_checker,
    )
    extracted_info = _clean_extracted_info(extracted_info)

    _emit_progress(progress_callback, 40, "正在生成关键字映射")
    _check_cancel(cancel_checker)
    mapping = SpecificationMapping(extracted_info)
    keywords_payload = mapping.generate_keywords_payload(max_retries=3)

    pdm_query_summary = _summarize_pdm_query_params(keywords_payload)
    _emit_progress(
        progress_callback,
        45,
        f"正在执行 PDM BOM 查询 | 参数: {pdm_query_summary}",
    )
    _check_cancel(cancel_checker)
    pdm_result = _run_pdm_query(keywords_payload, cancel_checker)
    _check_cancel(cancel_checker)
    pdm_partids = _collect_pdm_partids(pdm_result)

    _emit_progress(progress_callback, 50, "PDM 查询完成，等待用户审核")

    return Phase1Result(
        keywords_payload=keywords_payload,
        pdm_result=pdm_result,
        pdm_partids=pdm_partids,
        temp_image_minio_path=temp_image_minio_path,
        temp_image_url=temp_image_url,
        raw_extracted_info=extracted_info,
    )


def run_phase2_u8_bom_inventory(
    pdm_partids: List[str],
    progress_callback: ProgressCallback = None,
    cancel_checker: CancelChecker = None,
) -> Phase2Result:
    """Phase 2: use PDM PARTIDs to query U8 BOM Inventory for the final output."""
    _check_cancel(cancel_checker)

    if not pdm_partids:
        raise QuotationPipelineError("PDM 结果未包含任何 PARTID，无法继续 U8 查询")

    parent_inv_codes = ",".join(pdm_partids)
    u8_summary = _summarize_partid_list(pdm_partids)
    _emit_progress(
        progress_callback,
        70,
        f"正在执行 U8 BOM Inventory 查询 | 参数: {u8_summary}",
    )
    _check_cancel(cancel_checker)

    u8_result = _run_u8_query(parent_inv_codes, _U8_MAX_DEPTH, cancel_checker)
    _check_cancel(cancel_checker)

    _emit_progress(progress_callback, 95, "U8 查询完成，正在收尾")

    return Phase2Result(u8_result=u8_result)
