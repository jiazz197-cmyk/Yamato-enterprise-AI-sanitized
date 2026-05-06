"""Quotation generation outbound ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Protocol

from app.ports.dto.quotation import QuotationTaskSnapshot

CancelChecker = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, str], None]]


@dataclass
class RasterPageResult:
    """First-page rasterization output."""

    image_bytes: bytes
    suggested_filename_suffix: str


@dataclass
class TempObjectUploadResult:
    """Public URL and storage path for a temporary uploaded object."""

    public_url: str
    object_path: str


class FileStoragePort(Protocol):
    """Object storage abstraction for quotation files."""

    def upload_pdf(
        self,
        *,
        object_path: str,
        file_bytes: bytes,
        content_type: str,
    ) -> None:
        ...


class QuotationTaskRepoPort(Protocol):
    """Persistence boundary for quotation task + file metadata."""

    def create_file_record(
        self,
        *,
        file_name: str,
        unique_name: str,
        minio_path: str,
        content_type: str,
        file_size: int,
        uploader: str,
    ) -> int:
        ...

    def create_task(
        self,
        *,
        task_id: str,
        owner_id: str,
        owner_username: str,
        owner_ip: Optional[str],
        role_snapshot: str,
        uploaded_file_id: int,
        uploaded_file_name: str,
        display_name: str,
        uploaded_file_minio_path: str,
        uploaded_file_content_type: str,
        uploaded_file_size: int,
    ) -> QuotationTaskSnapshot:
        ...

    def get_task(self, task_id: str) -> Optional[QuotationTaskSnapshot]:
        ...

    def patch_task(self, task_id: str, updates: Dict[str, Any]) -> QuotationTaskSnapshot:
        ...

    def count_owner_queued_before(self, owner_id: str, created_at: datetime) -> int:
        ...

    def cleanup_task_files(self, task_id: str) -> Dict[str, Any]:
        ...

    def delete_task(self, task_id: str) -> None:
        ...


class PdfFirstPageRasterPort(Protocol):
    """Rasterize page 1 of a PDF to image bytes."""

    def rasterize_first_page(
        self,
        pdf_bytes: bytes,
        *,
        cancel_checker: CancelChecker = None,
    ) -> RasterPageResult:
        ...


class QuotationTempObjectStoragePort(Protocol):
    """Upload temporary quotation artifacts (e.g. page-1 JPEG) and return a fetchable URL."""

    def upload_temp_image(
        self,
        *,
        image_bytes: bytes,
        object_path: str,
        cancel_checker: CancelChecker = None,
    ) -> TempObjectUploadResult:
        ...


class OcrStructuredInfoPort(Protocol):
    """Run layout OCR and structured field extraction for quotation."""

    def extract_structured_info(
        self,
        *,
        image_url: str,
        ocr_api_url: str,
        max_retries: int,
        cancel_checker: CancelChecker = None,
    ) -> Dict[str, Any]:
        ...


class KeywordPayloadMappingPort(Protocol):
    """Map OCR extracted_info to PDM keywords_payload."""

    def build_keywords_payload(
        self,
        extracted_info: Dict[str, Any],
        *,
        max_retries: int,
        cancel_checker: CancelChecker = None,
    ) -> Dict[str, Any]:
        ...
