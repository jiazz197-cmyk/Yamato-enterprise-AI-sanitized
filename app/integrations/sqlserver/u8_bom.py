"""U8 BOM + Inventory recursive walk.

`InvCode` / PartId style codes use `.replace(\"'\", \"''\")` before embedding in N'...' SQL
literals. Parent codes are normalized from trusted API input, not ad-hoc SQL.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger

from app.integrations.sqlserver.client import close_sql_client, get_sql_client
from app.integrations.sqlserver.exceptions import raise_if_cancelled

logger = get_logger("database.sqlserver")

_DEADLOCK_RETRY_DELAYS_SEC: tuple[float, ...] = (0.3, 0.8, 1.5)


def _is_sqlserver_deadlock_error(exc: BaseException) -> bool:
    for arg in getattr(exc, "args", ()):  # pymssql usually exposes 1205 in args[0]
        if arg == 1205:
            return True
        if isinstance(arg, bytes) and b"1205" in arg:
            return True
        if isinstance(arg, str) and "1205" in arg:
            return True
    text = str(exc)
    return "1205" in text and "deadlock" in text.lower()


def _query_with_deadlock_retry(
    client: Any,
    sql: str,
    *,
    log_label: str,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    attempt = 0
    while True:
        try:
            return client.query(sql)
        except Exception as exc:
            if not _is_sqlserver_deadlock_error(exc) or attempt >= len(_DEADLOCK_RETRY_DELAYS_SEC):
                raise
            delay = _DEADLOCK_RETRY_DELAYS_SEC[attempt]
            attempt += 1
            logger.warning(
                "U8 SQLServer deadlock 1205，sleep 后重试: label=%s, attempt=%s/%s, delay=%.1fs",
                log_label,
                attempt,
                len(_DEADLOCK_RETRY_DELAYS_SEC),
                delay,
            )
            raise_if_cancelled(cancel_checker)
            time.sleep(delay)
            raise_if_cancelled(cancel_checker)


def _is_price_missing(value: Any) -> bool:
    """Return True if the price value is NULL, empty, or zero."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        return float(text) == 0
    except Exception:
        return True


def _query_recordoutlist_prices(
    client: Any,
    missing_codes: set[str],
) -> Dict[str, float]:
    """Query recordoutlist for latest iunitcost per cinvcode.

    Returns a dict mapping cinvcode -> iunitcost (latest record per code).
    Falls back to simpler ORDER BY if ddate column is unavailable.
    """
    if not missing_codes:
        return {}

    safe_codes = ", ".join(
        f"N'{code.replace(chr(39), chr(39) + chr(39))}'" for code in sorted(missing_codes)
    )

    # Try with ddate first (standard U8 date column), fallback to autoid only
    for order_by in ("ddate DESC, autoid DESC", "autoid DESC"):
        sql = f"""
            SELECT cinvcode, iunitcost
            FROM (
                SELECT
                    cinvcode,
                    iunitcost,
                    ROW_NUMBER() OVER (
                        PARTITION BY cinvcode
                        ORDER BY {order_by}
                    ) AS rn
                FROM UFDATA_CHANGE_ME.dbo.recordoutlist
                WHERE cinvcode IN ({safe_codes})
                  AND iunitcost IS NOT NULL
                  AND iunitcost <> 0
            ) t
            WHERE rn = 1
        """
        try:
            rows = _query_with_deadlock_retry(
                client,
                sql,
                log_label=f"recordoutlist_prices:{order_by}",
            )
            result: Dict[str, float] = {}
            for row in rows:
                code = str(row.get("cinvcode", "")).strip()
                cost = row.get("iunitcost")
                if code and cost is not None:
                    try:
                        result[code] = float(cost)
                    except (ValueError, TypeError):
                        pass
            return result
        except Exception as exc:
            logger.warning(
                "recordoutlist 价格补充查询失败 (ORDER BY %s): %s",
                order_by, exc,
            )
            continue

    logger.warning("recordoutlist 价格补充查询失败 (所有 ORDER BY 回退)")
    return {}


def _supplement_missing_prices(
    result_rows: List[Dict[str, Any]],
    client: Any,
) -> None:
    """Supplement missing iInvNcost from recordoutlist, in-place.

    For every row where iInvNcost is NULL/empty/0, look up the latest
    iunitcost from recordoutlist for that ChildInvCode and fill it in.
    Also recalculate TOTAL_PRICE for supplemented rows.
    """
    missing_codes: set[str] = set()
    for row in result_rows:
        if _is_price_missing(row.get("iInvNcost")):
            code = str(row.get("ChildInvCode") or "").strip()
            if code:
                missing_codes.add(code)

    if not missing_codes:
        return

    supplement_prices = _query_recordoutlist_prices(client, missing_codes)
    if not supplement_prices:
        logger.info("U8 价格补充: recordoutlist 无匹配价格, missing_codes=%s", len(missing_codes))
        return

    supplemented_count = 0
    for row in result_rows:
        if not _is_price_missing(row.get("iInvNcost")):
            continue
        code = str(row.get("ChildInvCode") or "").strip()
        fallback_price = supplement_prices.get(code)
        if fallback_price is None:
            continue

        row["iInvNcost"] = fallback_price

        cum_qty = row.get("CUM_QTY")
        if cum_qty is not None:
            try:
                row["TOTAL_PRICE"] = float(cum_qty) * fallback_price
            except (ValueError, TypeError):
                row["TOTAL_PRICE"] = None

        supplemented_count += 1

    if supplemented_count > 0:
        logger.info(
            "U8 价格补充完成: supplemented=%s/%s missing, queried_codes=%s",
            supplemented_count,
            len(missing_codes),
            len(supplement_prices),
        )


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


def _fetch_root_inv_names(client: SqlServerClient, codes: List[str]) -> Dict[str, str]:
    """批量查询根父件编码对应的名称"""
    if not codes:
        return {}

    # 构建 IN 条件
    code_list = ", ".join(f"N'{code.replace(chr(39), chr(39)+chr(39))}'" for code in codes)
    sql = f"""
        SELECT cInvCode, cInvName
        FROM Inventory
        WHERE cInvCode IN ({code_list})
    """
    rows = _query_with_deadlock_retry(
        client,
        sql,
        log_label="root_inv_names",
    )

    result: Dict[str, str] = {}
    for row in rows:
        code = str(row.get("cInvCode") or "").strip()
        name = str(row.get("cInvName") or "").strip()
        if code and name:
            result[code] = name

    # 找不到名称的编码，使用编码本身作为名称
    for code in codes:
        if code not in result:
            result[code] = code

    return result


def _fill_inventory_only_rows(
    result_rows: List[Dict[str, Any]],
    client: Any,
    no_bom_codes: List[str],
    root_name_map: Dict[str, str],
) -> None:
    """For codes without BOM children (purchased/leaf items), query Inventory
    directly and append a single self-referencing row per code.

    This handles items like 铭牌 (108xxx), 标准件 (104xxx), etc. that are
    purchased parts with no BOM structure — they only exist in Inventory.
    """
    if not no_bom_codes:
        return

    safe_codes = ", ".join(
        f"N'{code.replace(chr(39), chr(39) + chr(39))}'" for code in no_bom_codes
    )
    sql = f"""
        SELECT
            cInvCode,
            cInvName,
            iInvSprice,
            iInvNcost,
            cInvStd,
            cInvDepCode,
            cDefWareHouse,
            bForeExpland,
            iSupplyType
        FROM Inventory
        WHERE cInvCode IN ({safe_codes})
    """
    try:
        inv_rows = _query_with_deadlock_retry(
            client,
            sql,
            log_label="inventory_only_rows",
        )
    except Exception as exc:
        logger.warning("Inventory 采购件回退查询失败: %s", exc)
        return

    # Map code -> inventory row
    inv_by_code: Dict[str, Dict[str, Any]] = {}
    for row in inv_rows:
        code = str(row.get("cInvCode") or "").strip()
        if code:
            inv_by_code[code] = row

    filled_count = 0
    for code in no_bom_codes:
        inv = inv_by_code.get(code)
        if not inv:
            logger.info("U8 采购件回退: 编码 %s 在 Inventory 中无记录", code)
            continue

        inv_cost = inv.get("iInvNcost")
        inv_cost_num = to_float_local(inv_cost, 0.0) if inv_cost is not None else None
        total_price = inv_cost_num if inv_cost_num is not None else None

        result_rows.append(
            {
                "ROOT_INV_CODE": code,
                "ROOT_INV_NAME": root_name_map.get(code, code),
                "ParentInvCode": code,
                "ChildInvCode": code,
                "CHINANAME": inv.get("cInvName"),
                "BomId": None,
                "SortSeq": 1,
                "BaseQtyN": 1,
                "BaseQtyD": 1,
                "COUNTS": 1.0,
                "CUM_QTY": 1.0,
                "LEVEL": 1,
                "CompScrap": None,
                "cInvCode": code,
                "HAS_INVENTORY": "YES",
                "iInvSprice": inv.get("iInvSprice"),
                "iInvNcost": inv.get("iInvNcost"),
                "cInvStd": inv.get("cInvStd"),
                "cInvDepCode": inv.get("cInvDepCode"),
                "cDefWareHouse": inv.get("cDefWareHouse"),
                "bForeExpland": inv.get("bForeExpland"),
                "iSupplyType": inv.get("iSupplyType"),
                "TOTAL_PRICE": total_price,
            }
        )
        filled_count += 1

    if filled_count > 0:
        logger.info(
            "U8 采购件回退完成: filled=%s/%s codes",
            filled_count,
            len(no_bom_codes),
        )


def to_float_local(value: Any, default: float = 0.0) -> float:
    """Local to_float for use outside _query_u8_bom_inventory closure."""
    try:
        return float(value)
    except Exception:
        return default


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
            rows = _query_with_deadlock_retry(
                client,
                probe_sql,
                log_label=f"partmap_probe:{code}",
                cancel_checker=cancel_checker,
            )
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
                    ic.bForeExpland,
                    ic.iSupplyType,
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
                cInvName, iInvSprice, iInvNcost, cInvStd, cInvDepCode, cDefWareHouse, bForeExpland, iSupplyType, ChildPartId
            FROM RawData
            WHERE rn = 1
            ORDER BY SortSeq, ChildInvCode
        """
        rows = _query_with_deadlock_retry(
            client,
            sql,
            log_label=f"fetch_children:{parent_inv_code}",
            cancel_checker=cancel_checker,
        )
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
        root_name: str,
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
                    "ROOT_INV_NAME": root_name,
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
                    "bForeExpland": child.get("bForeExpland"),
                    "iSupplyType": child.get("iSupplyType"),
                    "TOTAL_PRICE": total_price,
                }
            )

            next_visited = set(visited_part_ids)
            if child_part_id:
                next_visited.add(child_part_id)

            # 4/7 开头的编码不再继续向下展开
            if child_inv_code and child_inv_code.startswith(("4", "7")):
                continue

            if child_inv_code:
                walk(
                    root_code=root_code,
                    root_name=root_name,
                    parent_code=child_inv_code,
                    level=level + 1,
                    cumulative_qty=child_cumulative_qty,
                    visited_part_ids=next_visited,
                )

    try:
        # 批量查询所有根父件的名称
        root_name_map = _fetch_root_inv_names(client, parent_codes)

        # Collect root codes that have no BOM children (purchased/leaf items)
        no_bom_root_codes: List[str] = []

        for root_code in parent_codes:
            raise_if_cancelled(cancel_checker)
            before = len(result_rows)
            walk(
                root_code=root_code,
                root_name=root_name_map.get(root_code, root_code),
                parent_code=root_code,
                level=1,
                cumulative_qty=1.0,
                visited_part_ids=set(),
            )
            rows_added = len(result_rows) - before
            if rows_added == 0:
                no_bom_root_codes.append(root_code)
            logger.info("U8 根节点展开完成: root_code=%s, rows=%s", root_code, rows_added)

        # For root codes without BOM children, query Inventory directly
        _fill_inventory_only_rows(
            result_rows, client, no_bom_root_codes, root_name_map
        )

        # Supplement missing prices from recordoutlist
        _supplement_missing_prices(result_rows, client)

        return result_rows
    finally:
        close_sql_client(client)


_SUPPLY_TYPE_MAP: Dict[int, str] = {
    0: "领用",
    1: "入库倒冲",
    2: "工序倒冲",
    3: "虚拟件",
    4: "直接供应",
}


def _determine_supply_type(row: Dict[str, Any]) -> str:
    """Determine supply type from iSupplyType, falling back to bForeExpland,
    then to iInvNcost-based heuristic.

    Priority:
    1. Inventory.iSupplyType (from U8 AA_Enum: 0=领用, 1=入库倒冲, 2=工序倒冲, 3=虚拟件, 4=直接供应)
    2. Inventory.bForeExpland (1=虚拟件)
    3. iInvNcost heuristic (non-zero → 领用, else → 虚拟件)
    """
    # 1. Try iSupplyType
    iSupplyType = row.get("iSupplyType")
    if iSupplyType is not None:
        try:
            return _SUPPLY_TYPE_MAP[int(iSupplyType)]
        except (ValueError, TypeError, KeyError):
            pass

    # 2. Try bForeExpland
    bForeExpland = row.get("bForeExpland")
    if bForeExpland is not None:
        try:
            return "虚拟件" if int(bForeExpland) == 1 else "领用"
        except (ValueError, TypeError):
            pass

    # 3. Fallback to cost-based heuristic
    return "领用" if _is_material_item_by_cost(row.get("iInvNcost")) else "虚拟件"


def format_u8_output_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map U8 raw rows to the slim fields used for export/save."""

    formatted_rows: List[Dict[str, Any]] = []
    for row in rows:
        supply_type = _determine_supply_type(row)
        formatted_rows.append(
            {
                "子件层级": row.get("LEVEL"),
                "子件名称": row.get("CHINANAME"),
                "根父件名称": row.get("ROOT_INV_NAME"),
                "材料编码（物料编码）": row.get("cInvCode"),
                "累计用量": row.get("CUM_QTY"),
                "供应类型": supply_type,
                "规格型号": row.get("cInvStd"),
                "单价": row.get("iInvNcost"),
                "总价": row.get("TOTAL_PRICE"),
                "__root_inv_code": row.get("ROOT_INV_CODE"),
                "__root_inv_name": row.get("ROOT_INV_NAME"),
                "__parent_inv_code": row.get("ParentInvCode"),
            }
        )

    return formatted_rows


def _is_material_item_by_cost(value: Any) -> bool:
    """Fallback check: item with a non-zero cost price is a real material item."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        return float(text) != 0
    except Exception:
        return False


