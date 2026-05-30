"""U8 BOM + Inventory recursive walk.

`InvCode` / PartId style codes use `.replace(\"'\", \"''\")` before embedding in N'...' SQL
literals. Parent codes are normalized from trusted API input, not ad-hoc SQL.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger

from app.integrations.sqlserver.client import close_sql_client, get_sql_client
from app.integrations.sqlserver.exceptions import raise_if_cancelled

logger = get_logger("database.sqlserver")


def split_parent_inv_codes(value: Any) -> List[str]:
    """Normalize parent_inv_codes input; dedupe by order."""
    if value is None:
        return []

    codes: List[str] = []
    if isinstance(value, str):
        parts = re.split(r"[;,/|\s、，；]+", value)
        for part in parts:
            code = part.strip()
            if code:
                codes.append(code)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            code = str(item).strip()
            if code:
                codes.append(code)
    else:
        code = str(value).strip()
        if code:
            codes.append(code)

    return list(dict.fromkeys(codes))


def _query_u8_bom_inventory(
    parent_codes: List[str],
    max_depth: int,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    if not parent_codes:
        return []

    client = get_sql_client(
        {
            "backend": "pymssql",
            "server": settings.U8_SQLSERVER_HOST,
            "port": settings.U8_SQLSERVER_PORT,
            "database": settings.U8_SQLSERVER_DATABASE,
            "username": settings.U8_SQLSERVER_USER,
            "password": settings.U8_SQLSERVER_PASSWORD,
            "encrypt": settings.U8_SQLSERVER_ENCRYPT,
        }
    )

    children_cache: Dict[str, List[Dict[str, Any]]] = {}
    root_codes_set = set(parent_codes)

    def to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _probe_partmap_hits(code: str) -> Dict[str, Optional[int]]:
        safe_code = code.replace("'", "''")
        probe_sql = f"""
            SELECT
                SUM(CASE WHEN COALESCE(
                    NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
                    NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
                ) = N'{safe_code}' THEN 1 ELSE 0 END) AS InvCodeHits,
                SUM(CASE WHEN CAST(vp.PartId AS NVARCHAR(100)) = N'{safe_code}' THEN 1 ELSE 0 END) AS PartIdHits
            FROM v_bas_part vp
        """
        try:
            rows = client.query(probe_sql)
            first = rows[0] if rows else {}
            inv_hits_raw = first.get("InvCodeHits") if isinstance(first, dict) else None
            part_hits_raw = first.get("PartIdHits") if isinstance(first, dict) else None
            return {
                "inv_code_hits": int(inv_hits_raw) if inv_hits_raw is not None else None,
                "part_id_hits": int(part_hits_raw) if part_hits_raw is not None else None,
            }
        except Exception as exc:
            logger.warning("U8 PartMap 命中探针失败: code=%s, error=%s", code, exc)
            return {"inv_code_hits": None, "part_id_hits": None}

    def fetch_children(parent_inv_code: str) -> List[Dict[str, Any]]:
        if parent_inv_code in children_cache:
            return children_cache[parent_inv_code]

        raise_if_cancelled(cancel_checker)
        safe_code = parent_inv_code.replace("'", "''")
        sql = f"""
            ;WITH PartMap AS (
                SELECT
                    vp.PartId,
                    COALESCE(
                        NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
                        NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
                    ) AS PartInvCode
                FROM v_bas_part vp
            ),
            RawData AS (
                SELECT
                    parent.PartInvCode AS ParentInvCode,
                    child.PartInvCode AS ChildInvCode,
                    oc.BomId,
                    b.ModifyDate,
                    b.ModifyTime,
                    oc.SortSeq,
                    oc.BaseQtyN,
                    oc.BaseQtyD,
                    oc.CompScrap,
                    CAST(1.0 * oc.BaseQtyN / NULLIF(oc.BaseQtyD, 0) AS DECIMAL(38,12)) AS QtyPer,
                    ic.cInvName,
                    ic.iInvSprice,
                    ic.iInvNcost,
                    ic.cInvStd,
                    ic.cInvDepCode,
                    ic.cDefWareHouse,
                    child.PartId AS ChildPartId,
                    ROW_NUMBER() OVER (
                        PARTITION BY parent.PartInvCode, child.PartInvCode
                        ORDER BY b.ModifyDate DESC, b.ModifyTime DESC, oc.SortSeq
                    ) AS rn
                FROM PartMap parent
                JOIN bom_parent bp ON bp.ParentId = parent.PartId
                JOIN bom_opcomponent oc ON oc.BomId = bp.BomId
                JOIN bom_bom b ON b.BomId = bp.BomId AND b.Status = 3
                JOIN PartMap child ON child.PartId = oc.ComponentId
                LEFT JOIN Inventory ic ON ic.cInvCode = child.PartInvCode
                WHERE parent.PartInvCode = N'{safe_code}'
            )
            SELECT
                ParentInvCode, ChildInvCode, BomId, ModifyDate, ModifyTime,
                SortSeq, BaseQtyN, BaseQtyD, CompScrap, QtyPer,
                cInvName, iInvSprice, iInvNcost, cInvStd, cInvDepCode, cDefWareHouse, ChildPartId
            FROM RawData
            WHERE rn = 1
            ORDER BY SortSeq, ChildInvCode
        """
        rows = client.query(sql)
        if not rows and parent_inv_code in root_codes_set:
            probe = _probe_partmap_hits(parent_inv_code)
            logger.warning(
                "U8 根节点无子件: parent_code=%s, inv_code_hits=%s, part_id_hits=%s",
                parent_inv_code,
                probe.get("inv_code_hits"),
                probe.get("part_id_hits"),
            )
        children_cache[parent_inv_code] = rows
        return rows

    result_rows: List[Dict[str, Any]] = []

    def walk(
        root_code: str,
        parent_code: str,
        level: int,
        cumulative_qty: float,
        visited_part_ids: set[str],
    ) -> None:
        if level > max_depth:
            return

        children = fetch_children(parent_code)
        if not children:
            return

        for child in children:
            child_part_id = str(child.get("ChildPartId") or "").strip()
            child_inv_code = str(child.get("ChildInvCode") or "").strip()

            if child_part_id and child_part_id in visited_part_ids:
                continue

            qty_per = to_float(child.get("QtyPer"), 0.0)
            child_cumulative_qty = cumulative_qty * qty_per
            inv_cost = child.get("iInvNcost")
            inv_cost_num = to_float(inv_cost, 0.0) if inv_cost is not None else None
            total_price = child_cumulative_qty * inv_cost_num if inv_cost_num is not None else None

            result_rows.append(
                {
                    "ROOT_INV_CODE": root_code,
                    "ParentInvCode": parent_code,
                    "ChildInvCode": child_inv_code,
                    "CHINANAME": child.get("cInvName"),
                    "BomId": child.get("BomId"),
                    "SortSeq": child.get("SortSeq"),
                    "BaseQtyN": child.get("BaseQtyN"),
                    "BaseQtyD": child.get("BaseQtyD"),
                    "COUNTS": qty_per,
                    "CUM_QTY": child_cumulative_qty,
                    "LEVEL": level,
                    "CompScrap": child.get("CompScrap"),
                    "cInvCode": child_inv_code or None,
                    "HAS_INVENTORY": "YES" if child.get("cInvName") else "NO",
                    "iInvSprice": child.get("iInvSprice"),
                    "iInvNcost": child.get("iInvNcost"),
                    "cInvStd": child.get("cInvStd"),
                    "cInvDepCode": child.get("cInvDepCode"),
                    "cDefWareHouse": child.get("cDefWareHouse"),
                    "TOTAL_PRICE": total_price,
                }
            )

            next_visited = set(visited_part_ids)
            if child_part_id:
                next_visited.add(child_part_id)

            if child_inv_code:
                walk(
                    root_code=root_code,
                    parent_code=child_inv_code,
                    level=level + 1,
                    cumulative_qty=child_cumulative_qty,
                    visited_part_ids=next_visited,
                )

    try:
        for root_code in parent_codes:
            raise_if_cancelled(cancel_checker)
            before = len(result_rows)
            walk(
                root_code=root_code,
                parent_code=root_code,
                level=1,
                cumulative_qty=1.0,
                visited_part_ids=set(),
            )
            logger.info("U8 根节点展开完成: root_code=%s, rows=%s", root_code, len(result_rows) - before)

        return result_rows
    finally:
        close_sql_client(client)


def format_u8_output_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map U8 raw rows to the slim fields used for export/save."""

    def is_material_item(value: Any) -> bool:
        if value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        try:
            return float(text) != 0
        except Exception:
            return False

    formatted_rows: List[Dict[str, Any]] = []
    for row in rows:
        supply_type = "领料" if is_material_item(row.get("iInvNcost")) else "虚拟件"
        formatted_rows.append(
            {
                "子件层级": row.get("LEVEL"),
                "子件名称": row.get("CHINANAME"),
                "材料编码（物料编码）": row.get("cInvCode"),
                "基本用量": row.get("COUNTS"),
                "累计用量": row.get("CUM_QTY"),
                "供应类型": supply_type,
                "仓库编码": row.get("cDefWareHouse"),
                "领料部门": row.get("cInvDepCode"),
                "规格型号": row.get("cInvStd"),
                "单价": row.get("iInvNcost"),
                "总价": row.get("TOTAL_PRICE"),
                "__root_inv_code": row.get("ROOT_INV_CODE"),
                "__parent_inv_code": row.get("ParentInvCode"),
            }
        )

    return formatted_rows


