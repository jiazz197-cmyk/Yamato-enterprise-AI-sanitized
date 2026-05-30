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
]
_DETAIL_TOTAL_FIELD_CANDIDATES = (
    "\u603b\u4ef7",
    "\u91d1\u989d",
    "amount",
    "total_price",
    "totalPrice",
)


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


def _detail_total_column_index(fieldnames: List[str]) -> int | None:
    for idx, fieldname in enumerate(fieldnames):
        if fieldname in _DETAIL_TOTAL_FIELD_CANDIDATES:
            return idx
    return None


class OpenpyxlQuotationWorkbookAdapter(QuotationWorkbookRenderPort):
    def export_workbook(self, workbook_data: QuotationWorkbookData) -> QuotationWorkbookExport:
        from openpyxl import Workbook  # noqa: PLC0415
        from openpyxl.styles import Border, Font, Side  # noqa: PLC0415

        wb = Workbook()
        used_titles: set[str] = set()
        bold_font = Font(bold=True)
        thin_side = Side(style="thin")
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        summary_ws = wb.active
        summary_ws.title = _excel_sheet_title(workbook_data.summary_sheet_name, used_titles)

        meta = workbook_data.summary_meta
        summary_ws["C6"] = meta.pricing_title or workbook_data.summary_title
        summary_ws["F1"] = "\u62a5\u4ef7\u7f16\u53f7\uff1a"
        summary_ws["G1"] = meta.quote_number
        summary_ws["F2"] = "\u5236\u9020\u7f16\u53f7\uff1a"
        summary_ws["G2"] = meta.manufacturing_number
        summary_ws["F3"] = "\u578b\u53f7\uff1a"
        summary_ws["G3"] = meta.model
        summary_ws["F4"] = "\u7f16\u5236\uff1a"
        summary_ws["G4"] = meta.prepared_by
        summary_ws["F5"] = "\u5ba1\u6838\uff1a"
        summary_ws["G5"] = meta.reviewed_by
        summary_ws["F6"] = "\u62a5\u4ef7\u65e5\u671f\uff1a"
        summary_ws["G6"] = meta.quote_date
        summary_ws["E8"] = meta.tax_note
        summary_ws["E9"] = "\u5355\u4f4d\uff1a"
        summary_ws["F9"] = meta.currency_label
        summary_ws["E10"] = "\u603b\u8ba1\uff1a"
        summary_ws["F10"] = meta.grand_total
        summary_ws["B10"] = meta.table_title
        summary_ws.append([])

        summary_header_row = 11
        for col_idx, header in enumerate(_SUMMARY_HEADERS, start=2):
            summary_ws.cell(row=summary_header_row, column=col_idx, value=header)

        row_idx = summary_header_row + 1
        for row in workbook_data.summary_rows:
            summary_ws.cell(row=row_idx, column=2, value=row.part_no)
            summary_ws.cell(row=row_idx, column=3, value=row.name)
            summary_ws.cell(row=row_idx, column=4, value=row.quantity_display)
            summary_ws.cell(row=row_idx, column=5, value=row.unit_price)
            summary_ws.cell(row=row_idx, column=6, value=row.amount)
            summary_ws.cell(row=row_idx, column=7, value=row.remark)
            row_idx += 1

        if workbook_data.fixed_charge_rows:
            for row in workbook_data.fixed_charge_rows:
                summary_ws.cell(row=row_idx, column=2, value=row.name)
                summary_ws.cell(row=row_idx, column=3, value=row.quantity_display)
                summary_ws.cell(row=row_idx, column=4, value=row.unit_price)
                summary_ws.cell(row=row_idx, column=5, value=row.amount)
                summary_ws.cell(row=row_idx, column=6, value=row.remark)
                row_idx += 1

        for row in summary_ws.iter_rows():
            for cell in row:
                if cell.value not in (None, ""):
                    cell.font = bold_font

        for cell_range in ("F1:G6", "E8:F10", f"B11:G{row_idx - 1}"):
            for rows in summary_ws[cell_range]:
                for cell in rows:
                    cell.border = thin_border

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
            total_col_idx = _detail_total_column_index(fieldnames)
            if total_col_idx is not None:
                total_row = [None] * len(fieldnames)
                total_row[total_col_idx] = detail_sheet.total_amount
                ws.append(total_row)

        bio = BytesIO()
        wb.save(bio)
        return QuotationWorkbookExport(content=bio.getvalue())
