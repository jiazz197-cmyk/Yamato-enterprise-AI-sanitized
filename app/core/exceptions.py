"""
自定义异常类
"""
from typing import Any, Dict, Optional


class APIException(Exception):
    """API自定义异常基类"""

    def __init__(
            self,
            message: str,
            status_code: int = 400,
            error_code: str = "API_ERROR",
            details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details
        super().__init__(self.message)


class ValidationError(APIException):
    """数据验证错误"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details
        )


class AuthenticationError(APIException):
    """认证错误"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            status_code=401,
            error_code="AUTHENTICATION_ERROR"
        )


class AuthorizationError(APIException):
    """授权错误"""

    def __init__(self, message: str = "Access denied"):
        super().__init__(
            message=message,
            status_code=403,
            error_code="AUTHORIZATION_ERROR"
        )


class NotFoundError(APIException):
    """资源不存在错误"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            message=message,
            status_code=404,
            error_code="NOT_FOUND"
        )


class ConflictError(APIException):
    """资源冲突错误"""

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(
            message=message,
            status_code=409,
            error_code="CONFLICT_ERROR"
        )


class ExternalServiceError(APIException):
    """外部服务错误"""

    def __init__(self, service_name: str, message: str = "External service error"):
        super().__init__(
            message=f"{service_name}: {message}",
            status_code=502,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service_name}
        )


class RateLimitError(APIException):
    """限流错误"""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(
            message=message,
            status_code=429,
            error_code="RATE_LIMIT_EXCEEDED"
        )


class DatabaseError(APIException):
    """数据库错误"""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(
            message=message,
            status_code=500,
            error_code="DATABASE_ERROR"
        )


class FileUploadError(APIException):
    """文件上传错误"""

    def __init__(self, message: str = "File upload failed"):
        super().__init__(
            message=message,
            status_code=400,
            error_code="FILE_UPLOAD_ERROR"
        )


class ProcessingError(APIException):
    """数据处理错误"""

    def __init__(self, message: str = "Data processing failed"):
        super().__init__(
            message=message,
            status_code=422,
            error_code="PROCESSING_ERROR"
        )
