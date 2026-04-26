"""Entry points for U8 and PDM BOM queries (no FastAPI)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, ValidationError
from app.core.logging import get_logger
from app.schemas.sqlserver import PdmBomRequest, QueryResponse, U8BomInventoryRequest

from app.integrations.keyword import (
    detect_product_type,
    expand_keyword_mapping,
    normalize_pdm_keywords,
)
from app.integrations.sqlserver.client import close_sql_client, get_sql_client
from app.integrations.sqlserver.exceptions import QueryCancelledError, raise_if_cancelled
from app.integrations.sqlserver.pdm_bom import (
    deduplicate_pdm_result_rows,
    match_row_to_candidates,
    query_pdm_bom_merged,
)
from app.integrations.sqlserver.u8_bom import (
    _query_u8_bom_inventory,
    format_u8_output_rows,
    split_parent_inv_codes,
)

logger = get_logger("sqlserver")


def run_u8_bom_inventory_query(
    payload: U8BomInventoryRequest,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> QueryResponse:
    """U8 BOM + Inventory. Cooperative cancellation between root iterations."""
    parent_codes = split_parent_inv_codes(payload.parent_inv_codes)
    if not parent_codes:
        raise ValidationError("parent_inv_codes 不能为空")

    try:
        raw_rows = _query_u8_bom_inventory(
            parent_codes, payload.max_depth, cancel_checker=cancel_checker
        )
        rows = format_u8_output_rows(raw_rows)
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
    """PDM BOM_016. Cooperative cancellation between SQL calls."""
    keyword_groups = normalize_pdm_keywords(payload.keywords)
    if not keyword_groups:
        raise ValidationError(
            "keywords 不能为空，且仅支持 {type, attr} 或 [{type, attr}, ...]"
        )

    shared_client = get_sql_client(
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
            raise_if_cancelled(cancel_checker)
            product_types = detect_product_type(group) or [""]
            for product_type in product_types:
                raise_if_cancelled(cancel_checker)
                alts_per_keyword: List[List[str]] = []
                for keyword in group:
                    mapped = expand_keyword_mapping(keyword, product_type=product_type)
                    if mapped:
                        alts_per_keyword.append(mapped)
                if not alts_per_keyword:
                    continue

                executed_query_count += 1
                group_rows = query_pdm_bom_merged(alts_per_keyword, client=shared_client)
                for row in group_rows:
                    item = dict(row)
                    item["QUERY_INDEX"] = idx
                    item["QUERY_KEYWORDS"] = group
                    item["QUERY_EXPANDED_KEYWORDS"] = match_row_to_candidates(
                        row, alts_per_keyword
                    )
                    rows.append(item)

        deduplicated_rows = deduplicate_pdm_result_rows(rows)
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
        close_sql_client(shared_client)
