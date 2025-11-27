"""
全局异常定义
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class APIException(Exception):
    """API 异常基类，提供统一的错误结构。"""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_code: str = "API_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "message": self.message,
            "error_code": self.error_code,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(APIException):
    """参数或数据校验失败。"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=422, error_code="VALIDATION_ERROR", details=details)


class NotFoundError(APIException):
    """资源不存在。"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404, error_code="NOT_FOUND")


class ConflictError(APIException):
    """资源冲突。"""

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message, status_code=409, error_code="CONFLICT_ERROR")


class ExternalServiceError(APIException):
    """外部服务调用失败。"""

    def __init__(self, service_name: str, message: str = "External service error"):
        super().__init__(
            message=f"{service_name}: {message}",
            status_code=502,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service_name},
        )


class RateLimitError(APIException):
    """命中限流策略。"""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429, error_code="RATE_LIMIT_EXCEEDED")


class DatabaseError(APIException):
    """数据库操作失败。"""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(message, status_code=500, error_code="DATABASE_ERROR")


class FileUploadError(APIException):
    """文件上传失败。"""

    def __init__(self, message: str = "File upload failed"):
        super().__init__(message, status_code=400, error_code="FILE_UPLOAD_ERROR")


class ProcessingError(APIException):
    """数据处理失败。"""

    def __init__(self, message: str = "Data processing failed"):
        super().__init__(message, status_code=422, error_code="PROCESSING_ERROR")
