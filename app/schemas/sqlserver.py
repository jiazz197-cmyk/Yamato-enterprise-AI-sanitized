"""Pydantic models for U8/PDM SQLServer query API (shared by API routes and quotation pipeline)."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class U8BomInventoryRequest(BaseModel):
    """U8 BOM + Inventory query request."""

    parent_inv_codes: str | List[str] = Field(
        ...,
        description="父件编码，支持字符串（逗号/空格分隔）或数组",
    )
    max_depth: int = Field(3, ge=1, le=50, description="递归最大深度")


class PdmBomRequest(BaseModel):
    """PDM BOM_016 query request."""

    keywords: Any = Field(
        ...,
        description=(
            "仅支持两种结构化格式: 单个对象({type, attr})、"
            "对象列表(List[{type, attr}])"
        ),
    )


class QueryResponse(BaseModel):
    """Generic query response."""

    total: int
    items: List[Dict[str, Any]]
