from fastapi import APIRouter
from app.api.v1.endpoints import image2url

endpoints_router = APIRouter()

endpoints_router.include_router(image2url.router, prefix="/image2url", tags=["image2url"])
