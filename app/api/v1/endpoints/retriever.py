# api/chat_api.py
from fastapi import APIRouter, Depends

from app.core.dependencies import get_rag_instance
from app.ragsystem import chart_analyze, retriever_for_yamato
from app.schemas.base import ChatRequest, ChartRequest

router = APIRouter()

@router.post("/db")
def db(request: ChatRequest,rag_instance=Depends(get_rag_instance)):
    print(request.collection_name)
    retriever = retriever_for_yamato.retriever(rag_system=rag_instance,collection_name=request.collection_name)
    return retriever.get_response(request.question)

@router.post("/excel")
def excel(request: ChatRequest,rag_instance=Depends(get_rag_instance)):
    print(request.collection_name)
    retriever = retriever_for_yamato.retriever(rag_system=rag_instance,collection_name=request.collection_name)
    return retriever.get_charts(request.question)

@router.post("/charts")
async def charts(request: ChartRequest):
    analyze = chart_analyze.analyze()
    return await analyze.get_response(request.data_source, request.requirements)
