"""
SQL Server 查询路由
整合 query_u8_sql.py 与 query_pdm_sql.py 的核心能力。
"""
from __future__ import annotations

from itertools import product
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, ValidationError
from app.core.logging import get_logger
from app.api.v1.keyword_mapping import detect_product_type, expand_keyword_mapping
from app.api.v1.keyword_normalizer import normalize_pdm_keywords

router = APIRouter()
logger = get_logger("sqlserver_queries")


class QueryCancelledError(RuntimeError):
    """Raised when a SQL query loop is aborted via cancel_checker."""


def _raise_if_cancelled(cancel_checker: Optional[Callable[[], bool]]) -> None:
    if cancel_checker is not None and cancel_checker():
        raise QueryCancelledError("cancelled")


class U8BomInventoryRequest(BaseModel):
    """U8 BOM + Inventory 查询请求。"""

    parent_inv_codes: str | List[str] = Field(
        ...,
        description="父件编码，支持字符串（逗号/空格分隔）或数组",
    )
    max_depth: int = Field(20, ge=1, le=50, description="递归最大深度")


class PdmBomRequest(BaseModel):
    """PDM BOM_016 查询请求。"""

    keywords: Any = Field(
        ...,
        description=(
            "仅支持两种结构化格式: 单个对象({type, attr})、"
            "对象列表(List[{type, attr}])"
        ),
    )


class QueryResponse(BaseModel):
    """通用查询响应。"""

    total: int
    items: List[Dict[str, Any]]


def _split_codes(value: Any) -> List[str]:
    """规范化 parent_inv_codes 输入。"""
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

    # 按输入顺序去重
    return list(dict.fromkeys(codes))


def _build_pdm_where_clauses(condition: str | List[str]) -> List[str]:
    clauses: List[str] = []

    if isinstance(condition, str):
        text = condition.strip()
        if text:
            negated = text.startswith("!")
            payload = text[1:].strip() if negated else text
            if payload:
                safe_text = payload.replace("'", "''")
                if negated:
                    clauses.append(f"CHINANAME NOT LIKE '%{safe_text}%'")
                else:
                    clauses.append(f"CHINANAME LIKE '%{safe_text}%'")
        return clauses

    for item in condition:
        text = str(item).strip()
        if not text:
            continue
        negated = text.startswith("!")
        payload = text[1:].strip() if negated else text
        if not payload:
            continue
        safe_text = payload.replace("'", "''")
        if negated:
            clauses.append(f"CHINANAME NOT LIKE '%{safe_text}%'")
        else:
            clauses.append(f"CHINANAME LIKE '%{safe_text}%'")

    return clauses


def _deduplicate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 (CHINANAME, PARTID) 去重，保留首条。"""
    unique_rows: List[Dict[str, Any]] = []
    seen = set()

    for row in rows:
        chinaname = str(row.get("CHINANAME") or "").strip()
        partid = str(row.get("PARTID") or "").strip()
        key = (chinaname, partid)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    return unique_rows


def _deduplicate_pdm_result_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    汇总多次 PDM 查询结果，并按 (CHINANAME, PARTID) 去重。
    保留首条命中的 QUERY_INDEX/QUERY_KEYWORDS/QUERY_EXPANDED_KEYWORDS。
    """
    return _deduplicate_rows(rows)


def _get_sql_client(config: Dict[str, Any]):
    """优先使用 sqlserver_tools，退化到 pymssql。"""
    try:
        from sqlserver_tools import ConnectionConfig, SqlServerClient  # type: ignore

        return SqlServerClient(ConnectionConfig(**config))
    except ImportError:
        pass

    try:
        import pymssql  # type: ignore
    except ImportError as exc:
        raise ExternalServiceError(
            "SQLServer",
            "缺少依赖，请安装 sqlserver_tools 或 pymssql",
        ) from exc

    class _PymssqlClient:
        """Reuses a single pymssql connection across queries to avoid repeated
        TCP/TLS/auth handshakes (each handshake costs multiple seconds)."""

        def __init__(self, conf: Dict[str, Any]):
            self.conf = conf
            self._conn: Any = None

        def _ensure_conn(self) -> Any:
            if self._conn is None:
                self._conn = pymssql.connect(
                    server=self.conf["server"],
                    port=self.conf.get("port", 1433),
                    user=self.conf["username"],
                    password=self.conf["password"],
                    database=self.conf["database"],
                    charset="utf8",
                    as_dict=True,
                )
            return self._conn

        def query(self, sql: str) -> List[Dict[str, Any]]:
            try:
                conn = self._ensure_conn()
                with conn.cursor(as_dict=True) as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                return [dict(row) for row in rows]
            except Exception:
                self.close()
                raise

        def close(self) -> None:
            conn = self._conn
            self._conn = None
            if conn is None:
                return
            try:
                conn.close()
            except Exception:
                pass

        def __enter__(self) -> "_PymssqlClient":
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            self.close()

    return _PymssqlClient(config)


def _close_sql_client(client: Any) -> None:
    """Best-effort close for any sql client shape (pymssql wrapper or sqlserver_tools)."""
    if client is None:
        return
    closer = getattr(client, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass


def test_sqlserver_connectivity() -> Dict[str, Dict[str, Any]]:
    """
    Test U8/PDM SQLServer connectivity with `SELECT 1`.

    Returns:
        {
            "u8": {"ok": bool, "latency_ms": float | None, "error": str | None},
            "pdm": {"ok": bool, "latency_ms": float | None, "error": str | None},
        }
    """

    checks = {
        "u8": {
            "backend": "pymssql",
            "server": settings.U8_SQLSERVER_HOST,
            "port": settings.U8_SQLSERVER_PORT,
            "database": settings.U8_SQLSERVER_DATABASE,
            "username": settings.U8_SQLSERVER_USER,
            "password": settings.U8_SQLSERVER_PASSWORD,
            "encrypt": settings.U8_SQLSERVER_ENCRYPT,
        },
        "pdm": {
            "backend": "pymssql",
            "server": settings.PDM_SQLSERVER_HOST,
            "port": settings.PDM_SQLSERVER_PORT,
            "database": settings.PDM_SQLSERVER_DATABASE,
            "username": settings.PDM_SQLSERVER_USER,
            "password": settings.PDM_SQLSERVER_PASSWORD,
            "encrypt": settings.PDM_SQLSERVER_ENCRYPT,
        },
    }

    results: Dict[str, Dict[str, Any]] = {}
    for name, conf in checks.items():
        start = perf_counter()
        try:
            client = _get_sql_client(conf)
            client.query("SELECT 1 AS ok")
            latency_ms = (perf_counter() - start) * 1000
            results[name] = {
                "ok": True,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }
        except Exception as exc:
            results[name] = {
                "ok": False,
                "latency_ms": None,
                "error": str(exc),
            }

    return results


def _query_u8_bom_inventory(
    parent_codes: List[str],
    max_depth: int,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    if not parent_codes:
        return []

    client = _get_sql_client(
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

    def to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def fetch_children(parent_inv_code: str) -> List[Dict[str, Any]]:
        if parent_inv_code in children_cache:
            return children_cache[parent_inv_code]

        _raise_if_cancelled(cancel_checker)
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
            )
            SELECT
                parent.PartInvCode AS ParentInvCode,
                child.PartInvCode AS ChildInvCode,
                oc.BomId,
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
                child.PartId AS ChildPartId
            FROM PartMap parent
            JOIN bom_parent bp ON bp.ParentId = parent.PartId
            JOIN bom_opcomponent oc ON oc.BomId = bp.BomId
            JOIN bom_bom b ON b.BomId = bp.BomId AND b.Status = 3
            JOIN PartMap child ON child.PartId = oc.ComponentId
            LEFT JOIN Inventory ic ON ic.cInvCode = child.PartInvCode
            WHERE parent.PartInvCode = N'{safe_code}'
            ORDER BY oc.SortSeq, child.PartInvCode
        """
        rows = client.query(sql)
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

    for root_code in parent_codes:
        _raise_if_cancelled(cancel_checker)
        walk(
            root_code=root_code,
            parent_code=root_code,
            level=1,
            cumulative_qty=1.0,
            visited_part_ids=set(),
        )

    return result_rows


def _format_u8_output_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 U8 原始结果转换为保存文件使用的精简字段。"""

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
                "供应类型": supply_type,
                "仓库编码": row.get("cDefWareHouse"),
                "领料部门": row.get("cInvDepCode"),
                "规格型号": row.get("cInvStd"),
                "单价": row.get("iInvNcost"),
                "总价": row.get("TOTAL_PRICE"),
            }
        )

    return formatted_rows


def _query_pdm_bom(
    condition: str | List[str],
    client: Any = None,
) -> List[Dict[str, Any]]:
    where_clauses = _build_pdm_where_clauses(condition)
    if not where_clauses:
        return []

    and_conditions = "\n            AND ".join(where_clauses)

    if client is None:
        client = _get_sql_client(
            {
                "backend": "pymssql",
                "server": settings.PDM_SQLSERVER_HOST,
                "port": settings.PDM_SQLSERVER_PORT,
                "database": settings.PDM_SQLSERVER_DATABASE,
                "username": settings.PDM_SQLSERVER_USER,
                "password": settings.PDM_SQLSERVER_PASSWORD,
                "encrypt": settings.PDM_SQLSERVER_ENCRYPT,
            }
        )

    query_sql = f"""
        SELECT DISTINCT
            CHINANAME,
            PARTID
        FROM BOM_016
        WHERE
            SEQNUM LIKE '1.[0-9]%'
            AND SEQNUM NOT LIKE '1.[0-9]%.%'
            AND {and_conditions}
        ORDER BY CHINANAME, PARTID
    """

    rows = client.query(query_sql)
    return _deduplicate_rows(rows)


def _normalize_pdm_keywords(value: Any) -> List[List[str]]:
    """兼容旧调用入口，真实实现已迁移至 keyword_normalizer 模块。"""
    return normalize_pdm_keywords(value)


def _expand_pdm_keyword_group(group: List[str]) -> List[List[str]]:
    """
    将一组原始关键词展开为多组可执行查询关键词。

    例如:
    ["供料漏斗", "flat"] -> [["供料漏斗", "平"], ["供料漏斗", "平板"]]

    当检测到多个产品类型时，对每个产品类型分别做映射展开，然后合并去重。
    例如:
    ["溜槽部", "flat"] ->
        产品类型=["溜槽", "溜槽部"]，flat映射=["平", "平板"]
        -> [["溜槽", "平"], ["溜槽", "平板"], ["溜槽部", "平"], ["溜槽部", "平板"]]
    """
    if not group:
        return []

    product_types = detect_product_type(group)

    # 如果没有检测到产品类型，使用空字符串作为默认值
    if not product_types:
        product_types = [""]

    expanded_groups: List[List[str]] = []
    seen_groups: set = set()

    for product_type in product_types:
        # 对每个产品类型分别做关键词映射展开
        expanded_candidates = []
        for keyword in group:
            mapped_candidates = expand_keyword_mapping(keyword, product_type=product_type)
            # 当规则明确要求“不作为参数加入”时，映射函数会返回空列表，这里用空占位跳过该关键词。
            expanded_candidates.append(mapped_candidates if mapped_candidates else [""])

        for combination in product(*expanded_candidates):
            query_group = [str(item).strip() for item in combination if str(item).strip()]
            # 使用 tuple 去重
            group_key = tuple(query_group)
            if query_group and group_key not in seen_groups:
                seen_groups.add(group_key)
                expanded_groups.append(query_group)

    return expanded_groups


def run_u8_bom_inventory_query(
    payload: U8BomInventoryRequest,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> QueryResponse:
    """Core U8 BOM + Inventory query. Supports cooperative cancellation."""
    parent_codes = _split_codes(payload.parent_inv_codes)
    if not parent_codes:
        raise ValidationError("parent_inv_codes 不能为空")

    try:
        raw_rows = _query_u8_bom_inventory(
            parent_codes, payload.max_depth, cancel_checker=cancel_checker
        )
        rows = _format_u8_output_rows(raw_rows)
        logger.info(
            "U8 查询完成: parent_inv_codes=%s, raw_rows=%s, output_rows=%s",
            parent_codes,
            len(raw_rows),
            len(rows),
        )
        return QueryResponse(total=len(rows), items=rows)
    except (ValidationError, QueryCancelledError):
        raise
    except Exception as exc:
        logger.error("U8 查询失败: %s", exc, exc_info=True)
        raise ExternalServiceError("U8 SQLServer", f"查询失败: {exc}") from exc


def run_pdm_bom_query(
    payload: PdmBomRequest,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> QueryResponse:
    """Core PDM BOM_016 query. Supports cooperative cancellation between SQL calls."""
    keyword_groups = normalize_pdm_keywords(payload.keywords)
    if not keyword_groups:
        raise ValidationError(
            "keywords 不能为空，且仅支持 {type, attr} 或 [{type, attr}, ...]"
        )

    shared_client = _get_sql_client(
        {
            "backend": "pymssql",
            "server": settings.PDM_SQLSERVER_HOST,
            "port": settings.PDM_SQLSERVER_PORT,
            "database": settings.PDM_SQLSERVER_DATABASE,
            "username": settings.PDM_SQLSERVER_USER,
            "password": settings.PDM_SQLSERVER_PASSWORD,
            "encrypt": settings.PDM_SQLSERVER_ENCRYPT,
        }
    )

    try:
        rows: List[Dict[str, Any]] = []
        executed_query_count = 0

        for idx, group in enumerate(keyword_groups, start=1):
            _raise_if_cancelled(cancel_checker)
            expanded_groups = _expand_pdm_keyword_group(group)
            for expanded_group in expanded_groups:
                _raise_if_cancelled(cancel_checker)
                executed_query_count += 1
                group_rows = _query_pdm_bom(expanded_group, client=shared_client)
                for row in group_rows:
                    item = dict(row)
                    item["QUERY_INDEX"] = idx
                    item["QUERY_KEYWORDS"] = group
                    item["QUERY_EXPANDED_KEYWORDS"] = expanded_group
                    rows.append(item)

        deduplicated_rows = _deduplicate_pdm_result_rows(rows)
        logger.info(
            "PDM 查询完成: input_groups=%s, executed_queries=%s, rows=%s, deduplicated_rows=%s",
            len(keyword_groups),
            executed_query_count,
            len(rows),
            len(deduplicated_rows),
        )
        return QueryResponse(total=len(deduplicated_rows), items=deduplicated_rows)
    except (ValidationError, QueryCancelledError):
        raise
    except Exception as exc:
        logger.error("PDM 查询失败: %s", exc, exc_info=True)
        raise ExternalServiceError("PDM SQLServer", f"查询失败: {exc}") from exc
    finally:
        _close_sql_client(shared_client)


@router.post("/u8/bom-inventory", response_model=QueryResponse, summary="U8 BOM + Inventory 递归查询")
def query_u8_bom_inventory(payload: U8BomInventoryRequest) -> QueryResponse:
    """按 parent_inv_codes 递归展开 U8 BOM，并关联 Inventory 成本信息。"""
    return run_u8_bom_inventory_query(payload)


@router.post("/pdm/bom", response_model=QueryResponse, summary="PDM BOM_016 条件查询")
def query_pdm_bom(payload: PdmBomRequest) -> QueryResponse:
    """查询 pdm_change_me.BOM_016，支持单组关键词 AND 或多组关键词分批查询。"""
    return run_pdm_bom_query(payload)
