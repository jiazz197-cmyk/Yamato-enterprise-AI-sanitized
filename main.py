import os
import uvicorn
from contextlib import asynccontextmanager
from app.api.v1.router import endpoints_router
from fastapi import FastAPI
from app.ragsystem.RAGretriever import create_rag_retriever_system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化 RAG 系统
    print("正在初始化 RAG 检索系统...")
    try:
        rag_system = create_rag_retriever_system(
            host=os.getenv("POSTGRES_SERVER", "localhost"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "change_me_pg_password"),
            database=os.getenv("POSTGRES_DB", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            table_prefix="doc_collection",
            instance_id=1,
            bge_m3_api_url=os.getenv("BGE_M3_API_URL", "http://localhost:8000/v1/embeddings"),
            reranker_api_url=os.getenv("RERANKER_API_URL", "http://localhost:8001/v1/rerank"),
            default_top_k=20,
            default_top_n=3
        )
        app.state.rag = rag_system #这里对state.rag进行注入
        print("RAG 系统初始化完成")
    except Exception as e:
        print(f"RAG 系统初始化失败: {e}")
        app.state.rag = None
    
    yield  # 应用运行期间
    
    # 关闭时清理资源
    print("正在清理 RAG 系统资源...")
    if hasattr(app.state, 'rag') and app.state.rag:
        app.state.rag.cleanup()
    print("RAG 系统资源清理完成")


app = FastAPI(lifespan=lifespan)
# 挂载路由
app.include_router(endpoints_router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)