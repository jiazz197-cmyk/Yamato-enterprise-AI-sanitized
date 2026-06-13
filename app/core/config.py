"""从环境变量加载的全局 Settings（单例）。"""
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


def _is_production_env(value: Any) -> bool:
    return str(value or "").strip().lower() in {"production", "prod"}


def _contains_wildcard(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() == "*"
    if isinstance(value, list):
        return "*" in [str(item).strip() for item in value]
    return False


class SingletonModelMeta(ModelMetaclass):
    """Settings 用：双检锁单例，兼容 pydantic BaseSettings。"""
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]


class Settings(BaseSettings, metaclass=SingletonModelMeta):
    """单例配置：字段对应环境变量 / .env。"""

    PROJECT_NAME: str = Field("AI Data Tool", env="PROJECT_NAME")
    VERSION: str = Field("1.0.0", env="VERSION")
    DESCRIPTION: str = Field("AI数据工具后端API服务", env="DESCRIPTION")
    ENVIRONMENT: str = Field("development", env="ENVIRONMENT")
    DEBUG: bool = Field(True, env="DEBUG")
    @validator("DEBUG", pre=True)
    def parse_debug_flag(cls, v: Any):
        """兼容 true/false、dev/prod 等字符串。"""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return v

    API_V1_STR: str = Field("/api/v1", env="API_V1_STR")

    HOST: str = Field("0.0.0.0", env="HOST")
    PORT: int = Field(8000, env="PORT")
    ALLOWED_HOSTS: List[str] = Field(default_factory=lambda: ["*"], env="ALLOWED_HOSTS")
    TRUST_PROXY_HEADERS: bool = Field(False, env="TRUST_PROXY_HEADERS")
    TRUSTED_PROXIES: List[str] = Field(default_factory=list, env="TRUSTED_PROXIES")

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

    @validator("TRUSTED_PROXIES", pre=True)
    def split_trusted_proxies(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @validator("ALLOWED_HOSTS")
    def validate_allowed_hosts_for_production(cls, v: List[str], values):
        if _is_production_env(values.get("ENVIRONMENT")) and _contains_wildcard(v):
            raise ValueError("生产环境禁止使用 ALLOWED_HOSTS=[\"*\"]，请配置明确域名")
        return v

    @validator("BACKEND_CORS_ORIGINS")
    def validate_cors_origins_for_production(cls, v: List[str], values):
        if _is_production_env(values.get("ENVIRONMENT")) and _contains_wildcard(v):
            raise ValueError("生产环境禁止使用 BACKEND_CORS_ORIGINS=[\"*\"]，请配置明确来源")
        return v

    @validator("RETRIEVER_ALLOWED_COLLECTIONS", pre=True)
    def split_retriever_allowed_collections(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    POSTGRES_SERVER: str = Field("127.0.0.1", env="POSTGRES_SERVER")
    POSTGRES_USER: str = Field("pguser", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("change_me_postgres_password", env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field("pgdb", env="POSTGRES_DB")
    POSTGRES_PORT: int = Field(5432, env="POSTGRES_PORT")

    # SQL Server（U8 / PDM）
    U8_SQLSERVER_HOST: str = Field("127.0.0.1", env="U8_SQLSERVER_HOST")
    U8_SQLSERVER_PORT: int = Field(1433, env="U8_SQLSERVER_PORT")
    U8_SQLSERVER_DATABASE: str = Field("UFDATA_CHANGE_ME", env="U8_SQLSERVER_DATABASE")
    U8_SQLSERVER_USER: str = Field("sa", env="U8_SQLSERVER_USER")
    U8_SQLSERVER_PASSWORD: str = Field("change_me_u8_sqlserver_password", env="U8_SQLSERVER_PASSWORD")
    U8_SQLSERVER_ENCRYPT: bool = Field(False, env="U8_SQLSERVER_ENCRYPT")

    PDM_SQLSERVER_HOST: str = Field("127.0.0.1", env="PDM_SQLSERVER_HOST")
    PDM_SQLSERVER_PORT: int = Field(1433, env="PDM_SQLSERVER_PORT")
    PDM_SQLSERVER_DATABASE: str = Field("pdm_change_me", env="PDM_SQLSERVER_DATABASE")
    PDM_SQLSERVER_USER: str = Field("sa", env="PDM_SQLSERVER_USER")
    PDM_SQLSERVER_PASSWORD: str = Field("change_me_pdm_sqlserver_password", env="PDM_SQLSERVER_PASSWORD")
    PDM_SQLSERVER_ENCRYPT: bool = Field(False, env="PDM_SQLSERVER_ENCRYPT")
    # pymssql: query timeout (seconds) and connection/login timeout
    SQLSERVER_QUERY_TIMEOUT_SEC: int = Field(120, ge=1, le=3600, env="SQLSERVER_QUERY_TIMEOUT_SEC")
    SQLSERVER_LOGIN_TIMEOUT_SEC: int = Field(30, ge=1, le=300, env="SQLSERVER_LOGIN_TIMEOUT_SEC")
    SQLSERVER_QUERY_MAX_WORKERS: int = Field(2, ge=1, le=8, env="SQLSERVER_QUERY_MAX_WORKERS")

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

    @property
    def ASYNC_SQLALCHEMY_DATABASE_URI(self) -> str:
        """asyncpg 异步数据库连接串。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:"
            f"{self.POSTGRES_PORT}/"
            f"{self.POSTGRES_DB}"
        )

    REDIS_HOST: str = Field("127.0.0.1", env="REDIS_HOST")
    REDIS_PORT: int = Field(6379, env="REDIS_PORT")
    REDIS_DB: int = Field(0, env="REDIS_DB")
    REDIS_PASSWORD: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    REDIS_MAX_CONNECTIONS: int = Field(10, env="REDIS_MAX_CONNECTIONS")

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # This process connects to MinIO for put_object / bucket (use loopback or published port when API is on the host).
    MINIO_APP_ENDPOINT: str = Field("127.0.0.1:9000", env="MINIO_APP_ENDPOINT")
    # Legacy: presign / anonymous URL fallback when MINIO_PUBLIC_ENDPOINT is unset. Not used for application upload.
    MINIO_ENDPOINT: str = Field("127.0.0.1:9000", env="MINIO_ENDPOINT")
    # Host:port (or full http URL) that other containers (OCR) use to GET objects — presign is signed for this host only.
    MINIO_PUBLIC_ENDPOINT: Optional[str] = Field(default=None, env="MINIO_PUBLIC_ENDPOINT")
    MINIO_ACCESS_KEY: str = Field("change_me_minio_access_key", env="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = Field("change_me_minio_secret_key", env="MINIO_SECRET_KEY")
    MINIO_SECURE: bool = Field(False, env="MINIO_SECURE")
    # Set so minio-py does not call GetBucketLocation on presign; MinIO S3 default is us-east-1
    MINIO_REGION: str = Field("us-east-1", env="MINIO_REGION")
    MINIO_BUCKET_NAME: str = Field("yamatodev", env="MINIO_BUCKET_NAME")
    CLOSING_FORM_IMAGE_PREFIX: str = Field("form_pic", env="CLOSING_FORM_IMAGE_PREFIX")
    # Presigned GetObject for OCR / temp files (replaces bucket-wide anonymous read by default)
    MINIO_PRESIGN_EXPIRES_HOURS: int = Field(12, ge=1, le=168, env="MINIO_PRESIGN_EXPIRES_HOURS")
    # Override TLS for presign only (e.g. internal MINIO_ON https but public http). None = infer from URL or MINIO_SECURE
    MINIO_PRESIGN_SECURE: Optional[bool] = Field(default=None, env="MINIO_PRESIGN_SECURE")
    # Optional: upload temp OCR images to a dedicated bucket (still uses presign, no public policy)
    MINIO_OCR_TEMP_BUCKET: Optional[str] = Field(default=None, env="MINIO_OCR_TEMP_BUCKET")
    # Opt-in only: if True, set anonymous s3:GetObject on MINIO_OCR_ANONYMOUS_BUCKET (never on default bucket)
    MINIO_OCR_ENABLE_ANONYMOUS_BUCKET: bool = Field(False, env="MINIO_OCR_ENABLE_ANONYMOUS_BUCKET")
    MINIO_OCR_ANONYMOUS_BUCKET: Optional[str] = Field(default=None, env="MINIO_OCR_ANONYMOUS_BUCKET")

    OCR_HTTP_CONNECT_TIMEOUT: float = Field(10.0, ge=1.0, le=300.0, env="OCR_HTTP_CONNECT_TIMEOUT")
    OCR_HTTP_READ_TIMEOUT: float = Field(300.0, ge=5.0, le=3600.0, env="OCR_HTTP_READ_TIMEOUT")

    OCR_PDFTEXT_ENABLED: bool = Field(True, env="OCR_PDFTEXT_ENABLED")
    OCR_PDFTEXT_TIMEOUT: int = Field(30, ge=5, le=120, env="OCR_PDFTEXT_TIMEOUT")
    OCR_DOTSOCR_MAX_TOKENS: int = Field(4096, ge=1024, le=16384, env="OCR_DOTSOCR_MAX_TOKENS")

    HTTP_CLIENT_TIMEOUT: float = Field(30.0, env="HTTP_CLIENT_TIMEOUT")
    HTTP_CLIENT_MAX_CONNECTIONS: int = Field(100, env="HTTP_CLIENT_MAX_CONNECTIONS")
    HTTP_CLIENT_MAX_KEEPALIVE: int = Field(20, env="HTTP_CLIENT_MAX_KEEPALIVE")

    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32), env="SECRET_KEY")
    ALGORITHM: str = Field("HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    INTERNAL_API_KEY: str = Field("change_me_internal_api_key", env="INTERNAL_API_KEY")
    RETRIEVER_ALLOWED_COLLECTIONS: List[str] = Field(default_factory=list, env="RETRIEVER_ALLOWED_COLLECTIONS")

    BOOTSTRAP_SUPERUSER_USERNAME: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_USERNAME")
    BOOTSTRAP_SUPERUSER_EMAIL: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_EMAIL")
    BOOTSTRAP_SUPERUSER_PASSWORD: Optional[str] = Field(default=None, env="BOOTSTRAP_SUPERUSER_PASSWORD")

    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(300, env="RATE_LIMIT_REQUESTS_PER_MINUTE")
    RATE_LIMIT_REQUESTS_PER_HOUR: int = Field(3000, env="RATE_LIMIT_REQUESTS_PER_HOUR")
    RATE_LIMIT_AUTH: int = Field(300, env="RATE_LIMIT_AUTH")
    RATE_LIMIT_ANON: int = Field(60, env="RATE_LIMIT_ANON")
    RATE_LIMIT_EXPENSIVE_AUTH: int = Field(60, env="RATE_LIMIT_EXPENSIVE_AUTH")
    RATE_LIMIT_EXPENSIVE_ANON: int = Field(15, env="RATE_LIMIT_EXPENSIVE_ANON")
    RATE_LIMIT_WINDOW: int = Field(60, env="RATE_LIMIT_WINDOW")
    RATE_LIMIT_FAIL_OPEN: bool = Field(True, env="RATE_LIMIT_FAIL_OPEN")
    RATE_LIMIT_REDIS_ERROR_STATUS: int = Field(503, env="RATE_LIMIT_REDIS_ERROR_STATUS")
    WS_MAX_CONNECTIONS_PER_IP: int = Field(20, env="WS_MAX_CONNECTIONS_PER_IP")
    WS_MAX_MESSAGES_PER_MINUTE: int = Field(120, env="WS_MAX_MESSAGES_PER_MINUTE")
    # Cap in-memory per-IP message counter entries to avoid unbounded growth
    WS_MAX_TRACKED_IPS_FOR_COUNTERS: int = Field(2000, ge=100, le=100000, env="WS_MAX_TRACKED_IPS_FOR_COUNTERS")

    # Quotation queue runtime concurrency limits
    QUOTATION_MAX_RUNNING_PER_OWNER: int = Field(2, ge=1, le=20, env="QUOTATION_MAX_RUNNING_PER_OWNER")
    QUOTATION_MAX_RUNNING_PER_IP: int = Field(2, ge=1, le=20, env="QUOTATION_MAX_RUNNING_PER_IP")

    QUOTATION_RETENTION_MAX_TOTAL: int = Field(100, ge=10, le=10000, env="QUOTATION_RETENTION_MAX_TOTAL")
    QUOTATION_RETENTION_TARGET: int = Field(50, ge=1, le=5000, env="QUOTATION_RETENTION_TARGET")
    QUOTATION_RETENTION_INTERVAL_SEC: int = Field(300, ge=60, le=86400, env="QUOTATION_RETENTION_INTERVAL_SEC")
    QUOTATION_AWAITING_APPROVAL_TTL_HOURS: int = Field(24, ge=1, le=168, env="QUOTATION_AWAITING_APPROVAL_TTL_HOURS")

    # Headless document conversion; abort hung soffice processes
    LIBREOFFICE_SUBPROCESS_TIMEOUT_SEC: int = Field(300, ge=30, le=3600, env="LIBREOFFICE_SUBPROCESS_TIMEOUT_SEC")

    ENABLE_RATE_LIMIT: bool = Field(False, env="ENABLE_RATE_LIMIT")
    ENABLE_REQUEST_SIZE_LIMIT: bool = Field(True, env="ENABLE_REQUEST_SIZE_LIMIT")
    ENABLE_CACHE: bool = Field(False, env="ENABLE_CACHE")

    MAX_JSON_SIZE: int = Field(5 * 1024 * 1024, env="MAX_JSON_SIZE")
    MAX_FILE_SIZE: int = Field(50 * 1024 * 1024, env="MAX_FILE_SIZE")
    CACHE_DEFAULT_TTL: int = Field(300, env="CACHE_DEFAULT_TTL")
    CACHE_ENABLED_METHODS: List[str] = Field(default_factory=lambda: ["GET"], env="CACHE_ENABLED_METHODS")
    CACHE_TTL: int = Field(3600, env="CACHE_TTL")
    CACHE_API_RESPONSE_TTL: int = Field(300, env="CACHE_API_RESPONSE_TTL")
    CACHE_JOB_STATUS_TTL: int = Field(86400, env="CACHE_JOB_STATUS_TTL")

    @validator("CACHE_ENABLED_METHODS", pre=True)
    def split_cache_methods(cls, v: Union[str, List[str]]) -> List[str]:
        return _split_comma_separated(v)

    MAX_FILE_SIZE_MB: int = Field(50, env="MAX_FILE_SIZE_MB")
    ALLOWED_FILE_EXTENSIONS: List[str] = Field(
        default_factory=lambda: [".pdf", ".doc", ".docx", ".txt", ".csv", ".xlsx", ".xls", ".json", ".xml"],
        env="ALLOWED_FILE_EXTENSIONS",
    )

    @validator("ALLOWED_FILE_EXTENSIONS", pre=True)
    def split_allowed_extensions(cls, v: Union[str, List[str]]) -> List[str]:
        return _split_comma_separated(v)

    BGE_M3_API_URL: str = Field("http://localhost:8002/v1/embeddings", env="BGE_M3_API_URL")
    BGE_M3_MODEL_NAME: str = Field("BAAI/bge-m3", env="BGE_M3_MODEL_NAME")
    BGE_M3_TOKENIZER_NAME: str = Field("BAAI/bge-m3", env="BGE_M3_TOKENIZER_NAME")
    
    RERANKER_API_URL: str = Field("http://localhost:8003/v1/rerank", env="RERANKER_API_URL")
    
    DOTS_OCR_ENDPOINT: str = Field("http://localhost:8001/v1/chat/completions", env="DOTS_OCR_ENDPOINT")
    
    LOCAL_MODEL_GPU_DEVICE: int = Field(3, env="LOCAL_MODEL_GPU_DEVICE")

    QWEN3_8B_API_URL: str = Field("http://localhost:80/llm/qwen8b/v1", env="QWEN3_8B_API_URL")
    QWEN3_6_35B_API_URL: str = Field(
        "http://localhost:80/llm/qwen36b/v1",
        env="QWEN3_6_35B_API_URL",
        description="OpenAI-compatible API root (…/v1) for Qwen3.6-35B; proxy must target vLLM, not Dify/Next static routes.",
    )
    QWEN3_6_35B_MODEL: str = Field(
        "/models/Qwen3.6-35B-A3B",
        env="QWEN3_6_35B_MODEL",
        description="Served model id (GET /v1/models on the same base as QWEN3_6_35B_API_URL). vLLM often uses path-style ids, not Hub names.",
    )

    N8N_BASE_URL: str = Field("http://localhost:5678", env="N8N_BASE_URL")
    N8N_API_KEY: Optional[str] = Field(default=None, env="N8N_API_KEY")
    
    DIFY_BASE_URL: str = Field("http://localhost:80", env="DIFY_BASE_URL")
    DIFY_API_KEY: Optional[str] = Field(default=None, env="DIFY_API_KEY")
    
    RAGFLOW_BASE_URL: str = Field("http://localhost:9380", env="RAGFLOW_BASE_URL")
    RAGFLOW_API_KEY: Optional[str] = Field(default=None, env="RAGFLOW_API_KEY")
    RAGFLOW_DATASET_ID: Optional[str] = Field(default=None, env="RAGFLOW_DATASET_ID")
    
    SUPERSET_BASE_URL: str = Field("http://localhost:8088", env="SUPERSET_BASE_URL")
    SUPERSET_USERNAME: str = Field("admin", env="SUPERSET_USERNAME")
    SUPERSET_PASSWORD: str = Field("admin", env="SUPERSET_PASSWORD")
    SUPERSET_DATABASE_ID: int = Field(1, env="SUPERSET_DATABASE_ID")
    SUPERSET_GUEST_TOKEN_SECRET: str = Field("your-superset-guest-token-secret", env="SUPERSET_GUEST_TOKEN_SECRET")
    SUPERSET_CSRF_TOKEN_TIMEOUT: int = Field(3600, env="SUPERSET_CSRF_TOKEN_TIMEOUT")
    SUPERSET_CACHE_DEFAULT_TIMEOUT: int = Field(300, env="SUPERSET_CACHE_DEFAULT_TIMEOUT")
    
    DATAHUB_GMS_URL: str = Field("http://localhost:8080", env="DATAHUB_GMS_URL")
    DATAHUB_GMS_TOKEN: Optional[str] = Field(default=None, env="DATAHUB_GMS_TOKEN")
    DATAHUB_KAFKA_BOOTSTRAP_SERVERS: str = Field("localhost:9092", env="DATAHUB_KAFKA_BOOTSTRAP_SERVERS")
    DATAHUB_SCHEMA_REGISTRY_URL: str = Field("http://localhost:8081", env="DATAHUB_SCHEMA_REGISTRY_URL")

    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    LOG_FORMAT: str = Field("%(asctime)s - %(name)s - %(levelname)s - %(message)s", env="LOG_FORMAT")
    LOG_FILE: Optional[str] = Field(default=None, env="LOG_FILE")
    ENABLE_METRICS: bool = Field(True, env="ENABLE_METRICS")
    METRICS_PORT: int = Field(9090, env="METRICS_PORT")
    ENABLE_MONITORING: bool = Field(True, env="ENABLE_MONITORING")
    MONITORING_INTERVAL: int = Field(60, env="MONITORING_INTERVAL")
    ENABLE_PROMETHEUS: bool = Field(True, env="ENABLE_PROMETHEUS")
    ENABLE_HEALTH_CHECK: bool = Field(True, env="ENABLE_HEALTH_CHECK")
    METRICS_REQUIRE_API_KEY: bool = Field(True, env="METRICS_REQUIRE_API_KEY")
    ENABLE_SECURITY_HEADERS: bool = Field(True, env="ENABLE_SECURITY_HEADERS")
    ENABLE_HSTS: bool = Field(True, env="ENABLE_HSTS")
    HSTS_MAX_AGE: int = Field(31536000, env="HSTS_MAX_AGE")

    CHAT_API_KEY: str = Field("change_me_chat_api_key", env="CHAT_API_KEY")

    @field_validator(
        "SECRET_KEY",
        "INTERNAL_API_KEY",
        "CHAT_API_KEY",
        "POSTGRES_PASSWORD",
        "U8_SQLSERVER_PASSWORD",
        "PDM_SQLSERVER_PASSWORD",
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

    @validator("ENABLE_RATE_LIMIT")
    def validate_rate_limit_required_in_production(cls, v: bool, values):
        if _is_production_env(values.get("ENVIRONMENT")) and not v:
            raise ValueError("生产环境必须启用 ENABLE_RATE_LIMIT")
        return v

    @validator("RATE_LIMIT_REDIS_ERROR_STATUS")
    def validate_rate_limit_redis_error_status(cls, v: int):
        if v not in {429, 503}:
            raise ValueError("RATE_LIMIT_REDIS_ERROR_STATUS 仅支持 429 或 503")
        return v

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
