"""FastAPI 应用入口。"""
import os

# GPU：须在导入其他模块前配置；.env 由 dotenv 加载
from dotenv import load_dotenv
load_dotenv()

# 热重载会重复导入模块，用环境变量避免重复初始化 GPU
if not os.environ.get("_GPU_INITIALIZED"):
    os.environ["_GPU_INITIALIZED"] = "1"
    
    LOCAL_GPU_DEVICE = os.environ.get("LOCAL_MODEL_GPU_DEVICE", "3")
    # 不设 CUDA_VISIBLE_DEVICES，Docker 内仍需访问多块 GPU；设备由各库 API 指定
    os.environ.setdefault("LOCAL_MODEL_GPU_DEVICE", LOCAL_GPU_DEVICE)
    
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_use_cudnn", "1")
    
    try:
        import paddle
        paddle.set_device(f'gpu:{LOCAL_GPU_DEVICE}')
        print(f"[success] Paddle 设备已设置为 GPU:{LOCAL_GPU_DEVICE}")
    except ImportError:
        print("[info] Paddle 不可用，跳过 GPU 设置")
    except Exception as e:
        print(f"[warning] 设置 Paddle GPU 失败: {e}")
    
    try:
        import torch
        if torch.cuda.is_available():
            print(f"[success] PyTorch CUDA 可用，本地模型将使用 GPU:{LOCAL_GPU_DEVICE}")
        else:
            print("[info] PyTorch CUDA 不可用")
    except ImportError:
        pass
else:
    LOCAL_GPU_DEVICE = os.environ.get("LOCAL_MODEL_GPU_DEVICE", "3")

from app.ragsystem.RAGretriever import create_rag_retriever_system

import asyncio
from contextlib import asynccontextmanager

import sys

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.api.v1 import api_router
from app.api.v1.tags import OPENAPI_TAG_METADATA
from app.core.cache import redis_manager
from app.core.config import settings
from app.core.exceptions import APIException
from app.core.logging import setup_logging
from app.core.middleware.middleware_cache import CacheMiddleware
from app.core.middleware.monitoring import MonitoringMiddleware
from app.core.middleware.rate_limit import RateLimitMiddleware
from app.core.middleware.request_size import RequestSizeMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.integrations.monitoring.health_check import health_service
from app.integrations.monitoring.prometheus import metrics as prometheus_metrics


def require_metrics_access(x_api_key: str | None = Header(default=None, alias="X-API-KEY")) -> None:
    """生产场景下用 API Key 限制 /metrics，避免公网裸奔。"""
    if not settings.METRICS_REQUIRE_API_KEY:
        return
    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )


def _startup_check_sqlserver_connectivity(app: FastAPI) -> None:
    """Check U8/PDM connectivity at startup without blocking service startup."""
    try:
        from app.integrations.sqlserver import test_sqlserver_connectivity

        sqlserver_checks = test_sqlserver_connectivity()
        app.state.sqlserver_connectivity = sqlserver_checks
        for db_name in ("u8", "pdm"):
            result = sqlserver_checks.get(db_name, {})
            if result.get("ok"):
                print(
                    f"[success] {db_name.upper()} SQLServer 连接成功 "
                    f"({result.get('latency_ms')}ms)"
                )
            else:
                print(
                    f"[warning] {db_name.upper()} SQLServer 连接失败: "
                    f"{result.get('error')}"
                )
    except Exception as e:
        app.state.sqlserver_connectivity = {}
        print(f"[warning] SQLServer 连通性检查失败: {e}")


def _startup_resume_quotation_services() -> None:
    """
    Recover quotation task queue after process restart.

    - reset stale running tasks to queued
    - dispatch queued tasks for each owner
    """
    try:
        from app.integrations.Quotation_Generation.quotation_task_workers import (
            dispatch_quotation_queue_for_owner,
        )
        from app.core.database import SessionLocal
        from app.core.task_manager import task_manager
        from app.models.orm.quotation_task import QuotationTask, QuotationTaskStatus

        db = SessionLocal()
        stale_task_ids: list[str] = []
        try:
            stale_running_tasks = (
                db.query(QuotationTask)
                .filter(QuotationTask.status == QuotationTaskStatus.running.value)
                .all()
            )
            for task in stale_running_tasks:
                task.status = QuotationTaskStatus.queued.value
                task.message = "服务重启后重新排队"
                task.started_at = None
                task.completed_at = None
                task.error = None
                task.progress = 0
                task.awaiting_approval_at = None
                stale_task_ids.append(task.task_id)

            if stale_running_tasks:
                db.commit()
                print(f"[info] 已重置 {len(stale_running_tasks)} 个中断中的报价任务为排队状态")

            owner_rows = (
                db.query(QuotationTask.owner_id)
                .filter(
                    or_(
                        QuotationTask.status == QuotationTaskStatus.queued.value,
                        QuotationTask.status == QuotationTaskStatus.running.value,
                    )
                )
                .distinct()
                .all()
            )
            owner_ids = [str(row[0]).strip() for row in owner_rows if str(row[0]).strip()]
        finally:
            db.close()

        async def _sync_redis_status() -> None:
            for task_id in stale_task_ids:
                await task_manager.update_status(task_id, "queued", "服务重启后重新排队")

        if stale_task_ids:
            asyncio.get_running_loop().create_task(_sync_redis_status())

        for owner_id in owner_ids:
            dispatch_quotation_queue_for_owner(owner_id)

        if owner_ids:
            print(f"[success] 报价任务服务已恢复并调度，影响用户数: {len(owner_ids)}")
        else:
            print("[info] 报价任务服务启动完成，无待调度任务")
    except Exception as e:
        print(f"[warning] 报价任务服务启动失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化依赖，关闭时按序释放。"""
    app.state.metrics = prometheus_metrics
    
    try:
        from app.core.database import init_db_tables
        init_db_tables()
    except Exception as e:
        print(f"[warning] 数据库表初始化失败: {e}")
    
    try:
        from app.core.executor import executor_manager
        from app.core.task_manager import task_manager
        executor_manager.set_task_manager(task_manager, auto_sync=False)  # 默认不向 TaskManager 自动同步
        from app.core.executor import PYTHON_39_PLUS
        print(
            f"[info] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}, "
            f"advanced shutdown: {PYTHON_39_PLUS}"
        )
        print("[success] ExecutorManager 已集成 TaskManager")
    except Exception as e:
        print(f"[warning] ExecutorManager 集成 TaskManager 失败: {e}")
    
    try:
        from app.core.task_manager import task_manager
        from app.integrations.observers import (
            LoggingObserver, 
            MetricsCollector,
        )
        from app.core.websocket_task_manager import (
            WebSocketTaskObserver,
            ws_manager,
        )
        
        logging_observer = LoggingObserver()
        await task_manager.register_observer(logging_observer)
        
        metrics_observer = MetricsCollector()
        await task_manager.register_observer(metrics_observer)
        app.state.metrics_observer = metrics_observer
        
        ws_observer = WebSocketTaskObserver(ws_manager)
        await task_manager.register_observer(ws_observer)
        task_manager.set_notify_loop(asyncio.get_running_loop())
        
        print("[success] 任务观察者注册完成")
        observer_stats = task_manager.get_observer_stats()
        print(f"  - 已注册观察者数: {observer_stats['observer_count']}")
        print(f"  - 观察者状态: {'启用' if observer_stats['observer_enabled'] else '禁用'}")
        
    except Exception as e:
        print(f"[warning] 注册任务观察者失败: {e}")

    _startup_check_sqlserver_connectivity(app)
    _startup_resume_quotation_services()

    try:
        from app.core.retention_scheduler import run_retention_once, start_retention_scheduler

        await run_retention_once()
        app.state.retention_task = start_retention_scheduler()
        print("[success] 报价任务 retention 调度已启动")
    except Exception as e:
        print(f"[warning] 报价任务 retention 调度启动失败: {e}")
    
    try:
        await redis_manager.test_connection()
    except Exception:
        # 启动不依赖 Redis 就绪，后续由中间件兜底
        pass
    
    try:
        from app.core.storage import get_minio_client, MINIO_BUCKET_NAME
        client = get_minio_client()
        client.bucket_exists(MINIO_BUCKET_NAME)
        print(f"[success] MinIO 连接成功，bucket: {MINIO_BUCKET_NAME}")
    except Exception as e:
        print(f"[warning] MinIO 连接失败: {e}，服务将降级运行")
    
    try:
        rag_system = create_rag_retriever_system(
            host=settings.POSTGRES_SERVER,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            port=settings.POSTGRES_PORT,
            table_prefix="doc_collection",
            instance_id=1,
            bge_m3_api_url=settings.BGE_M3_API_URL,
            reranker_api_url=settings.RERANKER_API_URL,
            default_top_k=20,
            default_top_n=3
        )
        app.state.rag = rag_system
        print("[success] RAG 系统初始化完成")
        print(f"  - BGE-M3 嵌入模型: {settings.BGE_M3_API_URL}")
        print(f"  - Reranker 重排序器: {settings.RERANKER_API_URL}")
    except Exception as e:
        print(f"[warning] RAG 系统初始化失败: {e}")
        app.state.rag = None
    
    yield
    
    import signal
    import sys
    
    print("\n[shutdown] 开始关闭...")
    
    def force_exit(signum=None, frame=None):
        print("\n[warning] 关闭超时，强制退出")
        sys.exit(1)
    
    signal.signal(signal.SIGALRM, force_exit)
    signal.alarm(10)
    
    try:
        try:
            if hasattr(app.state, 'rag') and app.state.rag:
                app.state.rag.cleanup()
            print("[success] RAG 系统清理完成")
        except Exception as e:
            print(f"[warning] 清理 RAG 时出错: {e}")
        
        try:
            from app.core.executor import executor_manager
            executor_manager.shutdown(wait=False, cancel_futures=True)
            print("[success] 线程池已关闭")
        except Exception as e:
            print(f"[warning] 关闭线程池时出错: {e}")
        
        try:
            from app.core.task_manager import task_manager
            await asyncio.wait_for(task_manager.remove_all_observers(), timeout=1.0)
            print("[success] 观察者已清理")
        except asyncio.TimeoutError:
            print("[warning] 清理观察者超时，跳过")
        except Exception as e:
            print(f"[warning] 清理观察者时出错: {e}")
        
        try:
            from app.core.retention_scheduler import stop_retention_scheduler
            await stop_retention_scheduler()
            print("[success] 报价任务 retention 调度已停止")
        except Exception as e:
            print(f"[warning] 停止 retention 调度时出错: {e}")

        try:
            from app.core.websocket_task_manager import ws_manager
            await asyncio.wait_for(ws_manager.disconnect_all(), timeout=1.0)
            print("[success] WebSocket 已关闭")
        except asyncio.TimeoutError:
            print("[warning] WebSocket 关闭超时，跳过")
        except Exception as e:
            print(f"[warning] 关闭 WebSocket 时出错: {e}")
        
        try:
            await asyncio.wait_for(redis_manager.close(), timeout=2.0)
            print("[success] Redis 已关闭")
        except asyncio.TimeoutError:
            print("[warning] Redis 关闭超时，跳过")
        except Exception as e:
            print(f"[warning] 关闭 Redis 时出错: {e}")
        
    finally:
        signal.alarm(0)
        print("[shutdown] 关闭完成\n")

def create_app() -> FastAPI:
    is_production = str(settings.ENVIRONMENT).strip().lower() in {"production", "prod"}
    docs_url = None if is_production else f"{settings.API_V1_STR}/docs"
    redoc_url = None if is_production else f"{settings.API_V1_STR}/redoc"
    openapi_url = None if is_production else f"{settings.API_V1_STR}/openapi.json"

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        debug=settings.DEBUG,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        openapi_tags=OPENAPI_TAG_METADATA,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.redis = redis_manager.redis_client

    cors_origins = settings.BACKEND_CORS_ORIGINS or []
    allow_credentials = "*" not in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    allowed_hosts = settings.ALLOWED_HOSTS or ["localhost", "127.0.0.1"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    app.add_middleware(MonitoringMiddleware)
    if settings.ENABLE_SECURITY_HEADERS:
        app.add_middleware(SecurityHeadersMiddleware)
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

    @app.get(f"{settings.API_V1_STR}/metrics", include_in_schema=False)
    async def metrics_endpoint(_: None = Depends(require_metrics_access)):
        data = prometheus_metrics.get_metrics()
        return Response(content=data, media_type="text/plain")

    @app.exception_handler(APIException)
    async def api_exception_handler(request, exc: APIException):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


setup_logging()
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",  # 使用字符串以支持热重载
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
