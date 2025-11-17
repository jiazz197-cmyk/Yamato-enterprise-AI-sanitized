"""
应用配置管理
"""
import os
import secrets
from pathlib import Path
from typing import List, Optional, Union, Any

from pydantic import validator
from pydantic_settings import BaseSettings

from dotenv import load_dotenv
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
sys.path.insert(0, project_root)

load_dotenv()

class Settings(BaseSettings):
    """应用配置类"""

    # 基础配置
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "AI Data Tool")
    VERSION: str = os.getenv("VERSION", "1.0.0")
    DESCRIPTION: str = os.getenv("DESCRIPTION", "AI数据工具后端API服务")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "True") == "True"
    API_V1_STR: str = os.getenv("API_V1_STR", "/api/v1")

    # 服务器配置
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    ALLOWED_HOSTS: List[str] = os.getenv("ALLOWED_HOSTS", "*").split(",")

    # CORS配置
    # BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # 数据库配置
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "know_analy-pgvector")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "change_me_pg_password")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "postgres")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    SQLALCHEMY_DATABASE_URI: Optional[str] = os.getenv("SQLALCHEMY_DATABASE_URI")

    @validator("SQLALCHEMY_DATABASE_URI", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> Any:
        if isinstance(v, str):
            return v
        return f"postgresql://{values.get('POSTGRES_USER')}:{values.get('POSTGRES_PASSWORD')}@{values.get('POSTGRES_SERVER')}:{values.get('POSTGRES_PORT')}/{values.get('POSTGRES_DB')}"

    # Redis配置
    REDIS_HOST: str = os.getenv("REDIS_HOST", "know_analy-redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = int(os.getenv("REDIS_DB", 0))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://know_analy-redis:6379/0")

    REDIS_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", 10))

    @property
    def REDIS_CONNECTION_URL(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # MinIO配置
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "know_analy-minio:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "False") == "True"
    MINIO_BUCKET_NAME: str = os.getenv("MINIO_BUCKET_NAME", "knowanaly")


    # 安全配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))  # 分钟
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

    # API Key配置
    INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "your-internal-api-key-change-in-production")

    # 限流配置
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", 100))
    RATE_LIMIT_REQUESTS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_HOUR", 1000))

    # 中间件配置
    ENABLE_RATE_LIMIT: bool = os.getenv("ENABLE_RATE_LIMIT", "False") == "True"  # 临时关闭限流
    ENABLE_REQUEST_SIZE_LIMIT: bool = os.getenv("ENABLE_REQUEST_SIZE_LIMIT", "True") == "True"
    ENABLE_CACHE: bool = os.getenv("ENABLE_CACHE", "False") == "True"  # 临时禁用缓存

    # 限流配置
    RATE_LIMIT_AUTH: int = int(os.getenv("RATE_LIMIT_AUTH", 100))
    RATE_LIMIT_ANON: int = int(os.getenv("RATE_LIMIT_ANON", 20))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", 60))

    # 请求大小限制
    MAX_JSON_SIZE: int = int(os.getenv("MAX_JSON_SIZE", 5 * 1024 * 1024))
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", 50 * 1024 * 1024))

    # 缓存配置
    CACHE_DEFAULT_TTL: int = int(os.getenv("CACHE_DEFAULT_TTL", 300))
    CACHE_ENABLED_METHODS: List[str] = os.getenv("CACHE_ENABLED_METHODS", "GET").split(",")

    # 文件上传配置
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", 50))
    ALLOWED_FILE_EXTENSIONS: List[str] = os.getenv("ALLOWED_FILE_EXTENSIONS",
                                                   ".pdf,.doc,.docx,.txt,.csv,.xlsx,.xls,.json,.xml").split(",")

    # 外部服务配置
    # n8n配置
    N8N_BASE_URL: str = os.getenv("N8N_BASE_URL", "http://localhost:5678")
    N8N_API_KEY: Optional[str] = os.getenv("N8N_API_KEY")

    # Dify配置
    DIFY_BASE_URL: str = os.getenv("DIFY_BASE_URL", "http://localhost:3000")
    DIFY_API_KEY: Optional[str] = os.getenv("DIFY_API_KEY")

    # RagFlow配置
    RAGFLOW_BASE_URL: str = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380")
    RAGFLOW_API_KEY: Optional[str] = os.getenv("RAGFLOW_API_KEY")
    RAGFLOW_DATASET_ID: Optional[str] = os.getenv("RAGFLOW_DATASET_ID")

    # Superset配置
    SUPERSET_BASE_URL: str = os.getenv("SUPERSET_BASE_URL", "http://localhost:8088")
    SUPERSET_USERNAME: str = os.getenv("SUPERSET_USERNAME", "admin")
    SUPERSET_PASSWORD: str = os.getenv("SUPERSET_PASSWORD", "admin")
    SUPERSET_DATABASE_ID: int = int(os.getenv("SUPERSET_DATABASE_ID", 1))
    SUPERSET_GUEST_TOKEN_SECRET: str = os.getenv("SUPERSET_GUEST_TOKEN_SECRET", "your-superset-guest-token-secret")
    SUPERSET_CSRF_TOKEN_TIMEOUT: int = int(os.getenv("SUPERSET_CSRF_TOKEN_TIMEOUT", 3600))
    SUPERSET_CACHE_DEFAULT_TIMEOUT: int = int(os.getenv("SUPERSET_CACHE_DEFAULT_TIMEOUT", 300))

    # DataHub配置
    DATAHUB_GMS_URL: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    DATAHUB_GMS_TOKEN: Optional[str] = os.getenv("DATAHUB_GMS_TOKEN")
    DATAHUB_KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("DATAHUB_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    DATAHUB_SCHEMA_REGISTRY_URL: str = os.getenv("DATAHUB_SCHEMA_REGISTRY_URL", "http://localhost:8081")

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE")

    # 监控配置
    ENABLE_METRICS: bool = os.getenv("ENABLE_METRICS", "True") == "True"
    METRICS_PORT: int = int(os.getenv("METRICS_PORT", 9090))

    # 开发配置
    RELOAD: bool = os.getenv("RELOAD", "False") == "True"

    # 监控设置
    ENABLE_MONITORING: bool = os.getenv("ENABLE_MONITORING", "True") == "True"
    MONITORING_INTERVAL: int = int(os.getenv("MONITORING_INTERVAL", 60))
    ENABLE_PROMETHEUS: bool = os.getenv("ENABLE_PROMETHEUS", "True") == "True"
    ENABLE_HEALTH_CHECK: bool = os.getenv("ENABLE_HEALTH_CHECK", "True") == "True"

    # 缓存设置
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", 3600))

    @validator("RELOAD", pre=True)
    def set_reload_for_dev(cls, v, values):
        if values.get("ENVIRONMENT") == "development":
            return True
        return v

    class Config:
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        case_sensitive = True
        extra = "ignore"  # 忽略额外字段

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


# 创建全局配置实例
settings = Settings()
