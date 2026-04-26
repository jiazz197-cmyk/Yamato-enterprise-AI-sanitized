# api/chat_api.py
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import get_rag_instance
from app.core.config import settings
from app.core.security import get_current_user
from app.models.orm.platform.user import User, UserRole
from app.ragsystem import chart_analyze, retriever_for_yamato
from app.schemas.base import ChatRequest, ChartRequest

router = APIRouter()


def _collection_name_from_instance_id(instance_id: int) -> str:
    # PGVector internally stores physical tables as data_<table_name>.
    # Here we must pass logical table_name to avoid data_data_* mismatch.
    return f"doc_collection_{instance_id}"


def _ensure_collection_access(collection_name: str, current_user: User) -> str:
    if current_user.role == UserRole.superuser:
        return collection_name

    allowed_collections = {name.strip() for name in settings.RETRIEVER_ALLOWED_COLLECTIONS if name.strip()}
    compatible_allowed = set(allowed_collections)
    for name in allowed_collections:
        if name.startswith("data_"):
            compatible_allowed.add(name[len("data_"):])

    if collection_name not in compatible_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="collection access denied",
        )
    return collection_name


@router.post("/db")
def db(
    request: ChatRequest,
    instance_id: int = Query(..., ge=1, description="RAG instance id"),
    rag_instance=Depends(get_rag_instance),
    current_user: User = Depends(get_current_user),
):
    collection_name = _collection_name_from_instance_id(instance_id)
    collection_name = _ensure_collection_access(collection_name, current_user)
    retriever = retriever_for_yamato.retriever(rag_system=rag_instance, collection_name=collection_name)
    return retriever.get_response(request.question)


@router.post("/excel")
def excel(
    request: ChatRequest,
    instance_id: int = Query(..., ge=1, description="RAG instance id"),
    rag_instance=Depends(get_rag_instance),
    current_user: User = Depends(get_current_user),
):
    collection_name = _collection_name_from_instance_id(instance_id)
    collection_name = _ensure_collection_access(collection_name, current_user)
    retriever = retriever_for_yamato.retriever(rag_system=rag_instance, collection_name=collection_name)
    return retriever.get_charts(request.question)


@router.post("/charts")
async def charts(
    request: ChartRequest,
    current_user: User = Depends(get_current_user),
):
    # Keep expensive chart analysis limited to authenticated users.
    _ = current_user
    analyze = chart_analyze.analyze()
    return await analyze.get_response(request.data_source, request.requirements)
