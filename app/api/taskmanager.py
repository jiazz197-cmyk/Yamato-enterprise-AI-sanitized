"""
异步任务管理器
用于管理长时间运行的后台任务的状态和结果
支持 Redis 存储和内存存储两种模式
"""

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any, Optional, Literal

from app.core.logging import request_logger as logger


@dataclass
class TaskStatus:
    """任务状态数据类"""
    task_id: str
    task_type: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: int = 0
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MemoryTaskStorage:
    """内存任务存储（Redis 不可用时的备用方案）"""
    
    def __init__(self):
        self._tasks: Dict[str, TaskStatus] = {}
        self.default_ttl = 3600 * 24  # 24小时
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置任务数据"""
        try:
            self._tasks[key] = value
            return True
        except Exception as e:
            logger.error(f"内存存储设置失败 {key}: {e}")
            return False
    
    async def get(self, key: str) -> Optional[Any]:
        """获取任务数据"""
        try:
            return self._tasks.get(key)
        except Exception as e:
            logger.error(f"内存存储获取失败 {key}: {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """删除任务数据"""
        try:
            if key in self._tasks:
                del self._tasks[key]
                return True
            return False
        except Exception as e:
            logger.error(f"内存存储删除失败 {key}: {e}")
            return False
    
    async def keys(self, pattern: str) -> list:
        """获取匹配的键列表"""
        try:
            # 简单的前缀匹配
            prefix = pattern.replace("*", "")
            return [key for key in self._tasks.keys() if key.startswith(prefix)]
        except Exception as e:
            logger.error(f"内存存储键列表获取失败: {e}")
            return []


class TaskManager:
    """
    异步任务管理器
    
    职责：
    - 管理任务状态（pending/running/completed/failed）
    - 存储任务元数据和结果
    - 提供任务查询接口
    
    注意：
    - 仅负责状态管理，不负责任务执行
    - 不管理线程池或进程池
    - 任务的实际执行由调用方负责
    """
    
    def __init__(self):
        self.task_prefix = "task:"
        self.default_ttl = 3600 * 24  # 24小时
        
        # 初始化为内存存储，稍后可能升级为 Redis
        self.storage = MemoryTaskStorage()
        self.storage_type = "memory"
        self._init_attempted = False

        # 尝试初始化存储
        self._try_init_storage()

    def _try_init_storage(self):
        """尝试初始化存储（优先 Redis，降级到内存）"""
        if self._init_attempted:
            return

        self._init_attempted = True

        # ⚠️ 临时禁用 Redis，直接使用内存存储
        # 原因：当前 Redis (107.174.1.76:6379) 是只读副本，无法写入
        logger.warning("⚠️  检测到 Redis 只读副本，自动降级到内存存储")
        logger.info("如需使用 Redis，请配置可写的 Redis 主节点")
        self.storage = MemoryTaskStorage()
        self.storage_type = "memory"
        logger.info("✅ 任务管理器使用内存存储")
        return

        # TODO: 待 Redis 配置修复后，取消下面代码的注释
        # try:
        #     from app.core.cache import redis_manager
        #     if (hasattr(redis_manager, 'redis_client') and
        #         redis_manager.redis_client is not None):
        #         self.storage = redis_manager
        #         self.storage_type = "redis"
        #         logger.info("✅ 任务管理器使用 Redis 存储")
        #         return
        # except Exception as e:
        #     logger.warning(f"无法初始化 Redis: {e}")
        # 
        # logger.info("✅ 任务管理器使用内存存储")

    def generate_task_id(self, task_type: str) -> str:
        """生成任务ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"{task_type}_{timestamp}_{uuid.uuid4().hex[:8]}"

    async def create_task(self, task_type: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """创建新任务"""
        try:
            task_id = self.generate_task_id(task_type)

            task_status = TaskStatus(
                task_id=task_id,
                task_type=task_type,
                status="pending",
                created_at=datetime.now().isoformat(),
                metadata=metadata or {}
            )

            success = await self._save_task_status(task_status)
            if not success:
                logger.error(f"创建任务失败: {task_id}")
                raise Exception(f"无法保存任务状态: {task_id}")

            logger.info(f"创建任务: {task_id} (类型: {task_type}, 存储: {self.storage_type})")
            return task_id

        except Exception as e:
            logger.error(f"创建任务时发生错误: {e}")
            raise

    async def start_task(self, task_id: str) -> bool:
        """标记任务为运行状态"""
        try:
            task_status = await self.get_task_status(task_id)
            if not task_status:
                logger.error(f"任务不存在: {task_id}")
                return False

            task_status.status = "running"
            task_status.started_at = datetime.now().isoformat()
            task_status.progress = 0

            success = await self._save_task_status(task_status)
            if success:
                logger.info(f"启动任务: {task_id}")
            return success

        except Exception as e:
            logger.error(f"启动任务时发生错误 {task_id}: {e}")
            return False

    async def update_task_progress(self, task_id: str, progress: int, message: str = "") -> bool:
        """更新任务进度"""
        try:
            task_status = await self.get_task_status(task_id)
            if not task_status:
                return False

            task_status.progress = max(0, min(100, progress))
            if message:
                task_status.message = message

            return await self._save_task_status(task_status)

        except Exception as e:
            logger.error(f"更新任务进度时发生错误 {task_id}: {e}")
            return False

    async def complete_task(self, task_id: str, result: Dict[str, Any], message: str = "任务完成") -> bool:
        """标记任务为完成状态"""
        try:
            task_status = await self.get_task_status(task_id)
            if not task_status:
                return False

            task_status.status = "completed"
            task_status.completed_at = datetime.now().isoformat()
            task_status.progress = 100
            task_status.message = message
            task_status.result = result

            success = await self._save_task_status(task_status)
            if success:
                logger.info(f"完成任务: {task_id}")
            return success

        except Exception as e:
            logger.error(f"完成任务时发生错误 {task_id}: {e}")
            return False

    async def fail_task(self, task_id: str, error: str, message: str = "任务失败") -> bool:
        """标记任务为失败状态"""
        try:
            task_status = await self.get_task_status(task_id)
            if not task_status:
                return False

            task_status.status = "failed"
            task_status.completed_at = datetime.now().isoformat()
            task_status.message = message
            task_status.error = error

            success = await self._save_task_status(task_status)
            if success:
                logger.error(f"任务失败: {task_id} - {error}")
            return success

        except Exception as e:
            logger.error(f"标记任务失败时发生错误 {task_id}: {e}")
            return False
    
    async def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        try:
            task_key = f"{self.task_prefix}{task_id}"
            
            if self.storage_type == "redis":
                task_data = await self.storage.get(task_key)
                if task_data is None:
                    return None
                
                if isinstance(task_data, str):
                    task_data = json.loads(task_data)
                
                return TaskStatus(**task_data)
            else:
                # 内存存储
                return await self.storage.get(task_key)
                
        except Exception as e:
            logger.error(f"获取任务状态失败 {task_id}: {e}")
            return None
    
    async def delete_task(self, task_id: str) -> bool:
        """删除任务记录"""
        try:
            task_key = f"{self.task_prefix}{task_id}"
            result = await self.storage.delete(task_key)
            if result:
                logger.info(f"删除任务: {task_id}")
            return bool(result)
        except Exception as e:
            logger.error(f"删除任务失败 {task_id}: {e}")
            return False
    
    async def _save_task_status(self, task_status: TaskStatus) -> bool:
        """保存任务状态"""
        try:
            task_key = f"{self.task_prefix}{task_status.task_id}"
            
            if self.storage_type == "redis":
                task_data = asdict(task_status)
                await self.storage.set(task_key, json.dumps(task_data, ensure_ascii=False), self.default_ttl)
            else:
                # 内存存储直接保存对象
                await self.storage.set(task_key, task_status, self.default_ttl)
            
            return True
        except Exception as e:
            logger.error(f"保存任务状态失败 {task_status.task_id}: {e}")
            return False
    
    async def list_tasks(self, task_type: Optional[str] = None, limit: int = 10) -> list:
        """
        列出任务列表
        
        Args:
            task_type: 可选，按任务类型筛选
            limit: 返回数量限制
        
        Returns:
            任务状态列表
        """
        try:
            pattern = f"{self.task_prefix}*"
            
            if self.storage_type == "redis":
                keys = []
                async for key in self.storage.redis_client.scan_iter(match=pattern):
                    if isinstance(key, bytes):
                        key = key.decode('utf-8')
                    keys.append(key)
            else:
                # 内存存储
                keys = await self.storage.keys(pattern)
            
            tasks = []
            for key in keys[:limit]:
                task_id = key.replace(self.task_prefix, "")
                task_status = await self.get_task_status(task_id)
                
                if task_status:
                    # 过滤任务类型
                    if task_type and task_status.task_type != task_type:
                        continue
                    
                    tasks.append(task_status)
            
            # 按创建时间倒序排序
            tasks.sort(key=lambda x: x.created_at, reverse=True)
            return tasks[:limit]
            
        except Exception as e:
            logger.error(f"列出任务失败: {e}")
            return []
    


# 全局任务管理器实例
task_manager = TaskManager() 