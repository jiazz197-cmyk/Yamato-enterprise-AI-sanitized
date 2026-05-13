"""DTOs for rendering quotation workbooks with summary and detail sheets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class QuotationSummaryRow:
    part_no: str
    name: str
    quantity_display: str
    unit_price: float
    amount: float
    remark: str = ""
    detail_sheet_name: str = ""


@dataclass(frozen=True)
class QuotationFixedChargeRow:
    name: str
    quantity_display: str = ""
    unit_price: str = ""
    amount: str = ""
    remark: str = ""


@dataclass(frozen=True)
class QuotationDetailSheet:
    sheet_name: str
    rows: List[Dict[str, Any]]
    total_amount: float


@dataclass(frozen=True)
class QuotationWorkbookData:
    summary_sheet_name: str
    summary_title: str
    summary_rows: List[QuotationSummaryRow] = field(default_factory=list)
    fixed_charge_rows: List[QuotationFixedChargeRow] = field(default_factory=list)
    detail_sheets: List[QuotationDetailSheet] = field(default_factory=list)


@dataclass(frozen=True)
class QuotationWorkbookExport:
    content: bytes
