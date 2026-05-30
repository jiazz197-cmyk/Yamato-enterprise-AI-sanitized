"""PDM BOM_027 query helpers.

Text fragments embedded in CHINANAME LIKE/NOT LIKE use single-quote doubling for SQL
Server string literals; user % / _ in keywords still act as wildcard metacharacters
in LIKE (semantic breadth, not classic injection). Tighten at API layer if needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

from app.integrations.sqlserver.client import get_sql_client

logger = get_logger("database.sqlserver.pdm_bom")

# 默认排除的关键词（停用、禁用等）
_DEFAULT_EXCLUDE_KEYWORDS = ["停用", "暂停使用", "禁用", "作废", "废弃"]


def build_pdm_exclude_clauses() -> List[str]:
    """Build default exclude clauses for CHINANAME."""
    clauses: List[str] = []
    for exclude_kw in _DEFAULT_EXCLUDE_KEYWORDS:
        safe_kw = exclude_kw.replace("'", "''")
        clauses.append(f"a.CHINANAME NOT LIKE '%{safe_kw}%'")
    return clauses


def build_model_filter_clauses(model: Optional[str] = None) -> List[str]:
    """Build MODEL filter clauses with exact match logic.

    - a.MODEL LIKE '%{model}%' - 包含 model
    - a.MODEL NOT LIKE '%{model}[a-zA-Z]%' - 排除 model 后面紧跟字母的情况

    Args:
        model: 机型型号，如 "ADW-A-0314S"

    Returns:
        List of SQL clauses for MODEL filtering
    """
    if not model:
        return []

    safe_model = model.replace("'", "''")
    clauses: List[str] = []
    clauses.append(f"a.MODEL LIKE '%{safe_model}%'")
    clauses.append(f"a.MODEL NOT LIKE '%{safe_model}[a-zA-Z]%'")
    return clauses


def build_pdm_where_clauses(condition: str | List[str]) -> List[str]:
    """Build LIKE clauses; strings are SQL-quoted via `.replace("'", "''")` only."""
    clauses: List[str] = build_pdm_exclude_clauses()

    if isinstance(condition, str):
        text = condition.strip()
        if text:
            negated = text.startswith("!")
            payload = text[1:].strip() if negated else text
            if payload:
                safe_text = payload.replace("'", "''")
                if negated:
                    clauses.append(f"a.CHINANAME NOT LIKE '%{safe_text}%'")
                else:
                    clauses.append(f"a.CHINANAME LIKE '%{safe_text}%'")
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
            clauses.append(f"a.CHINANAME NOT LIKE '%{safe_text}%'")
        else:
            clauses.append(f"a.CHINANAME LIKE '%{safe_text}%'")

    return clauses


def deduplicate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by (CHINANAME, PARTID), keep first."""
    unique_rows: List[Dict[str, Any]] = []
    seen: set = set()

    for row in rows:
        chinaname = str(row.get("CHINANAME") or "").strip()
        partid = str(row.get("PARTID") or "").strip()
        key = (chinaname, partid)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    return unique_rows


def deduplicate_pdm_result_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate merged PDM query results."""
    return deduplicate_rows(rows)


def _pdm_client_config() -> dict:
    return {
        "backend": "pymssql",
        "server": settings.PDM_SQLSERVER_HOST,
        "port": settings.PDM_SQLSERVER_PORT,
        "database": settings.PDM_SQLSERVER_DATABASE,
        "username": settings.PDM_SQLSERVER_USER,
        "password": settings.PDM_SQLSERVER_PASSWORD,
        "encrypt": settings.PDM_SQLSERVER_ENCRYPT,
    }


def build_pdm_and_where_clause(
    alternatives_per_keyword: List[List[str]],
    model: Optional[str] = None,
) -> str:
    """Merged WHERE fragment: OR positive-only candidates, AND if any candidate is negated.

    Args:
        alternatives_per_keyword: 关键词列表，每组内的关键词用 OR 连接
        model: 机型型号，用于精确匹配 MODEL 字段
    """
    # 先添加默认排除条件
    outer_parts: List[str] = build_pdm_exclude_clauses()

    # 添加 MODEL 过滤条件
    model_clauses = build_model_filter_clauses(model)
    outer_parts.extend(model_clauses)

    for alts in alternatives_per_keyword:
        inner: List[str] = []
        has_negated = False
        seen_inner: set = set()
        for candidate in alts:
            text = str(candidate).strip()
            if not text:
                continue
            negated = text.startswith("!")
            has_negated = has_negated or negated
            payload = text[1:].strip() if negated else text
            if not payload:
                continue
            safe_text = payload.replace("'", "''")
            clause = (
                f"a.CHINANAME NOT LIKE '%{safe_text}%'"
                if negated
                else f"a.CHINANAME LIKE '%{safe_text}%'"
            )
            if clause in seen_inner:
                continue
            seen_inner.add(clause)
            inner.append(clause)
        if not inner:
            continue
        if len(inner) == 1:
            outer_parts.append(inner[0])
        elif has_negated:
            outer_parts.append("(" + " AND ".join(inner) + ")")
        else:
            outer_parts.append("(" + " AND ".join(inner) + ")")
    return "\n            AND ".join(outer_parts)


def build_pdm_or_where_clause(alternatives_per_keyword: List[List[str]]) -> str:
    """Backward-compatible wrapper for merged PDM WHERE construction."""
    return build_pdm_and_where_clause(alternatives_per_keyword)


def query_pdm_bom_merged(
    alternatives_per_keyword: List[List[str]],
    model: Optional[str] = None,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Query BOM_027 with keywords and optional model filter.

    Args:
        alternatives_per_keyword: 关键词列表
        model: 机型型号，如 "ADW-A-0314S"
        client: SQL client

    Returns:
        Deduplicated list of rows with PARTID and CHINANAME
    """
    and_conditions = build_pdm_and_where_clause(alternatives_per_keyword, model=model)
    if not and_conditions:
        return []

    if client is None:
        client = get_sql_client(_pdm_client_config())

    query_sql = f"""
        SELECT DISTINCT
            a.PARTID AS PARTID,
            a.CHINANAME AS CHINANAME
        FROM BOM_027 a
        WHERE a.PARTVAR = (
            SELECT MAX(b.PARTVAR) FROM BOM_027 b WHERE b.PARTID = a.PARTID
        )
        AND {and_conditions}
        ORDER BY a.PARTID
    """

    logger.debug("PDM BOM_027 merged SQL:\n%s", query_sql)
    rows = client.query(query_sql)
    return deduplicate_rows(rows)


def match_row_to_candidates(
    row: Dict[str, Any],
    alternatives_per_keyword: List[List[str]],
) -> List[str]:
    chinaname = str(row.get("CHINANAME") or "")
    result: List[str] = []
    for alts in alternatives_per_keyword:
        hits: List[str] = []
        has_negated = False
        for candidate in alts:
            text = str(candidate).strip()
            if not text:
                continue
            negated = text.startswith("!")
            has_negated = has_negated or negated
            payload = text[1:].strip() if negated else text
            if not payload:
                continue
            matched = (payload not in chinaname) if negated else (payload in chinaname)
            if matched:
                hits.append(text)
        result.append(" AND ".join(hits) if has_negated else (hits[0] if hits else ""))
    return result


def query_pdm_bom(
    condition: str | List[str],
    model: Optional[str] = None,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Query BOM_027 with condition and optional model filter.

    Args:
        condition: 单个关键词或关键词列表
        model: 机型型号，如 "ADW-A-0314S"
        client: SQL client

    Returns:
        Deduplicated list of rows with PARTID and CHINANAME
    """
    where_clauses = build_pdm_where_clauses(condition)

    # 添加 MODEL 过滤条件
    model_clauses = build_model_filter_clauses(model)
    where_clauses.extend(model_clauses)

    if not where_clauses:
        return []

    and_conditions = "\n            AND ".join(where_clauses)

    if client is None:
        client = get_sql_client(_pdm_client_config())

    query_sql = f"""
        SELECT DISTINCT
            a.PARTID AS PARTID,
            a.CHINANAME AS CHINANAME
        FROM BOM_027 a
        WHERE a.PARTVAR = (
            SELECT MAX(b.PARTVAR) FROM BOM_027 b WHERE b.PARTID = a.PARTID
        )
        AND {and_conditions}
        ORDER BY a.PARTID
    """

    logger.debug("PDM BOM_027 SQL:\n%s", query_sql)
    rows = client.query(query_sql)
    return deduplicate_rows(rows)