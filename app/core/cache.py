"""
Redis 缓存管理器

提供以下功能：
- 通用缓存操作 (get/set/delete)
- API 响应缓存
- 限流计数
- 异步任务状态
- 文件上传进度
- 数据源概览缓存
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional, Dict

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("cache")


class AsyncRedisManager:
    """异步 Redis 管理器，提供缓存、限流、任务状态等功能"""
    def __init__(self):
        kwargs = {
            "max_connections": settings.REDIS_MAX_CONNECTIONS,
            "decode_responses": True,
        }
        if settings.REDIS_PASSWORD:
            kwargs["password"] = settings.REDIS_PASSWORD
        self.redis_client = redis.from_url(settings.REDIS_URL, **kwargs)

    async def _test_connection(self):
        try:
            await self.redis_client.ping()
            logger.info("Redis connection established successfully")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def test_connection(self):
        """测试 Redis 连接是否正常"""
        return await self._test_connection()

    async def close(self):
        """关闭 Redis 连接"""
        try:
            await self.redis_client.aclose()
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

    # ==================== 通用缓存操作 ====================
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if ttl:
                return await self.redis_client.setex(key, ttl, value)
            return await self.redis_client.set(key, value)
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")
            return False

    async def get(self, key: str) -> Optional[Any]:
        try:
            value = await self.redis_client.get(key)
            if value is None:
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None

    async def delete(self, key: str) -> bool:
        try:
            return bool(await self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        deleted = 0
        try:
            async for key in self.redis_client.scan_iter(match=pattern):
                deleted += await self.redis_client.delete(key)
            return deleted
        except Exception as e:
            logger.error(f"Error deleting keys with pattern {pattern}: {e}")
            return deleted

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self.redis_client.exists(key))
        except Exception as e:
            logger.error(f"Error checking existence of key {key}: {e}")
            return False

    async def expire(self, key: str, ttl: int) -> bool:
        try:
            return bool(await self.redis_client.expire(key, ttl))
        except Exception as e:
            logger.error(f"Error setting expiration for key {key}: {e}")
            return False

    # ==================== API响应缓存 ====================
    async def cache_api_response(self, endpoint: str, params: Dict[str, Any], response_data: Any,
                                 ttl: Optional[int] = None) -> bool:
        cache_key = self._generate_api_cache_key(endpoint, params)
        ttl = ttl or settings.CACHE_API_RESPONSE_TTL
        return await self.set(cache_key, response_data, ttl)

    async def get_cached_api_response(self, endpoint: str, params: Dict[str, Any]) -> Optional[Any]:
        cache_key = self._generate_api_cache_key(endpoint, params)
        return await self.get(cache_key)

    async def invalidate_api_cache(self, endpoint: str) -> int:
        pattern = f"api_cache:{endpoint}:*"
        return await self.delete_pattern(pattern)

    def _generate_api_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        return f"api_cache:{endpoint}:{params_hash}"

    # ==================== API限流 ====================
    async def check_rate_limit(self, identifier: str, limit: int, window: int, prefix: str = "rate_limit") -> Dict[
        str, Any]:
        key = f"{prefix}:{identifier}:{window}s"
        try:
            current = await self.redis_client.get(key)
            if current is None:
                await self.redis_client.setex(key, window, 1)
                return {
                    "allowed": True,
                    "current": 1,
                    "limit": limit,
                    "remaining": limit - 1,
                    "reset_time": datetime.utcnow() + timedelta(seconds=window)
                }
            current = int(current)
            if current >= limit:
                ttl = await self.redis_client.ttl(key)
                ttl = ttl if ttl is not None and ttl > 0 else window
                return {
                    "allowed": False,
                    "current": current,
                    "limit": limit,
                    "remaining": 0,
                    "reset_time": datetime.utcnow() + timedelta(seconds=ttl)
                }
            new_count = await self.redis_client.incr(key)
            ttl = await self.redis_client.ttl(key)
            ttl = ttl if ttl is not None and ttl > 0 else window
            return {
                "allowed": True,
                "current": new_count,
                "limit": limit,
                "remaining": limit - new_count,
                "reset_time": datetime.utcnow() + timedelta(seconds=ttl)
            }
        except Exception as e:
            logger.error(f"Error checking rate limit for {identifier}: {e}")
            return {
                "allowed": True,
                "current": 0,
                "limit": limit,
                "remaining": limit,
                "reset_time": datetime.utcnow() + timedelta(seconds=window)
            }

    # ==================== 任务状态缓存 ====================
    async def set_job_status(self, job_id: str, status: str, progress: int = 0,
                             metadata: Optional[Dict[str, Any]] = None, ttl: Optional[int] = None) -> bool:
        job_key = f"job_status:{job_id}"
        job_data = {
            "status": status,
            "progress": progress,
            "updated_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        ttl = ttl or settings.CACHE_JOB_STATUS_TTL
        return await self.set(job_key, job_data, ttl)

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        job_key = f"job_status:{job_id}"
        return await self.get(job_key)

    async def delete_job_status(self, job_id: str) -> bool:
        job_key = f"job_status:{job_id}"
        return await self.delete(job_key)

    # ==================== 数据源概览缓存 ====================
    async def cache_data_source_overview(self, source_id: int, overview_data: Dict[str, Any], ttl: int = 300) -> bool:
        cache_key = f"ds_overview:{source_id}"
        return await self.set(cache_key, overview_data, ttl)

    async def get_cached_data_source_overview(self, source_id: int) -> Optional[Dict[str, Any]]:
        cache_key = f"ds_overview:{source_id}"
        return await self.get(cache_key)

    async def invalidate_data_source_cache(self, source_id: int) -> bool:
        cache_key = f"ds_overview:{source_id}"
        return await self.delete(cache_key)

    # ==================== 文件上传进度 ====================
    async def set_upload_progress(self, file_id: str, total_size: int, uploaded_size: int, status: str = "uploading",
                                  ttl: int = 3600) -> bool:
        progress_key = f"upload_progress:{file_id}"
        progress_data = {
            "total_size": total_size,
            "uploaded_size": uploaded_size,
            "progress": int((uploaded_size / total_size) * 100) if total_size > 0 else 0,
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        return await self.set(progress_key, progress_data, ttl)

    async def get_upload_progress(self, file_id: str) -> Optional[Dict[str, Any]]:
        progress_key = f"upload_progress:{file_id}"
        return await self.get(progress_key)

    async def delete_upload_progress(self, file_id: str) -> bool:
        progress_key = f"upload_progress:{file_id}"
        return await self.delete(progress_key)

    # ==================== 系统统计 ====================
    async def get_redis_stats(self) -> Dict[str, Any]:
        try:
            info = await self.redis_client.info()

            async def _count_keys(match: str) -> int:
                count = 0
                async for _ in self.redis_client.scan_iter(match=match):
                    count += 1
                return count

            cache_stats = {
                "api_cache_keys": await _count_keys("api_cache:*"),
                "rate_limit_keys": await _count_keys("rate_limit:*"),
                "job_status_keys": await _count_keys("job_status:*"),
                "upload_progress_keys": await _count_keys("upload_progress:*"),
                "data_source_keys": await _count_keys("ds_overview:*")
            }
            return {
                "redis_info": {
                    "used_memory": info.get("used_memory"),
                    "used_memory_human": info.get("used_memory_human"),
                    "connected_clients": info.get("connected_clients"),
                    "total_commands_processed": info.get("total_commands_processed"),
                    "keyspace_hits": info.get("keyspace_hits"),
                    "keyspace_misses": info.get("keyspace_misses")
                },
                "cache_stats": cache_stats
            }
        except Exception as e:
            logger.error(f"Error getting Redis stats: {e}")
            return {}


# 全局 Redis 管理器实例
redis_manager = AsyncRedisManager()
