"""
FastAPI application entrypoint.
"""
import os

# ===== 在导入其他模块之前设置 GPU 环境 =====
# 从 .env 文件读取配置（如果存在）
from dotenv import load_dotenv
load_dotenv()

# 使用环境变量标志避免重复初始化（热重载时模块会被多次导入）
if not os.environ.get("_GPU_INITIALIZED"):
    os.environ["_GPU_INITIALIZED"] = "1"
    
    # 设置本地模型使用的 GPU 设备
    LOCAL_GPU_DEVICE = os.environ.get("LOCAL_MODEL_GPU_DEVICE", "3")
    # 注意：不设置 CUDA_VISIBLE_DEVICES，因为 Docker 服务需要访问其他 GPU
    # 我们通过各个库的 API 来指定 GPU（如 paddle.set_device, torch device 等）
    os.environ.setdefault("LOCAL_MODEL_GPU_DEVICE", LOCAL_GPU_DEVICE)
    
    # 设置 PaddlePaddle 环境变量以避免版本兼容性问题
    os.environ.setdefault("FLAGS_use_mkldnn", "0")  # 禁用 MKL-DNN 优化
    os.environ.setdefault("FLAGS_use_cudnn", "1")   # 使用 cuDNN（GPU 环境）
    
    # 设置 Paddle 设备（如果 paddle 可用）
    try:
        import paddle
        paddle.set_device(f'gpu:{LOCAL_GPU_DEVICE}')
        print(f"✅ Paddle 设备已设置为 GPU:{LOCAL_GPU_DEVICE}")
    except ImportError:
        print("ℹ️  Paddle 不可用，跳过 GPU 设置")
    except Exception as e:
        print(f"⚠️  设置 Paddle GPU 失败: {e}")
    
    # 设置 PyTorch 默认设备（如果需要）
    try:
        import torch
        if torch.cuda.is_available():
            # 不设置默认设备，让各个模型自己指定
            print(f"✅ PyTorch CUDA 可用，本地模型将使用 GPU:{LOCAL_GPU_DEVICE}")
        else:
            print("ℹ️  PyTorch CUDA 不可用")
    except ImportError:
        pass
else:
    # 已经初始化过，直接读取配置
    LOCAL_GPU_DEVICE = os.environ.get("LOCAL_MODEL_GPU_DEVICE", "3")
# ===== GPU 环境设置完成 =====

from app.ragsystem.RAGretriever import create_rag_retriever_system

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.api.v1 import api_router
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
    """Protect metrics endpoint from anonymous scraping in non-internal networks."""
    if not settings.METRICS_REQUIRE_API_KEY:
        return
    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )


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
    
    # 2. 集成 TaskManager 和 ExecutorManager
    try:
        from app.core.executor import executor_manager
        from app.api.taskmanager import task_manager
        executor_manager.set_task_manager(task_manager, auto_sync=False)  # 默认不自动同步，按需开启
        print("✅ ExecutorManager 已集成 TaskManager")
    except Exception as e:
        print(f"⚠️  ExecutorManager 集成 TaskManager 失败: {e}")
    
    # 2.5 注册任务观察者（支持实时推送）
    try:
        from app.api.taskmanager import task_manager
        from app.integrations.observers import (
            LoggingObserver, 
            MetricsCollector,
        )
        from app.api.v1.websocket_notifier import (
            WebSocketTaskObserver,
            ws_manager
        )
        
        # 注册日志观察者（记录所有事件）
        logging_observer = LoggingObserver()
        await task_manager.register_observer(logging_observer)
        
        # 注册指标收集器（用于 Prometheus 监控）
        metrics_observer = MetricsCollector()
        await task_manager.register_observer(metrics_observer)
        app.state.metrics_observer = metrics_observer  # 保存到 app.state
        
        # 注册 WebSocket 推送观察者（实时推送给客户端）
        ws_observer = WebSocketTaskObserver(ws_manager)
        await task_manager.register_observer(ws_observer)
        task_manager.set_notify_loop(asyncio.get_running_loop())
        
        print("✅ 任务观察者注册完成")
        observer_stats = task_manager.get_observer_stats()
        print(f"  - 已注册观察者数: {observer_stats['observer_count']}")
        print(f"  - 观察者状态: {'启用' if observer_stats['observer_enabled'] else '禁用'}")
        
    except Exception as e:
        print(f"⚠️  注册任务观察者失败: {e}")
    
    # 3. 测试 Redis 连接
    try:
        await redis_manager.test_connection()
    except Exception:
        # 不阻塞启动，中间件会处理 Redis 不可用的情况
        pass
    
    # 4. 测试 MinIO 连接
    try:
        from app.core.storage import get_minio_client, MINIO_BUCKET_NAME
        client = get_minio_client()
        # 尝试检查 bucket 是否存在（不阻塞启动）
        client.bucket_exists(MINIO_BUCKET_NAME)
        print(f"✅ MinIO 连接成功，bucket: {MINIO_BUCKET_NAME}")
    except Exception as e:
        print(f"⚠️  MinIO 连接失败: {e}，服务将降级运行")
    
    # 5. 初始化 RAG 系统（包含 BGE-M3 嵌入模型和 Reranker 重排序器）
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
        app.state.rag = rag_system  # 这里对state.rag进行注入
        print("✅ RAG 系统初始化完成")
        print(f"  - BGE-M3 嵌入模型: {settings.BGE_M3_API_URL}")
        print(f"  - Reranker 重排序器: {settings.RERANKER_API_URL}")
    except Exception as e:
        print(f"⚠️  RAG 系统初始化失败: {e}")
        app.state.rag = None
    
    yield  # 应用运行中
    
    # === Shutdown ===
    import asyncio
    import signal
    import sys
    
    print("\n🛑 开始关闭...")
    
    # 设置全局关闭超时（10秒后强制退出）
    def force_exit(signum=None, frame=None):
        print("\n⚠️  关闭超时，强制退出")
        sys.exit(1)
    
    # 注册超时信号
    signal.signal(signal.SIGALRM, force_exit)
    signal.alarm(10)  # 10秒后触发
    
    try:
        # 1. 先清理 RAG 系统（非阻塞）
        try:
            if hasattr(app.state, 'rag') and app.state.rag:
                app.state.rag.cleanup()
            print("✅ RAG 系统清理完成")
        except Exception as e:
            print(f"⚠️  清理 RAG 时出错: {e}")
        
        # 2. 关闭线程池（不等待，直接取消）
        try:
            from app.core.executor import executor_manager
            # wait=False: 不等待任务完成
            # cancel_futures=True: 取消所有等待中的任务
            executor_manager.shutdown(wait=False, cancel_futures=True)
            print("✅ 线程池已关闭")
        except Exception as e:
            print(f"⚠️  关闭线程池时出错: {e}")
        
        # 3. 移除观察者（1秒超时）
        try:
            from app.api.taskmanager import task_manager
            await asyncio.wait_for(task_manager.remove_all_observers(), timeout=1.0)
            print("✅ 观察者已清理")
        except asyncio.TimeoutError:
            print("⚠️  清理观察者超时，跳过")
        except Exception as e:
            print(f"⚠️  清理观察者时出错: {e}")
        
        # 4. 关闭 WebSocket（1秒超时）
        try:
            from app.api.v1.websocket_notifier import ws_manager
            await asyncio.wait_for(ws_manager.disconnect_all(), timeout=1.0)
            print("✅ WebSocket 已关闭")
        except asyncio.TimeoutError:
            print("⚠️  WebSocket 关闭超时，跳过")
        except Exception as e:
            print(f"⚠️  关闭 WebSocket 时出错: {e}")
        
        # 5. 关闭 Redis（2秒超时）
        try:
            await asyncio.wait_for(redis_manager.close(), timeout=2.0)
            print("✅ Redis 已关闭")
        except asyncio.TimeoutError:
            print("⚠️  Redis 关闭超时，跳过")
        except Exception as e:
            print(f"⚠️  关闭 Redis 时出错: {e}")
        
    finally:
        # 取消超时警报
        signal.alarm(0)
        print("🛑 关闭完成\n")

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

    # Prometheus metrics endpoint
    @app.get(f"{settings.API_V1_STR}/metrics", include_in_schema=False)
    async def metrics_endpoint(_: None = Depends(require_metrics_access)):
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
        "main:app",  # 使用字符串以支持热重载
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
