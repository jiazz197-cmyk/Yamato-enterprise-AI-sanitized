"""Ports for building and rendering quotation workbooks."""

from __future__ import annotations

from typing import Protocol

from app.ports.dto.quotation_workbook import QuotationWorkbookData, QuotationWorkbookExport


class QuotationWorkbookRenderPort(Protocol):
    """Render a workbook data model into an `.xlsx` binary."""

    def export_workbook(self, workbook_data: QuotationWorkbookData) -> QuotationWorkbookExport:
        ...
