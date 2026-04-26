"""
API v1: routes are registered in `registry` (flat modules under this package).
"""
from app.api.v1.registry import api_router

__all__ = ["api_router"]
