"""DTOs for quotation phase execution results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Phase1Result:
    """Phase 1 output: keywords + PDM response + extracted PARTIDs."""

    keywords_payload: Dict[str, Any]
    pdm_result: Dict[str, Any]
    pdm_partids: List[str]
    temp_image_minio_path: str
    temp_image_url: str
    raw_extracted_info: Dict[str, Any] = field(default_factory=dict)
    ocr_text: str = ""
    extract_method: str = ""
    parsed_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keywords_payload": self.keywords_payload,
            "pdm_result": self.pdm_result,
            "pdm_partids": self.pdm_partids,
            "temp_image_minio_path": self.temp_image_minio_path,
            "temp_image_url": self.temp_image_url,
            "raw_extracted_info": self.raw_extracted_info,
            "ocr_text": self.ocr_text,
            "extract_method": self.extract_method,
            "parsed_params": self.parsed_params,
        }


@dataclass
class Phase2Result:
    """Phase 2 output: final U8 BOM inventory response."""

    u8_result: Dict[str, Any]
    u8_result_by_type: Dict[str, Any] = field(default_factory=dict)
    u8_result_type_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "u8_result": self.u8_result,
            "u8_result_by_type": self.u8_result_by_type,
            "u8_result_type_summary": self.u8_result_type_summary,
        }
