"""
应用配置管理
"""
import os
import secrets
from pathlib import Path
from typing import List, Optional, Union, Any
import threading

from pydantic import Field, validator, field_validator, ValidationInfo
from pydantic_settings import BaseSettings
from pydantic._internal._model_construction import ModelMetaclass

from dotenv import load_dotenv
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
sys.path.insert(0, project_root)

load_dotenv()

def _split_comma_separated(value: Union[str, List[str]]) -> List[str]:
    """将逗号分隔配置转换成列表。"""
    if isinstance(value, str):
        if not value or value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _is_insecure_value(value: Any) -> bool:
    """判断敏感配置是否仍为占位符或弱默认值。"""
    if not isinstance(value, str):
        return False

    normalized = value.strip().lower()
    if not normalized:
        return True

    insecure_keywords = (
        "change-me",
        "changeme",
        "your_",
        "your-",
        "placeholder",
        "example",
        "demo",
        "default",
        "minioadmin",
        "change_me_super_pass",
        "app-change_me_chat_api_key",
    )

    return any(keyword in normalized for keyword in insecure_keywords)


class SingletonModelMeta(ModelMetaclass):
    """
    线程安全的单例元类，继承自 pydantic 的 ModelMetaclass
    确保与 pydantic BaseSettings 兼容
    """
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        # 双重检查锁定模式
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]


class Settings(BaseSettings, metaclass=SingletonModelMeta):
    """
    全局配置对象，统一读取 .env 与环境变量（单例模式）
    
    使用元类确保全局唯一实例，兼容 pydantic BaseSettings
    """

    # 基础信息
    PROJECT_NAME: str = Field("AI Data Tool", env="PROJECT_NAME")
    VERSION: str = Field("1.0.0", env="VERSION")
    DESCRIPTION: str = Field("AI数据工具后端API服务", env="DESCRIPTION")
    ENVIRONMENT: str = Field("development", env="ENVIRONMENT")
    DEBUG: bool = Field(True, env="DEBUG")
    API_V1_STR: str = Field("/api/v1", env="API_V1_STR")

    # 服务端网络
    HOST: str = Field("0.0.0.0", env="HOST")
    PORT: int = Field(8000, env="PORT")
    ALLOWED_HOSTS: List[str] = Field(default_factory=lambda: ["*"], env="ALLOWED_HOSTS")

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"], env="BACKEND_CORS_ORIGINS")

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return _split_comma_separated(v)
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @validator("ALLOWED_HOSTS", pre=True)
    def split_allowed_hosts(cls, v: Union[str, List[str]]) -> List[str]:
        return _split_comma_separated(v)

    @validator("RETRIEVER_ALLOWED_COLLECTIONS", pre=True)
    def split_retriever_allowed_collections(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # 数据库
    POSTGRES_SERVER: str = Field("127.0.0.1", env="POSTGRES_SERVER")
    POSTGRES_USER: str = Field("pguser", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("change_me_postgres_password", env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field("pgdb", env="POSTGRES_DB")
    POSTGRES_PORT: int = Field(5432, env="POSTGRES_PORT")

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """根据单项设置拼接数据库连接串。"""
        return (
            f"postgresql://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:"
            f"{self.POSTGRES_PORT}/"
            f"{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = Field("127.0.0.1", env="REDIS_HOST")
    REDIS_PORT: int = Field(6379, env="REDIS_PORT")
    REDIS_DB: int = Field(0, env="REDIS_DB")
    REDIS_PASSWORD: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    REDIS_MAX_CONNECTIONS: int = Field(10, env="REDIS_MAX_CONNECTIONS")

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # MinIO
    MINIO_ENDPOINT: str = Field("127.0.0.1:9000", env="MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: str = Field("change_me_minio_access_key", env="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = Field("change_me_minio_secret_key", env="MINIO_SECRET_KEY")
    MINIO_SECURE: bool = Field(False, env="MINIO_SECURE")
    MINIO_BUCKET_NAME: str = Field("yamatodev", env="MINIO_BUCKET_NAME")

    # 安全
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32), env="SECRET_KEY")
    ALGORITHM: str = Field("HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    INTERNAL_API_KEY: str = Field("change_me_internal_api_key", env="INTERNAL_API_KEY")
    RETRIEVER_ALLOWED_COLLECTIONS: List[str] = Field(default_factory=list, env="RETRIEVER_ALLOWED_COLLECTIONS")

    # 启动引导账号（仅建议开发环境使用）
    BOOTSTRAP_SUPERUSER_USERNAME: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_USERNAME")
    BOOTSTRAP_SUPERUSER_EMAIL: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_EMAIL")
    BOOTSTRAP_SUPERUSER_PASSWORD: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_PASSWORD")

    # 限流
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(100, env="RATE_LIMIT_REQUESTS_PER_MINUTE")
    RATE_LIMIT_REQUESTS_PER_HOUR: int = Field(1000, env="RATE_LIMIT_REQUESTS_PER_HOUR")
    RATE_LIMIT_AUTH: int = Field(100, env="RATE_LIMIT_AUTH")
    RATE_LIMIT_ANON: int = Field(20, env="RATE_LIMIT_ANON")
    RATE_LIMIT_EXPENSIVE_AUTH: int = Field(20, env="RATE_LIMIT_EXPENSIVE_AUTH")
    RATE_LIMIT_EXPENSIVE_ANON: int = Field(5, env="RATE_LIMIT_EXPENSIVE_ANON")
    RATE_LIMIT_WINDOW: int = Field(60, env="RATE_LIMIT_WINDOW")

    # 中间件开关
    ENABLE_RATE_LIMIT: bool = Field(False, env="ENABLE_RATE_LIMIT")
    ENABLE_REQUEST_SIZE_LIMIT: bool = Field(True, env="ENABLE_REQUEST_SIZE_LIMIT")
    ENABLE_CACHE: bool = Field(False, env="ENABLE_CACHE")

    # 请求与缓存
    MAX_JSON_SIZE: int = Field(5 * 1024 * 1024, env="MAX_JSON_SIZE")
    MAX_FILE_SIZE: int = Field(50 * 1024 * 1024, env="MAX_FILE_SIZE")
    CACHE_DEFAULT_TTL: int = Field(300, env="CACHE_DEFAULT_TTL")
    CACHE_ENABLED_METHODS: List[str] = Field(default_factory=lambda: ["GET"], env="CACHE_ENABLED_METHODS")
    CACHE_TTL: int = Field(3600, env="CACHE_TTL")
    CACHE_API_RESPONSE_TTL: int = Field(300, env="CACHE_API_RESPONSE_TTL")
    CACHE_JOB_STATUS_TTL: int = Field(86400, env="CACHE_JOB_STATUS_TTL")  # 24小时

    @validator("CACHE_ENABLED_METHODS", pre=True)
    def split_cache_methods(cls, v: Union[str, List[str]]) -> List[str]:
        return _split_comma_separated(v)

    # 上传
    MAX_FILE_SIZE_MB: int = Field(50, env="MAX_FILE_SIZE_MB")
    ALLOWED_FILE_EXTENSIONS: List[str] = Field(
        default_factory=lambda: [".pdf", ".doc", ".docx", ".txt", ".csv", ".xlsx", ".xls", ".json", ".xml"],
        env="ALLOWED_FILE_EXTENSIONS",
    )

    @validator("ALLOWED_FILE_EXTENSIONS", pre=True)
    def split_allowed_extensions(cls, v: Union[str, List[str]]) -> List[str]:
        return _split_comma_separated(v)

    # ==================== AI/ML 服务配置 ====================
    # BGE-M3 嵌入模型
    BGE_M3_API_URL: str = Field("http://localhost:8002/v1/embeddings", env="BGE_M3_API_URL")
    BGE_M3_MODEL_NAME: str = Field("BAAI/bge-m3", env="BGE_M3_MODEL_NAME")
    BGE_M3_TOKENIZER_NAME: str = Field("BAAI/bge-m3", env="BGE_M3_TOKENIZER_NAME")
    
    # Reranker 重排序服务
    RERANKER_API_URL: str = Field("http://localhost:8003/v1/rerank", env="RERANKER_API_URL")
    
    # DOTS OCR 服务
    DOTS_OCR_ENDPOINT: str = Field("http://localhost:8001/v1/chat/completions", env="DOTS_OCR_ENDPOINT")
    
    # 本地模型 GPU 配置（不影响上述 Docker 部署的服务）
    # 用于 Tokenizer、PaddleOCR、TagGenerator 等本地运行的模型
    LOCAL_MODEL_GPU_DEVICE: int = Field(3, env="LOCAL_MODEL_GPU_DEVICE")

    # ==================== 外部服务（暂未启用） ====================
    # Qwen3-8B API
    QWEN3_8B_API_URL: str = Field("http://localhost:80/llm/qwen8b/v1", env="QWEN3_8B_API_URL")
    QWEN3_5_27B_API_URL: str = Field("http://localhost:80/llm/qwen35b/v1", env="QWEN3_5_27B_API_URL")

    # N8N 工作流引擎
    N8N_BASE_URL: str = Field("http://localhost:5678", env="N8N_BASE_URL")
    N8N_API_KEY: Optional[str] = Field(default=None, env="N8N_API_KEY")
    
    # Dify AI 平台
    DIFY_BASE_URL: str = Field("http://localhost:80", env="DIFY_BASE_URL")
    DIFY_API_KEY: Optional[str] = Field(default=None, env="DIFY_API_KEY")
    
    # RAGFlow 知识库
    RAGFLOW_BASE_URL: str = Field("http://localhost:9380", env="RAGFLOW_BASE_URL")
    RAGFLOW_API_KEY: Optional[str] = Field(default=None, env="RAGFLOW_API_KEY")
    RAGFLOW_DATASET_ID: Optional[str] = Field(default=None, env="RAGFLOW_DATASET_ID")
    
    # Superset 数据可视化
    SUPERSET_BASE_URL: str = Field("http://localhost:8088", env="SUPERSET_BASE_URL")
    SUPERSET_USERNAME: str = Field("admin", env="SUPERSET_USERNAME")
    SUPERSET_PASSWORD: str = Field("admin", env="SUPERSET_PASSWORD")
    SUPERSET_DATABASE_ID: int = Field(1, env="SUPERSET_DATABASE_ID")
    SUPERSET_GUEST_TOKEN_SECRET: str = Field("your-superset-guest-token-secret", env="SUPERSET_GUEST_TOKEN_SECRET")
    SUPERSET_CSRF_TOKEN_TIMEOUT: int = Field(3600, env="SUPERSET_CSRF_TOKEN_TIMEOUT")
    SUPERSET_CACHE_DEFAULT_TIMEOUT: int = Field(300, env="SUPERSET_CACHE_DEFAULT_TIMEOUT")
    
    # DataHub 元数据管理
    DATAHUB_GMS_URL: str = Field("http://localhost:8080", env="DATAHUB_GMS_URL")
    DATAHUB_GMS_TOKEN: Optional[str] = Field(default=None, env="DATAHUB_GMS_TOKEN")
    DATAHUB_KAFKA_BOOTSTRAP_SERVERS: str = Field("localhost:9092", env="DATAHUB_KAFKA_BOOTSTRAP_SERVERS")
    DATAHUB_SCHEMA_REGISTRY_URL: str = Field("http://localhost:8081", env="DATAHUB_SCHEMA_REGISTRY_URL")

    # 日志 & 监控
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    LOG_FORMAT: str = Field("%(asctime)s - %(name)s - %(levelname)s - %(message)s", env="LOG_FORMAT")
    LOG_FILE: Optional[str] = Field(default=None, env="LOG_FILE")
    ENABLE_METRICS: bool = Field(True, env="ENABLE_METRICS")
    METRICS_PORT: int = Field(9090, env="METRICS_PORT")
    ENABLE_MONITORING: bool = Field(True, env="ENABLE_MONITORING")
    MONITORING_INTERVAL: int = Field(60, env="MONITORING_INTERVAL")
    ENABLE_PROMETHEUS: bool = Field(True, env="ENABLE_PROMETHEUS")
    ENABLE_HEALTH_CHECK: bool = Field(True, env="ENABLE_HEALTH_CHECK")

    CHAT_API_KEY: str = Field("change_me_chat_api_key", env="CHAT_API_KEY")

    @field_validator(
        "SECRET_KEY",
        "INTERNAL_API_KEY",
        "CHAT_API_KEY",
        "POSTGRES_PASSWORD",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        mode="after",
    )
    def validate_sensitive_values(cls, v: str, info: ValidationInfo):
        """生产环境下禁止使用占位符或弱默认敏感配置。"""
        env = str((info.data or {}).get("ENVIRONMENT", "development")).lower()
        field_name = getattr(info, "field_name", "敏感配置")

        if not v or not str(v).strip():
            raise ValueError(f"{field_name} 不能为空")

        if env in {"production", "prod"} and _is_insecure_value(v):
            raise ValueError(f"{field_name} 使用了不安全默认值，请通过环境变量覆盖")

        return v

    @validator("BOOTSTRAP_SUPERUSER_PASSWORD")
    def validate_bootstrap_superuser_password(cls, v: Optional[str], values):
        """生产环境禁用弱引导密码。"""
        if v is None:
            return v

        env = str(values.get("ENVIRONMENT", "development")).lower()
        if env in {"production", "prod"} and _is_insecure_value(v):
            raise ValueError("BOOTSTRAP_SUPERUSER_PASSWORD 使用了不安全默认值")
        return v

    # 开发模式
    RELOAD: bool = Field(False, env="RELOAD")

    @validator("RELOAD", pre=True)
    def set_reload_for_dev(cls, v, values):
        if values.get("ENVIRONMENT") == "development":
            return True
        return v

    class Config:
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        case_sensitive = True
        extra = "ignore"


settings = Settings()
