"""Adapter: ``u8_result_by_type`` → per-type CSV strings and one multi-sheet ``.xlsx``."""

from __future__ import annotations

import csv
import re
from io import BytesIO, StringIO
from typing import Any, Dict, Iterable, List, Mapping, MutableSet

from app.ports.domains.u8_result_by_type_csv import (
    U8ResultByTypeCsvExport,
    U8ResultByTypeCsvPort,
    U8ResultByTypeXlsxExport,
)

_EXCLUDED_ROW_KEYS: frozenset[str] = frozenset({"__root_inv_code", "__parent_inv_code"})
_SAFE_KEY_RE = re.compile(r"[^\w\u4e00-\u9fff\-]+")
_EXCEL_TITLE_INVALID = set(':*?/\\[]')


def _sanitize_table_key(type_label: str, *, index: int) -> str:
    raw = str(type_label or "").strip() or f"type_{index}"
    cleaned = _SAFE_KEY_RE.sub("_", raw).strip("_")
    return cleaned or f"type_{index}"


def _excel_sheet_title(raw: str, used: MutableSet[str]) -> str:
    """Excel worksheet name: max 31 chars, unique, no : * ? / \\ [ ]."""
    chars: List[str] = []
    for c in raw[:50]:
        if c in _EXCEL_TITLE_INVALID:
            chars.append("_")
        elif ord(c) < 32:
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
    seen: MutableSet[str] = set()
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


def _group_rows_by_sheet(u8_result_by_type: Mapping[str, Any]) -> Dict[str, List[Mapping[str, Any]]]:
    groups = u8_result_by_type.get("items")
    if not isinstance(groups, list):
        return {}

    tables: Dict[str, List[Mapping[str, Any]]] = {}
    used_keys: MutableSet[str] = set()

    for idx, group in enumerate(groups):
        if not isinstance(group, Mapping):
            continue
        type_label = str(group.get("type") or "").strip()
        base_key = _sanitize_table_key(type_label, index=idx)
        key = base_key
        suffix = 1
        while key in used_keys:
            suffix += 1
            key = f"{base_key}_{suffix}"
        used_keys.add(key)

        raw_items = group.get("items")
        rows: List[Mapping[str, Any]] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, Mapping):
                    rows.append(item)

        tables[key] = rows

    return tables


def group_u8_bom_rows_by_table_key(
    u8_result_by_type: Mapping[str, Any],
) -> Dict[str, List[Mapping[str, Any]]]:
    """Split ``u8_result_by_type`` into table key → BOM row dicts.

    Keys and insertion order match :meth:`U8ResultByTypeCsvAdapter.export_csv_tables`
    and the worksheet sequence in :meth:`U8ResultByTypeCsvAdapter.export_xlsx_workbook`.
    """

    return _group_rows_by_sheet(u8_result_by_type)


def _rows_to_csv(rows: List[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    fieldnames = _collect_fieldnames(rows)
    if not fieldnames:
        return ""
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        writer.writerow({k: row.get(k) for k in fieldnames})
    return buf.getvalue()


def _rows_by_sheet_to_xlsx(rows_by_sheet: Dict[str, List[Mapping[str, Any]]]) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 — optional dependency at runtime

    wb = Workbook()
    wb.remove(wb.active)
    used_titles: MutableSet[str] = set()

    if not rows_by_sheet:
        ws = wb.create_sheet(title=_excel_sheet_title("Empty", used_titles))
        ws["A1"] = "(no grouped types / rows)"
        bio = BytesIO()
        wb.save(bio)
        return bio.getvalue()

    for sheet_key, rows in rows_by_sheet.items():
        title = _excel_sheet_title(sheet_key, used_titles)
        ws = wb.create_sheet(title=title)
        if not rows:
            ws["A1"] = "(no rows)"
            continue
        fieldnames = _collect_fieldnames(rows)
        if not fieldnames:
            ws["A1"] = "(no rows)"
            continue
        ws.append(fieldnames)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            ws.append([row.get(k) for k in fieldnames])

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


class U8ResultByTypeCsvAdapter(U8ResultByTypeCsvPort):
    """Per-type CSV strings and one ``.xlsx`` with a worksheet per type."""

    def export_csv_tables(self, u8_result_by_type: Mapping[str, Any]) -> U8ResultByTypeCsvExport:
        rows_by_sheet = _group_rows_by_sheet(u8_result_by_type)
        tables = {k: _rows_to_csv(v) for k, v in rows_by_sheet.items()}
        return U8ResultByTypeCsvExport(tables=tables)

    def export_xlsx_workbook(self, u8_result_by_type: Mapping[str, Any]) -> U8ResultByTypeXlsxExport:
        try:
            rows_by_sheet = _group_rows_by_sheet(u8_result_by_type)
            return U8ResultByTypeXlsxExport(content=_rows_by_sheet_to_xlsx(rows_by_sheet))
        except ImportError as exc:  # pragma: no cover — exercised when openpyxl missing
            raise ImportError(
                "export_xlsx_workbook requires the 'openpyxl' package (see requirements.txt)."
            ) from exc
