"""
应用配置管理
"""
import os
import secrets
from pathlib import Path
from typing import List, Optional, Union

from pydantic import Field, validator
from pydantic_settings import BaseSettings

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


class Settings(BaseSettings):
    """全局配置对象，统一读取 .env 与环境变量。"""

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

    # 数据库
    POSTGRES_SERVER: str = Field("localhost", env="POSTGRES_SERVER")
    POSTGRES_USER: str = Field("postgres", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("change_me_pg_password", env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field("postgres", env="POSTGRES_DB")
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
    REDIS_HOST: str = Field("localhost", env="REDIS_HOST")
    REDIS_PORT: int = Field(6379, env="REDIS_PORT")
    REDIS_DB: int = Field(0, env="REDIS_DB")
    REDIS_PASSWORD: Optional[str] = Field(default="change_me_redis_password", env="REDIS_PASSWORD")
    REDIS_MAX_CONNECTIONS: int = Field(10, env="REDIS_MAX_CONNECTIONS")

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # MinIO
    MINIO_ENDPOINT: str = Field("localhost:9000", env="MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: str = Field("minioadmin", env="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = Field("minioadmin", env="MINIO_SECRET_KEY")
    MINIO_SECURE: bool = Field(False, env="MINIO_SECURE")
    MINIO_BUCKET_NAME: str = Field("imagebed", env="MINIO_BUCKET_NAME")

    # 安全
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32), env="SECRET_KEY")
    ALGORITHM: str = Field("HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    INTERNAL_API_KEY: str = Field("your-internal-api-key-change-in-production", env="INTERNAL_API_KEY")

    # 限流
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(100, env="RATE_LIMIT_REQUESTS_PER_MINUTE")
    RATE_LIMIT_REQUESTS_PER_HOUR: int = Field(1000, env="RATE_LIMIT_REQUESTS_PER_HOUR")
    RATE_LIMIT_AUTH: int = Field(100, env="RATE_LIMIT_AUTH")
    RATE_LIMIT_ANON: int = Field(20, env="RATE_LIMIT_ANON")
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

    # ==================== 外部服务（暂未启用） ====================
    # N8N 工作流引擎
    N8N_BASE_URL: str = Field("http://localhost:5678", env="N8N_BASE_URL")
    N8N_API_KEY: Optional[str] = Field(default=None, env="N8N_API_KEY")
    
    # Dify AI 平台
    DIFY_BASE_URL: str = Field("http://localhost:3000", env="DIFY_BASE_URL")
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
