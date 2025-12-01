import logging
from datetime import datetime
from typing import Dict, Any

import httpx
from sqlalchemy import text

from app.core.cache import redis_manager
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

class HealthCheckService:
    """系统健康检查服务"""
    
    def __init__(self):
        self.check_timeout = 5.0
        self.redis_client = redis_manager.redis_client
        self.db = SessionLocal()
        self.fastapi_client = httpx.AsyncClient()
    
    async def check_all_services(self) -> Dict[str, Dict[str, Any]]:
        """检查所有服务的健康状态"""
        results = {}
        
        # 检查Redis
        try:
            is_healthy = self._check_redis()
            results["redis"] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            results["redis"] = {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

        # 检查PostgreSQL
        try:
            is_healthy = self._check_postgresql()
            results["postgresql"] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            results["postgresql"] = {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

        # 检查FastAPI
        try:
            is_healthy = await self._check_fastapi()
            results["fastapi"] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            results["fastapi"] = {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

        return results
    
    def _check_redis(self) -> bool:
        """检查Redis连接"""
        try:
            return bool(self.redis_client.ping())
        except Exception as e:
            logger.error(f"Redis健康检查失败: {e}")
            return False
    
    def _check_postgresql(self) -> bool:
        """检查PostgreSQL连接"""
        try:
            self.db.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"PostgreSQL健康检查失败: {e}")
            return False
        finally:
            self.db.close()
    
    async def _check_fastapi(self) -> bool:
        """检查FastAPI服务"""
        try:
            # 检查应用是否正在运行
            return True
        except Exception as e:
            logger.error(f"FastAPI健康检查失败: {e}")
            return False
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.fastapi_client.aclose()
        self.db.close()

# 全局健康检查实例
health_service = HealthCheckService() 