"""Group flat U8 BOM rows by product type from keywords + PDM→U8 mapping (pure)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def group_u8_result_by_type(
    *,
    keywords_payload: Dict[str, Any],
    u8_result: Dict[str, Any],
    pdm_to_u8_mappings: List[Dict[str, str]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build type-grouped U8 payload using PDM->U8 mapping + U8 root code.

    Returns:
        (u8_result_by_type, u8_result_type_summary)
    """
    items = u8_result.get("items") if isinstance(u8_result, dict) else None
    if not isinstance(items, list):
        return {"total": 0, "items": []}, {"total_types": 0, "types": []}

    keywords = keywords_payload.get("keywords") if isinstance(keywords_payload, dict) else None
    if isinstance(keywords, dict):
        keywords = [keywords]
    if not isinstance(keywords, list):
        keywords = []

    mapped_order: List[str] = []
    mapped_set: set[str] = set()
    for mapping in pdm_to_u8_mappings:
        if not isinstance(mapping, dict):
            continue
        code = str(mapping.get("u8_parent_inv_code") or "").strip()
        if not code or code in mapped_set:
            continue
        mapped_set.add(code)
        mapped_order.append(code)

    type_entries: List[Dict[str, Any]] = []
    type_to_codes: Dict[str, List[str]] = {}
    fallback_name = "未命名"

    for idx, entry in enumerate(keywords, start=1):
        if not isinstance(entry, dict):
            continue
        type_name = str(entry.get("type") or "").strip() or fallback_name
        part_code = mapped_order[idx - 1] if idx - 1 < len(mapped_order) else ""
        if not part_code:
            continue
        type_to_codes.setdefault(type_name, []).append(part_code)
        type_entries.append(
            {
                "query_index": idx,
                "type": type_name,
                "u8_parent_inv_code": part_code,
                "matched": True,
            }
        )

    root_to_rows: Dict[str, List[Dict[str, Any]]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        root_code = str(raw.get("__root_inv_code") or "").strip()
        if not root_code:
            continue
        root_to_rows.setdefault(root_code, []).append(raw)

    grouped_items: List[Dict[str, Any]] = []
    for type_name, codes in type_to_codes.items():
        rows: List[Dict[str, Any]] = []
        for code in codes:
            rows.extend(root_to_rows.get(code, []))
        grouped_items.append(
            {
                "type": type_name,
                "u8_parent_inv_codes": codes,
                "total": len(rows),
                "items": rows,
            }
        )

    unmatched_codes = [code for code in mapped_order if code not in root_to_rows]
    summary = {
        "total_types": len(grouped_items),
        "total_items": len(items),
        "matched_root_codes": len(mapped_order) - len(unmatched_codes),
        "unmatched_root_codes": unmatched_codes,
        "types": [
            {
                "type": item.get("type"),
                "u8_parent_inv_codes": item.get("u8_parent_inv_codes"),
                "total": item.get("total"),
            }
            for item in grouped_items
        ],
        "mapping": type_entries,
    }

    grouped = {
        "total": len(grouped_items),
        "items": grouped_items,
    }
    return grouped, summary
