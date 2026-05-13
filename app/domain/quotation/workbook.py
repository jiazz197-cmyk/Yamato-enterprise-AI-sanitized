"""Build workbook data for quotation summary + detail sheet export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from app.ports.dto.quotation import QuotationSummarySelectionItem
from app.ports.dto.quotation_workbook import (
    QuotationDetailSheet,
    QuotationFixedChargeRow,
    QuotationSummaryRow,
    QuotationWorkbookData,
)

_FIXED_CHARGE_NAMES: tuple[str, ...] = (
    "\u6742\u9879",
    "FOB",
    "\u8fd0\u8f93\u8d39",
    "\u8bbe\u8ba1\u5de5\u65f6",
    "\u4eba\u5de5",
)
_AMOUNT_FIELD_CANDIDATES: tuple[str, ...] = (
    "\u603b\u4ef7",
    "\u91d1\u989d",
    "amount",
    "total_price",
    "totalPrice",
)


def _normalize_selection_items(items: Any) -> List[QuotationSummarySelectionItem]:
    if not isinstance(items, list):
        return []

    normalized: List[QuotationSummarySelectionItem] = []
    for raw in items:
        if isinstance(raw, QuotationSummarySelectionItem):
            normalized.append(raw)
            continue
        if not isinstance(raw, Mapping):
            continue
        normalized.append(
            QuotationSummarySelectionItem(
                selection_index=int(raw.get("selection_index") or 0),
                partid=str(raw.get("partid") or "").strip(),
                u8_parent_inv_code=str(raw.get("u8_parent_inv_code") or "").strip(),
                type_name=str(raw.get("type_name") or "").strip(),
                pdm_name=str(raw.get("pdm_name") or "").strip(),
                query_index=raw.get("query_index") if isinstance(raw.get("query_index"), int) else None,
                query_keywords=[
                    str(item).strip() for item in raw.get("query_keywords", []) if str(item).strip()
                ]
                if isinstance(raw.get("query_keywords"), list)
                else [],
                query_expanded_keywords=[
                    str(item).strip()
                    for item in raw.get("query_expanded_keywords", [])
                    if str(item).strip()
                ]
                if isinstance(raw.get("query_expanded_keywords"), list)
                else [],
                matched_pdm_row=bool(raw.get("matched_pdm_row")),
            )
        )
    return normalized


def _safe_summary_title(uploaded_file_name: str) -> str:
    stem = Path(uploaded_file_name or "").stem.strip()
    return stem or "\u62a5\u4ef7\u6c47\u603b"


def _rows_total_amount(rows: Iterable[Mapping[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in _AMOUNT_FIELD_CANDIDATES:
            value = row.get(key)
            if value is None:
                continue
            try:
                total += float(value)
            except (TypeError, ValueError):
                pass
            break
    return round(total, 4)


def _group_selection_by_type(
    selection_items: List[QuotationSummarySelectionItem],
) -> Dict[str, List[QuotationSummarySelectionItem]]:
    grouped: Dict[str, List[QuotationSummarySelectionItem]] = {}
    for item in sorted(selection_items, key=lambda x: x.selection_index):
        type_name = item.type_name.strip() or "Uncategorized"
        grouped.setdefault(type_name, []).append(item)
    return grouped


def _merge_texts(values: List[str]) -> str:
    seen: set[str] = set()
    merged: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return " / ".join(merged)


def build_quotation_workbook_data(
    *,
    uploaded_file_name: str,
    u8_result_by_type: Dict[str, Any],
    summary_selection_items: Any,
) -> QuotationWorkbookData:
    selection_items = _normalize_selection_items(summary_selection_items)
    selection_by_type = _group_selection_by_type(selection_items)

    groups = u8_result_by_type.get("items") if isinstance(u8_result_by_type, dict) else None
    detail_sheets: List[QuotationDetailSheet] = []
    summary_rows: List[QuotationSummaryRow] = []

    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            type_name = str(group.get("type") or "").strip() or "Uncategorized"
            rows = [
                item
                for item in (group.get("items") if isinstance(group.get("items"), list) else [])
                if isinstance(item, Mapping)
            ]
            total_amount = _rows_total_amount(rows)
            detail_sheets.append(
                QuotationDetailSheet(
                    sheet_name=type_name,
                    rows=[dict(row) for row in rows],
                    total_amount=total_amount,
                )
            )

            selected = selection_by_type.get(type_name, [])
            summary_rows.append(
                QuotationSummaryRow(
                    part_no=_merge_texts([item.partid for item in selected]),
                    name=_merge_texts([item.pdm_name for item in selected]) or type_name,
                    quantity_display="1",
                    unit_price=total_amount,
                    amount=total_amount,
                    detail_sheet_name=type_name,
                )
            )

    fixed_charge_rows = [QuotationFixedChargeRow(name=name) for name in _FIXED_CHARGE_NAMES]

    return QuotationWorkbookData(
        summary_sheet_name=_safe_summary_title(uploaded_file_name),
        summary_title=_safe_summary_title(uploaded_file_name),
        summary_rows=summary_rows,
        fixed_charge_rows=fixed_charge_rows,
        detail_sheets=detail_sheets,
    )
