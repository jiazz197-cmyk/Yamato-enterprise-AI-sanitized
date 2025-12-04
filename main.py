"""
FastAPI application entrypoint.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.v1 import api_router
from app.core.cache import redis_manager
from app.core.config import settings
from app.core.exceptions import APIException
from app.core.logging import setup_logging
from app.core.middleware.middleware_cache import CacheMiddleware
from app.core.middleware.monitoring import MonitoringMiddleware
from app.core.middleware.rate_limit import RateLimitMiddleware
from app.core.middleware.request_size import RequestSizeMiddleware
from app.integrations.monitoring.health_check import health_service
from app.integrations.monitoring.prometheus import metrics as prometheus_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时清理资源"""
    # === Startup ===
    app.state.metrics = prometheus_metrics
    
    # 1. 初始化数据库表
    try:
        from app.core.database import init_db_tables
        init_db_tables()
    except Exception as e:
        print(f"⚠️  数据库表初始化失败: {e}")
    
    # 2. 测试 Redis 连接
    try:
        await redis_manager.test_connection()
    except Exception:
        # 不阻塞启动，中间件会处理 Redis 不可用的情况
        pass
    
    # 3. 测试 MinIO 连接
    try:
        from app.core.storage import get_minio_client, MINIO_BUCKET_NAME
        client = get_minio_client()
        # 尝试检查 bucket 是否存在（不阻塞启动）
        client.bucket_exists(MINIO_BUCKET_NAME)
        print(f"✅ MinIO 连接成功，bucket: {MINIO_BUCKET_NAME}")
    except Exception as e:
        print(f"⚠️  MinIO 连接失败: {e}，服务将降级运行")
    
    yield  # 应用运行中
    
    # === Shutdown ===
    # 1. 关闭文档处理线程池
    try:
        from app.core.executor import executor_manager
        executor_manager.shutdown_executor()
    except Exception as e:
        print(f"关闭文档处理线程池时出错: {e}")
    
    # 2. 关闭 Redis 连接
    try:
        await redis_manager.close()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        debug=settings.DEBUG,
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.redis = redis_manager.redis_client

    cors_origins = settings.BACKEND_CORS_ORIGINS or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(MonitoringMiddleware)
    app.add_middleware(RequestSizeMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CacheMiddleware)

    @app.get("/")
    async def root():
        return {"project": settings.PROJECT_NAME, "version": settings.VERSION}

    @app.get(f"{settings.API_V1_STR}/health")
    async def api_health():
        services = await health_service.check_all_services()
        overall = "healthy" if all(item["status"] == "healthy" for item in services.values()) else "unhealthy"
        return {"status": overall, "services": services}

    # Prometheus metrics endpoint
    @app.get(f"{settings.API_V1_STR}/metrics", include_in_schema=False)
    async def metrics_endpoint():
        # return Prometheus metrics in text format
        data = prometheus_metrics.get_metrics()
        return Response(content=data, media_type="text/plain")

    # 注册全局 APIException 处理器，统一返回结构
    @app.exception_handler(APIException)
    async def api_exception_handler(request, exc: APIException):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    # 注册 API 路由
    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


setup_logging()
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
