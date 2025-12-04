"""
API v1 Router Module
Aggregates all v1 API endpoints
"""
from fastapi import APIRouter

from app.api.v1 import example, file_manager, document_processing
from app.api.v1.endpoints import image2url

api_router = APIRouter()

# Register sub-routers
api_router.include_router(example.router, prefix="/example", tags=["Example"])
api_router.include_router(file_manager.router, prefix="/files", tags=["File Management"])
api_router.include_router(document_processing.router, prefix="/docs", tags=["Document Processing"])
api_router.include_router(image2url.router, prefix="/image2url", tags=["Image Processing"])
