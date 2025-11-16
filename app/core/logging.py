"""
日志配置模块
"""
import logging.config
import sys

import logging
from app.core.config import settings

LOG_LEVEL = settings.LOG_LEVEL.upper() if hasattr(settings, 'LOG_LEVEL') else "INFO"


def setup_logging():
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(asctime)s - %(name)s - %(message)s",
                "use_colors": True,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": True,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": sys.stderr,
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "app": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO", "handlers": ["default"], "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
    logging.config.dictConfig(logging_config)


# 全局 logger，所有模块都从这里导入。
# uvicorn 将负责配置这个 logger 的输出。
logger = logging.getLogger("app")


class LoggerMixin:
    """日志混入类，为其他类提供logger属性"""

    @property
    def logger(self) -> logging.Logger:
        """获取当前类的logger"""
        return logging.getLogger(f"app.{self.__class__.__module__}.{self.__class__.__name__}")


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的logger"""
    return logging.getLogger(f"app.{name}")


# 请求日志中间件使用的logger
request_logger = logging.getLogger("app.requests")
security_logger = logging.getLogger("app.security")

# 配置全局日志格式和级别
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

database_logger = logging.getLogger("app.database")
