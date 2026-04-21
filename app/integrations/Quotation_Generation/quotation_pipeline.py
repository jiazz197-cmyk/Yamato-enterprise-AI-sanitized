"""Quotation generation pipeline for uploaded PDF files."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.core.config import settings
from app.integrations.Quotation_Generation.SpecificationMapping import SpecificationMapping
from app.integrations.ocr.image2url import upload_file_to_minio
from app.integrations.ocr.infoextraction import extract_info, extract_layout_info
from app.integrations.ocr.pdf2image import pdf_to_single_image


class QuotationPipelineCancelledError(RuntimeError):
    """Raised when a task is cancelled in pipeline execution."""


ProgressCallback = Optional[Callable[[int, str], None]]
CancelChecker = Optional[Callable[[], bool]]


@dataclass
class QuotationPipelineResult:
    """Pipeline output data."""

    raw_extracted_info: Dict[str, Any]
    mapping_output: Dict[str, str]
    mapping_output_list: list[str]
    full_output_text: str
    keywords_payload: Dict[str, Any]
    temp_image_minio_path: str
    temp_image_url: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_extracted_info": self.raw_extracted_info,
            "mapping_output": self.mapping_output,
            "mapping_output_list": self.mapping_output_list,
            "full_output_text": self.full_output_text,
            "keywords_payload": self.keywords_payload,
            "temp_image_minio_path": self.temp_image_minio_path,
            "temp_image_url": self.temp_image_url,
        }


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


def run_quotation_pipeline(
    pdf_bytes: bytes,
    original_filename: str,
    progress_callback: ProgressCallback = None,
    cancel_checker: CancelChecker = None,
) -> QuotationPipelineResult:
    """Run PDF page-1 OCR extraction and specification mapping."""
    _emit_progress(progress_callback, 10, "正在将PDF第1页转换为图片")
    _check_cancel(cancel_checker)

    image_bytes, _ = pdf_to_single_image(pdf_bytes, dpi=200, quality=85, page_number=1)
    _emit_progress(progress_callback, 30, "正在上传中间图片到MinIO")
    _check_cancel(cancel_checker)

    temp_image_minio_path = f"temp/quotation/{uuid.uuid4().hex}_{original_filename}_page_001.jpg"
    temp_image_url = upload_file_to_minio(image_bytes, temp_image_minio_path)

    _emit_progress(progress_callback, 55, "正在提取OCR结构化信息")
    _check_cancel(cancel_checker)
    extracted_info = _extract_info_with_fallback(
        image_url=temp_image_url,
        api_url=settings.DOTS_OCR_ENDPOINT,
        max_retries=3,
        cancel_checker=cancel_checker,
    )

    _emit_progress(progress_callback, 80, "正在生成报价映射结果")
    _check_cancel(cancel_checker)
    mapping = SpecificationMapping(extracted_info)
    keywords_payload = mapping.generate_keywords_payload(max_retries=3)
    mapping_output = mapping.generate_output_mapping()
    mapping_output_list = mapping.generate_output_list()
    full_output_text = mapping.generate_full_output()

    _emit_progress(progress_callback, 95, "报价结果生成完成，正在收尾")

    return QuotationPipelineResult(
        raw_extracted_info=extracted_info,
        mapping_output=mapping_output,
        mapping_output_list=mapping_output_list,
        full_output_text=full_output_text,
        keywords_payload=keywords_payload,
        temp_image_minio_path=temp_image_minio_path,
        temp_image_url=temp_image_url,
    )

