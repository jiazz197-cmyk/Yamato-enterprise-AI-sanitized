"""Usecase: execute quotation Phase1 (PDF → keywords → PDM)."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any, Dict

from app.core.config import settings
from app.domain.quotation import (
    Phase1Result,
    QuotationPipelineCancelledError,
    collect_pdm_partids,
    summarize_pdm_query_params,
)
from app.integrations.sqlserver.exceptions import QueryCancelledError
from app.ports.domains.quotation import (
    CancelChecker,
    KeywordPayloadMappingPort,
    OcrStructuredInfoPort,
    PdfFirstPageRasterPort,
    ProgressCallback,
    QuotationTempObjectStoragePort,
)
from app.ports.domains.sqlserver_queries import PdmBomQueryPort
from app.schemas.sqlserver import PdmBomRequest


def _response_to_dict(response: Any) -> Dict[str, Any]:
    dumper = getattr(response, "model_dump", None)
    if callable(dumper):
        return dumper()
    return response.dict()  # type: ignore[attr-defined]


@dataclass
class ExecuteQuotationPhase1Command:
    pdf_bytes: bytes
    original_filename: str
    progress_callback: ProgressCallback = None
    cancel_checker: CancelChecker = None


class ExecuteQuotationPhase1UseCase:
    def __init__(
        self,
        pdf_raster: PdfFirstPageRasterPort,
        temp_storage: QuotationTempObjectStoragePort,
        ocr: OcrStructuredInfoPort,
        keyword_mapping: KeywordPayloadMappingPort,
        pdm_query: PdmBomQueryPort,
    ):
        self._pdf_raster = pdf_raster
        self._temp_storage = temp_storage
        self._ocr = ocr
        self._keyword_mapping = keyword_mapping
        self._pdm_query = pdm_query

    def _emit_progress(self, cb: ProgressCallback, progress: int, message: str) -> None:
        if cb:
            cb(progress, message)

    def _check_cancel(self, cancel_checker: CancelChecker) -> None:
        if cancel_checker and cancel_checker():
            raise QuotationPipelineCancelledError("任务已取消")

    def execute(self, cmd: ExecuteQuotationPhase1Command) -> Phase1Result:
        cb = cmd.progress_callback
        cancel = cmd.cancel_checker

        self._emit_progress(cb, 10, "正在将PDF第1页转换为图片")
        self._check_cancel(cancel)
        raster = self._pdf_raster.rasterize_first_page(cmd.pdf_bytes, cancel_checker=cancel)

        self._emit_progress(cb, 20, "正在上传中间图片到MinIO")
        self._check_cancel(cancel)
        temp_image_minio_path = f"temp/quotation/{uuid.uuid4().hex}_{cmd.original_filename}_page_001.jpg"
        upload = self._temp_storage.upload_temp_image(
            image_bytes=raster.image_bytes,
            object_path=temp_image_minio_path,
            cancel_checker=cancel,
        )

        self._emit_progress(cb, 30, "正在提取OCR结构化信息")
        self._check_cancel(cancel)
        extracted_info = self._ocr.extract_structured_info(
            image_url=upload.public_url,
            ocr_api_url=settings.DOTS_OCR_ENDPOINT,
            max_retries=3,
            cancel_checker=cancel,
        )

        self._emit_progress(cb, 40, "正在生成关键字映射")
        self._check_cancel(cancel)
        keywords_payload = self._keyword_mapping.build_keywords_payload(
            extracted_info,
            max_retries=3,
            cancel_checker=cancel,
        )

        pdm_query_summary = summarize_pdm_query_params(keywords_payload)
        self._emit_progress(
            cb,
            45,
            f"正在执行 PDM BOM 查询 | 参数: {pdm_query_summary}",
        )
        self._check_cancel(cancel)

        keywords = keywords_payload.get("keywords") if isinstance(keywords_payload, dict) else None
        if keywords is None:
            keywords = keywords_payload

        try:
            response = self._pdm_query.run(
                PdmBomRequest(keywords=keywords),
                cancel_checker=cancel,
            )
        except QueryCancelledError as exc:
            raise QuotationPipelineCancelledError("PDM 查询已取消") from exc

        self._check_cancel(cancel)
        pdm_result = _response_to_dict(response)
        pdm_partids = collect_pdm_partids(pdm_result)

        self._emit_progress(cb, 50, "PDM 查询完成，等待用户审核")

        return Phase1Result(
            keywords_payload=keywords_payload,
            pdm_result=pdm_result,
            pdm_partids=pdm_partids,
            temp_image_minio_path=upload.object_path,
            temp_image_url=upload.public_url,
            raw_extracted_info=extracted_info,
        )
