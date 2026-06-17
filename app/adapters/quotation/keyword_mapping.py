"""Adapter: SpecificationMapping to keywords_payload."""

from __future__ import annotations

from typing import Any, Dict

from app.domain.quotation.exceptions import QuotationPipelineCancelledError
from app.domain.quotation.specification_mapping import SpecificationMapping
from app.ports.domains.quotation import CancelChecker, KeywordPayloadMappingPort


class KeywordPayloadMappingAdapter(KeywordPayloadMappingPort):
    def build_keywords_payload(
        self,
        extracted_info: Dict[str, Any],
        *,
        max_retries: int,
        cancel_checker: CancelChecker = None,
    ) -> Dict[str, Any]:
        if cancel_checker and cancel_checker():
            raise QuotationPipelineCancelledError("任务已取消")
        mapping = SpecificationMapping(extracted_info)
        return mapping.generate_keywords_payload(max_retries=max_retries)
