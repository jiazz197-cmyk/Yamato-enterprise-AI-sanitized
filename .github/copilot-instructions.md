# AI Data Tool - Copilot Instructions

## 项目概述
基于 FastAPI 的 AI 数据工具后端服务，提供文件管理、缓存、异步任务等基础功能。外部服务集成（RAGFlow、Dify、N8N、Superset、DataHub）已预留配置，待后续启用。

## 架构模式

### 应用入口与中间件链
入口文件 `main.py` 通过 `create_app()` 工厂函数创建应用。中间件按顺序加载：
```
MonitoringMiddleware → RequestSizeMiddleware → RateLimitMiddleware → CacheMiddleware
```
中间件通过 `settings.ENABLE_*` 开关控制启用状态。

### 核心模块布局
- `app/core/` - 基础设施：配置、数据库、缓存、安全、日志
- `app/models/orm/` - SQLAlchemy ORM 模型，继承 `app/core/database.py` 的 `Base`
- `app/api/` - API 路由和业务逻辑
- `app/integrations/` - 外部服务集成（监控、健康检查）

### 配置管理
所有配置通过 `app/core/config.py` 的 `Settings` 类管理，使用 pydantic-settings 从环境变量/`.env` 加载。添加新配置时：
```python
# 使用 Field 定义默认值和环境变量名
NEW_CONFIG: str = Field("default_value", env="NEW_CONFIG")
```

## 关键约定

### 数据库会话
使用依赖注入获取会话，参考 `app/core/dependencies.py`：
```python
from app.core.dependencies import get_db
from fastapi import Depends

@router.get("/example")
def example(db: Session = Depends(get_db)):
    ...
```

### API 认证
使用 `app/core/security.py` 中的 API Key 验证：
```python
from app.core.security import require_api_key

@router.get("/protected", dependencies=[Depends(require_api_key())])
async def protected_endpoint():
    return {"message": "Access granted"}
```

### 异常处理
使用 `app/core/exceptions.py` 中预定义的异常类：
- `ValidationError` - 参数校验失败 (422)
- `NotFoundError` - 资源不存在 (404)
- `ExternalServiceError` - 外部服务调用失败 (502)
- `RateLimitError` - 限流 (429)

### 日志规范
使用 `app/core/logging.py` 中的命名 logger：
```python
from app.core.logging import request_logger, database_logger, security_logger
# 或
from app.core.logging import get_logger
logger = get_logger("module_name")  # 创建 app.module_name logger
```

### Redis 缓存
通过 `app/core/cache.py` 的 `redis_manager` 操作缓存：
```python
from app.core.cache import redis_manager
await redis_manager.set("key", {"data": "value"}, ttl=300)
await redis_manager.get("key")
```

### 文件存储
MinIO 操作使用 `app/core/storage.py` 中的辅助函数：
- `upload_to_minio(file_path, file_name)` - 上传本地文件
- `upload_buffer_to_minio(buffer, file_name)` - 上传内存缓冲区
- `save_file_from_minio(object_name)` - 下载到临时文件

## API 路由设计模式

### 路由结构
```
app/api/
├── __init__.py
├── v1/
│   ├── __init__.py      # 汇总 v1 所有路由
│   ├── example.py       # 示例路由
│   └── <module>.py      # 其他业务模块路由
└── taskmanager.py       # 异步任务管理器
```

### 创建新路由模块
1. 在 `app/api/v1/` 下创建路由文件（如 `users.py`）
2. 在 `app/api/v1/__init__.py` 中注册路由：
```python
from app.api.v1 import users
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
```

### 路由文件模板
参考 `app/api/v1/example.py`：
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger("module_name")

# 1. 定义响应模型
class ItemResponse(BaseModel):
    id: int
    name: str

# 2. 定义路由
@router.get("/", response_model=ItemResponse, summary="获取列表")
async def get_items(db: Session = Depends(get_db)):
    logger.info("Get items called")
    return ItemResponse(id=1, name="example")
```

### 路由设计原则
- 使用 `response_model` 明确响应结构
- 使用 `summary` 为 API 文档提供简短描述
- 使用 `tags` 分组相关路由
- 异常使用 `app/core/exceptions.py` 中预定义的类

## ORM 模型规范

### 模型定义
ORM 模型继承 `app/core/database.py` 的 `Base`：
```python
from app.core.database import Base

class MyModel(Base):
    __tablename__ = "my_table"
    id = Column(Integer, primary_key=True)
```

### 现有模型
- `app/models/orm/file_resource.py` - 文件资源表（MinIO 文件元数据）

## 启动与调试

### 本地运行
```bash
python main.py  # 使用 uvicorn，配置来自 settings
```
API 文档：`http://localhost:8000/api/v1/docs`

### 环境变量
关键配置项（参考 `.env`）：
- `POSTGRES_*` - PostgreSQL 连接
- `REDIS_*` - Redis 连接
- `MINIO_*` - MinIO 对象存储
- `ENABLE_RATE_LIMIT`, `ENABLE_CACHE` - 中间件开关
- `ENABLE_RATE_LIMIT`, `ENABLE_CACHE` - 中间件开关
