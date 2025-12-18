"""
日志配置中心
"""
import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings


LOG_LEVEL = settings.LOG_LEVEL.upper()
BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _file_handler(filename: str) -> Dict[str, Any]:
    target = LOG_DIR / filename
    return {
        "formatter": "plain",
        "class": "logging.FileHandler",
        "filename": str(target),
        "mode": "a",
        "encoding": "utf-8",
    }


def _build_logging_config() -> Dict[str, Any]:
    """构建 logging.dictConfig 所需的配置结构。"""
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(asctime)s | %(name)s | %(message)s",
                "use_colors": True,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": True,
            },
            "plain": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
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
            "plain": {
                "formatter": "plain",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "app": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
            "app.database": {"handlers": ["plain"], "level": LOG_LEVEL, "propagate": False},
            "app.requests": {"handlers": ["plain"], "level": LOG_LEVEL, "propagate": False},
            "app.security": {"handlers": ["plain"], "level": LOG_LEVEL, "propagate": False},
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            # 第三方库日志级别控制（减少噪音）
            "pdfminer": {"handlers": ["default"], "level": "ERROR", "propagate": False},
            "pdfminer.pdffont": {"handlers": ["default"], "level": "ERROR", "propagate": False},
            "PIL": {"handlers": ["default"], "level": "ERROR", "propagate": False},
            "matplotlib": {"handlers": ["default"], "level": "ERROR", "propagate": False},
        },
    }
    config["handlers"]["app_file"] = _file_handler("app.log")
    config["handlers"]["database_file"] = _file_handler("database.log")
    config["handlers"]["requests_file"] = _file_handler("requests.log")
    config["handlers"]["security_file"] = _file_handler("security.log")

    config["loggers"]["app"]["handlers"].append("app_file")
    config["loggers"]["app.database"]["handlers"].append("database_file")
    config["loggers"]["app.requests"]["handlers"].append("requests_file")
    config["loggers"]["app.security"]["handlers"].append("security_file")
    return config


def setup_logging():
    """初始化全局日志配置。"""
    logging.config.dictConfig(_build_logging_config())


def get_logger(name: str) -> logging.Logger:
    """按照 app.xxx 规则获取命名 logger。"""
    return logging.getLogger(f"app.{name}")


request_logger = logging.getLogger("app.requests")
security_logger = logging.getLogger("app.security")
database_logger = logging.getLogger("app.database")
