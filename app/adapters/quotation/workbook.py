"""Openpyxl workbook renderer for quotation summary + detail sheets."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable, List, Mapping, MutableSet

from app.ports.domains.quotation_workbook import QuotationWorkbookRenderPort
from app.ports.dto.quotation_workbook import QuotationWorkbookData, QuotationWorkbookExport

_EXCLUDED_ROW_KEYS: frozenset[str] = frozenset({"__root_inv_code", "__parent_inv_code"})
_EXCEL_TITLE_INVALID = set(':*?/\\[]')

_SUMMARY_HEADERS = [
    "\u90e8\u54c1\u7f16\u53f7",
    "\u540d\u79f0",
    "\u6570\u91cf",
    "\u5355\u4ef7",
    "\u91d1\u989d",
    "\u5907\u6ce8",
    "\u5bf9\u5e94\u5b50\u9875",
]
_FIXED_CHARGE_HEADERS = [
    "\u56fa\u5b9a\u9879",
    "\u6570\u91cf",
    "\u5355\u4ef7",
    "\u91d1\u989d",
    "\u5907\u6ce8",
]


def _excel_sheet_title(raw: str, used: MutableSet[str]) -> str:
    chars: List[str] = []
    for c in str(raw or "")[:50]:
        if c in _EXCEL_TITLE_INVALID or ord(c) < 32:
            chars.append("_")
        else:
            chars.append(c)
    base = "".join(chars).strip("_") or "Sheet"
    base = base[:31]
    title = base
    n = 1
    while title in used:
        suffix = f"_{n}"
        title = (base[: 31 - len(suffix)] + suffix) if len(suffix) < 31 else f"S{n}"[:31]
        n += 1
    used.add(title)
    return title


def _collect_fieldnames(rows: Iterable[Mapping[str, Any]]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in row:
            if key in _EXCLUDED_ROW_KEYS:
                continue
            if key not in seen:
                seen.add(str(key))
                ordered.append(str(key))
    return ordered


class OpenpyxlQuotationWorkbookAdapter(QuotationWorkbookRenderPort):
    def export_workbook(self, workbook_data: QuotationWorkbookData) -> QuotationWorkbookExport:
        from openpyxl import Workbook  # noqa: PLC0415

        wb = Workbook()
        used_titles: set[str] = set()

        summary_ws = wb.active
        summary_ws.title = _excel_sheet_title(workbook_data.summary_sheet_name, used_titles)
        summary_ws["A1"] = workbook_data.summary_title
        summary_ws.append([])
        summary_ws.append(_SUMMARY_HEADERS)
        for row in workbook_data.summary_rows:
            summary_ws.append(
                [
                    row.part_no,
                    row.name,
                    row.quantity_display,
                    row.unit_price,
                    row.amount,
                    row.remark,
                    row.detail_sheet_name,
                ]
            )

        if workbook_data.fixed_charge_rows:
            summary_ws.append([])
            summary_ws.append(_FIXED_CHARGE_HEADERS)
            for row in workbook_data.fixed_charge_rows:
                summary_ws.append([row.name, row.quantity_display, row.unit_price, row.amount, row.remark])

        for detail_sheet in workbook_data.detail_sheets:
            ws = wb.create_sheet(title=_excel_sheet_title(detail_sheet.sheet_name, used_titles))
            if not detail_sheet.rows:
                ws["A1"] = "(no rows)"
                continue
            fieldnames = _collect_fieldnames(detail_sheet.rows)
            if not fieldnames:
                ws["A1"] = "(no rows)"
                continue
            ws.append(fieldnames)
            for row in detail_sheet.rows:
                ws.append([row.get(key) for key in fieldnames])

        bio = BytesIO()
        wb.save(bio)
        return QuotationWorkbookExport(content=bio.getvalue())
