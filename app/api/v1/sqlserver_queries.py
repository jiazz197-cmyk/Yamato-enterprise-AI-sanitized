"""
SQL Server query routes. Core logic: app.integrations.sqlserver, models: app.schemas.sqlserver.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.integrations.sqlserver import run_pdm_bom_query, run_u8_bom_inventory_query
from app.models.orm.platform.user import User
from app.schemas.sqlserver import PdmBomRequest, QueryResponse, U8BomInventoryRequest

router = APIRouter()


@router.post("/u8/bom-inventory", response_model=QueryResponse, summary="U8 BOM + Inventory 递归查询")
def query_u8_bom_inventory(
    payload: U8BomInventoryRequest,
    _current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """按 parent_inv_codes 递归展开 U8 BOM，并关联 Inventory 成本信息。需登录。"""
    return run_u8_bom_inventory_query(payload)


@router.post("/pdm/bom", response_model=QueryResponse, summary="PDM BOM_016 条件查询")
def query_pdm_bom(
    payload: PdmBomRequest,
    _current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """查询 pdm_change_me.BOM_016，支持单组关键词 AND 或多组关键词分批查询。需登录。"""
    return run_pdm_bom_query(payload)
