"""
API v1 路由模块
"""
from fastapi import APIRouter

from app.api.v1 import example, file_manager, document_processing

api_router = APIRouter()

# 注册子路由
api_router.include_router(example.router, prefix="/example", tags=["示例"])
api_router.include_router(file_manager.router, prefix="/files", tags=["文件管理"])
api_router.include_router(document_processing.router, prefix="/docs", tags=["文档处理"])
