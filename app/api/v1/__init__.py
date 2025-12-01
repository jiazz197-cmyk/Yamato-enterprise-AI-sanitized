"""
API v1 路由模块
"""
from fastapi import APIRouter

from app.api.v1 import example

api_router = APIRouter()

# 注册子路由
api_router.include_router(example.router, prefix="/example", tags=["示例"])
