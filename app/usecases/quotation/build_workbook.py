"""Usecase: build quotation workbook bytes from summary selection + grouped U8 data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.domain.quotation import build_quotation_workbook_data
from app.ports.domains.quotation_workbook import QuotationWorkbookRenderPort
from app.ports.dto.quotation_workbook import QuotationWorkbookExport


@dataclass
class BuildQuotationWorkbookCommand:
    uploaded_file_name: str
    u8_result_by_type: Dict[str, Any]
    summary_selection_items: Any = None


class BuildQuotationWorkbookUseCase:
    def __init__(self, render_port: QuotationWorkbookRenderPort):
        self._render_port = render_port

    def execute(self, cmd: BuildQuotationWorkbookCommand) -> QuotationWorkbookExport:
        workbook_data = build_quotation_workbook_data(
            uploaded_file_name=cmd.uploaded_file_name,
            u8_result_by_type=cmd.u8_result_by_type,
            summary_selection_items=cmd.summary_selection_items,
        )
        return self._render_port.export_workbook(workbook_data)
