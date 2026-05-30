"""
SQL Server query routes.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import APIRouter, Depends

from app.adapters.sqlserver_queries import PdmBomQueryAdapter, U8BomInventoryQueryAdapter
from app.core.config import settings
from app.core.security import get_current_user_detached
from app.models.orm.platform.user import User
from app.schemas.sqlserver import PdmBomRequest, QueryResponse, U8BomInventoryRequest
from app.usecases.sqlserver_queries.run_queries import RunPdmBomQueryUseCase, RunU8BomInventoryQueryUseCase

router = APIRouter()

_u8 = U8BomInventoryQueryAdapter()
_pdm = PdmBomQueryAdapter()
_sqlserver_query_executor = ThreadPoolExecutor(
    max_workers=settings.SQLSERVER_QUERY_MAX_WORKERS,
    thread_name_prefix="sqlserver_query_",
)


async def _run_sqlserver_query(func, *args) -> QueryResponse:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_sqlserver_query_executor, partial(func, *args))


@router.post("/u8/bom-inventory", response_model=QueryResponse, summary="U8 BOM + Inventory 递归查询")
async def query_u8_bom_inventory(
    payload: U8BomInventoryRequest,
    _current_user: User = Depends(get_current_user_detached),
) -> QueryResponse:
    """按 parent_inv_codes 递归展开 U8 BOM，并关联 Inventory 成本信息。需登录。"""
    return await _run_sqlserver_query(RunU8BomInventoryQueryUseCase(_u8).execute, payload)


@router.post("/pdm/bom", response_model=QueryResponse, summary="PDM BOM_016 条件查询")
async def query_pdm_bom(
    payload: PdmBomRequest,
    _current_user: User = Depends(get_current_user_detached),
) -> QueryResponse:
    """查询 pdm_change_me.BOM_016，支持单组关键词 AND 或多组关键词分批查询。需登录。"""
    return await _run_sqlserver_query(RunPdmBomQueryUseCase(_pdm).execute, payload)
