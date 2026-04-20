"""
API v1 Router Module
Aggregates all v1 API endpoints
"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    document_processing,
    example,
    file_manager,
    quotation_generation,
    sqlserver_queries,
    websocket_notifier,
)
from app.api.v1.endpoints import (
    image2url,
    retriever,
    pdf2image,
    chat_summary,
    closing_form,
    context_compression,
)

api_router = APIRouter()

# Register sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(example.router, prefix="/example", tags=["Example"])
api_router.include_router(
    file_manager.router, prefix="/files", tags=["File Management"]
)
api_router.include_router(
    quotation_generation.router, prefix="/quotation", tags=["Quotation Generation"]
)
api_router.include_router(
    document_processing.router, prefix="/docs", tags=["Document Processing"]
)
api_router.include_router(
    websocket_notifier.router, prefix="/docs", tags=["Document Processing"]
)  # WebSocket routes
api_router.include_router(
    image2url.router, prefix="/image2url", tags=["Image Processing"]
)
api_router.include_router(
    pdf2image.router, prefix="/pdf2image", tags=["PDF Processing"]
)
api_router.include_router(retriever.router, prefix="/retriever", tags=["Retriever"])
api_router.include_router(
    chat_summary.router, prefix="/chat-summary", tags=["Chat Summary"]
)
api_router.include_router(
    closing_form.router, prefix="/closing-form", tags=["Closing Form"]
)
api_router.include_router(
    context_compression.router,
    prefix="/context-compression",
    tags=["Context Compression"],
)
api_router.include_router(
    sqlserver_queries.router, prefix="/sqlserver", tags=["SQLServer Query"]
)
