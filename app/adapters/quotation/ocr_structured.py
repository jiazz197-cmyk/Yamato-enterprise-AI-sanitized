"""Adapter: OCR layout + structured extraction for quotation."""

from __future__ import annotations

from typing import Any, Dict

from app.integrations.Quotation_Generation.quotation_ocr_helpers import (
    clean_extracted_info,
    extract_structured_info_with_fallback,
)
from app.ports.domains.quotation import CancelChecker, OcrStructuredInfoPort


class OcrStructuredInfoAdapter(OcrStructuredInfoPort):
    def extract_structured_info(
        self,
        *,
        image_url: str,
        ocr_api_url: str,
        max_retries: int,
        cancel_checker: CancelChecker = None,
    ) -> Dict[str, Any]:
        raw = extract_structured_info_with_fallback(
            image_url=image_url,
            api_url=ocr_api_url,
            max_retries=max_retries,
            cancel_checker=cancel_checker,
        )
        return clean_extracted_info(raw)
