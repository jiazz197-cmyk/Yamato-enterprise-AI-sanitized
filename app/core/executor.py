"""
线程池执行器管理模块
提供全局线程池管理、任务跟踪和协作式取消机制

⚠️ 重要说明：
1. Python 无法强制杀死线程，所有取消都是"协作式"的
2. 后台任务必须主动检查 is_task_cancelled() 并退出
3. future.cancel() 只能取消未开始的任务
4. task_id 必须全局唯一（建议使用 UUID）
"""
import inspect
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, Optional, Callable, Any
from functools import wraps

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("executor")

# Python 版本检查（shutdown timeout 需要 3.9+）
PYTHON_39_PLUS = sys.version_info >= (3, 9)


class CancellationToken:
    """
    取消令牌 - 用于协作式任务取消
    
    ⚠️ 推荐用法：
        def my_task(token: CancellationToken):
            for i in range(1000):
                if token.is_cancelled():  # ✅ 直接用 token，无锁开销
                    logger.info("任务被取消")
                    return
                # do work...
    
    ❌ 不推荐（有锁竞争）：
        if executor_manager.is_task_cancelled(task_id):  # 每次调用需要锁
            return
    """
    def __init__(self):
        self._event = threading.Event()
    
    def cancel(self):
        """设置取消标志"""
        self._event.set()
    
    def is_cancelled(self) -> bool:
        """检查是否已取消（无锁，高性能）"""
        return self._event.is_set()


def cancellable(fn: Callable) -> Callable:
    """
    装饰器：标记函数接受 CancellationToken
    
    Usage:
        @cancellable
        def my_task(token: CancellationToken, file_path: str):
            while not token.is_cancelled():
                process(file_path)
        
        executor_manager.submit_task("task_1", my_task, file_path="/path")
    
    Note:
        这是可选的，主要用于：
        1. 代码可读性（明确函数是可取消的）
        2. IDE 类型提示
        3. 文档生成
    """
    @wraps(fn)
    def wrapper(token: CancellationToken, *args, **kwargs):
        return fn(token, *args, **kwargs)
    
    # 标记函数已装饰（用于后续验证）
    wrapper._is_cancellable = True
    return wrapper


class ExecutorManager:
    """
    线程池执行器管理器（单例模式）
    
    职责：
    - 管理 ThreadPoolExecutor 生命周期
    - 为每个任务创建 CancellationToken
    - 跟踪 Future 对象
    - 提供协作式取消机制
    
    ⚠️ 关键设计：
    1. 单例只初始化一次（在 __new__ 中完成）
    2. 任务函数必须接受 CancellationToken 参数
    3. 任务内部需主动检查 token.is_cancelled()
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # ✅ 在 __new__ 中初始化，确保只执行一次
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化（只执行一次）"""
        if self._initialized:
            return
        
        self._max_workers = getattr(settings, 'EXECUTOR_MAX_WORKERS', 4)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="bg_executor_"
        )
        # ✅ 任务历史：保留 Future 供查询结果，不删除
        self._task_futures: Dict[str, Future] = {}
        # ✅ 取消令牌：任务完成后可删除（节省内存）
        self._cancellation_tokens: Dict[str, CancellationToken] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        
        self._initialized = True
        logger.info(f"初始化全局线程池: {self._max_workers} workers")
    
    @property
    def executor(self) -> ThreadPoolExecutor:
        """获取线程池实例"""
        if self._shutdown:
            raise RuntimeError("线程池已关闭")
        return self._executor
    
    def submit_task(
        self, 
        task_id: str, 
        fn: Callable[[CancellationToken, Any], Any],
        *args, 
        **kwargs
    ) -> Future:
        """
        提交任务到线程池（自动注入 CancellationToken）
        
        Args:
            task_id: 任务唯一标识（必须全局唯一，建议用 UUID）
            fn: 要执行的函数（第一个参数必须是 CancellationToken）
            *args, **kwargs: 函数的其他参数
        
        Returns:
            Future 对象
        
        Raises:
            ValueError: task_id 已存在
            TypeError: 函数签名不符合要求
            RuntimeError: 线程池已关闭
        
        Example:
            ```python
            def my_task(token: CancellationToken, file_path: str):
                for i in range(100):
                    if token.is_cancelled():
                        logger.info("任务被取消")
                        return
                    # 处理文件...
            
            executor_manager.submit_task("task_1", my_task, file_path="/path/to/file")
            ```
        """
        with self._lock:
            if self._shutdown:
                raise RuntimeError("线程池已关闭，无法提交新任务")
            
            # 🐛 修复1：防止 task_id 重复
            if task_id in self._task_futures:
                raise ValueError(f"task_id '{task_id}' 已存在，请使用唯一标识（如 UUID）")
            
            # 🐛 修复2：验证函数签名（可选，开发模式启用）
            if getattr(settings, 'DEBUG', False):
                try:
                    sig = inspect.signature(fn)
                    params = list(sig.parameters.values())
                    
                    # 检查第一个参数是否存在
                    if not params:
                        raise TypeError(
                            f"函数 {fn.__name__} 必须接受至少一个参数（CancellationToken）"
                        )
                    
                    # 提示：参数名建议为 'token'
                    first_param = params[0]
                    if first_param.name != 'token':
                        logger.warning(
                            f"函数 {fn.__name__} 第一个参数名为 '{first_param.name}'，"
                            f"建议命名为 'token' 以提高可读性"
                        )
                        
                except Exception as e:
                    logger.debug(f"签名验证跳过: {e}")
            
            # ✅ 创建取消令牌
            token = CancellationToken()
            self._cancellation_tokens[task_id] = token
            
            # ✅ 包装函数，自动注入 token 作为第一个参数
            def wrapped_fn():
                try:
                    return fn(token, *args, **kwargs)
                except KeyboardInterrupt:
                    # 🐛 修复1：正确处理 KeyboardInterrupt（优雅退出）
                    logger.warning(f"任务 {task_id} 收到 KeyboardInterrupt，正在退出")
                    token.cancel()  # 设置取消标志
                    raise  # 重新抛出，让线程池知道
                except SystemExit:
                    # 处理 SystemExit（程序退出）
                    logger.warning(f"任务 {task_id} 收到 SystemExit，正在退出")
                    raise
                except Exception as e:
                    logger.error(f"任务 {task_id} 执行失败: {e}", exc_info=True)
                    raise
            
            # 提交到线程池
            future = self._executor.submit(wrapped_fn)
            self._task_futures[task_id] = future
            
            # ✅ 改进的清理回调（保留任务历史）
            def cleanup_callback(f):
                # 🌟 最佳实践：只清理 token，保留 future（用于查询结果）
                # 🐛 修复：非阻塞获取锁，避免嵌套锁死锁
                acquired = self._lock.acquire(blocking=False)
                if not acquired:
                    # 无法立即获取锁，延迟清理（通过线程池重新提交）
                    logger.debug(f"任务 {task_id} token 清理延迟（锁被占用）")
                    try:
                        self._executor.submit(lambda: self._delayed_cleanup(task_id))
                    except:
                        # 线程池已关闭或其他异常，忽略
                        pass
                    return
                
                try:
                    # ✅ 只删除 token（节省内存），保留 Future（供查询结果）
                    self._cancellation_tokens.pop(task_id, None)
                    logger.debug(f"任务 {task_id} token 已清理（Future 保留用于查询）")
                except Exception as e:
                    logger.error(f"清理任务 {task_id} token 失败: {e}")
                finally:
                    self._lock.release()
            
            future.add_done_callback(cleanup_callback)
            logger.debug(f"提交任务到线程池: {task_id}")
            return future
    
    def _delayed_cleanup(self, task_id: str):
        """
        延迟清理任务 token（用于处理锁竞争）
        
        ⚠️ 注意：只清理 token，不删除 Future
        Future 需要保留以供 wait_task() 和 get_task_future() 使用
        """
        try:
            with self._lock:
                self._cancellation_tokens.pop(task_id, None)
                logger.debug(f"任务 {task_id} token 延迟清理完成")
        except Exception as e:
            logger.error(f"延迟清理任务 {task_id} token 失败: {e}")
    
    def is_task_cancelled(self, task_id: str) -> bool:
        """
        检查任务是否被取消（供后台任务主动检查）
        
        ⚠️ 性能提示：
        - 推荐：直接使用 token.is_cancelled() ✅ 无锁，高性能
        - 备选：使用此方法 ⚠️ 有锁竞争，适合无法传递 token 的场景
        
        Args:
            task_id: 任务ID
        
        Returns:
            是否被取消
        
        Example:
            ```python
            # ✅ 推荐方式（函数内部）
            def my_task(token: CancellationToken):
                if token.is_cancelled():
                    return
            
            # ⚠️ 备选方式（无法访问 token 时）
            if executor_manager.is_task_cancelled("task_id"):
                return
            ```
        """
        with self._lock:
            token = self._cancellation_tokens.get(task_id)
            return token.is_cancelled() if token else False
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务（协作式取消）
        
        工作原理：
        1. 如果任务未开始：调用 future.cancel()，任务不会执行 ✅
        2. 如果任务正在运行：设置 CancellationToken，任务需主动检查 ⚠️
        3. 如果任务已完成：无法取消 ❌
        
        Returns:
            True - 成功设置取消标志（不代表任务已停止）
            False - 任务不存在或已完成
        
        Note:
            此方法是线程安全的，可以从任意线程调用
        """
        with self._lock:
            future = self._task_futures.get(task_id)
            token = self._cancellation_tokens.get(task_id)
            
            if not future or not token:
                logger.warning(f"无法取消任务 {task_id}：任务不存在")
                return False
            
            # 🐛 修复3：先设置取消标志，再尝试取消 future
            # 避免 cleanup_callback 和 cancel_task 的竞态条件
            # 即使 cleanup 先执行，token 仍然被正确设置
            token.cancel()
            
            # ✅ 1. 尝试取消未开始的任务
            if not future.done():
                cancelled = future.cancel()
                if cancelled:
                    logger.info(f"成功取消未开始的任务: {task_id}")
                    return True
                
                # ✅ 2. 任务已经开始执行
                logger.info(f"任务 {task_id} 正在运行，已设置取消标志（需任务主动检查）")
                return True
            
            # ❌ 3. 任务已完成（但我们已经设置了标志，为了一致性）
            logger.warning(f"任务 {task_id} 已完成，无法取消")
            return False
    
    def wait_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        等待任务完成并获取结果
        
        Args:
            task_id: 任务ID
            timeout: 超时时间（秒），None 表示无限等待
        
        Returns:
            任务返回值
        
        Raises:
            KeyError: 任务不存在
            TimeoutError: 等待超时
            Exception: 任务执行过程中的异常
        
        Example:
            ```python
            future = executor_manager.submit_task("task_1", my_task, x=1)
            
            # 方式1：通过 future 等待
            result = future.result(timeout=10)
            
            # 方式2：通过 task_id 等待（更方便）
            result = executor_manager.wait_task("task_1", timeout=10)
            ```
        """
        future = self.get_task_future(task_id)
        if not future:
            raise KeyError(f"任务 {task_id} 不存在或已完成")
        
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            logger.warning(f"等待任务 {task_id} 超时")
            raise
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            raise
    
    def get_task_future(self, task_id: str) -> Optional[Future]:
        """
        获取任务的 Future 对象
        
        ✅ 任务完成后 Future 仍然保留，可以查询结果
        
        Returns:
            Future 对象，如果任务不存在则返回 None
        """
        with self._lock:
            return self._task_futures.get(task_id)
    
    def get_active_task_count(self) -> int:
        """
        获取活跃任务数量（包括已完成但未删除的任务）
        
        Note:
            由于 Future 不会自动清理，此方法返回的是所有任务数量
            包括正在运行的和已完成的任务
        """
        with self._lock:
            return len(self._task_futures)
    
    def get_running_task_count(self) -> int:
        """
        获取正在运行的任务数量（不包括已完成的）
        
        Returns:
            正在运行的任务数量
        """
        with self._lock:
            return sum(1 for future in self._task_futures.values() if not future.done())
    
    def shutdown(self, wait: bool = True, cancel_futures: bool = False, timeout: float = 30.0):
        """
        优雅关闭线程池
        
        Args:
            wait: 是否等待正在运行的任务完成
            cancel_futures: 是否取消等待中的任务
            timeout: 等待超时时间（秒）⚠️ 需要 Python 3.9+
        
        Behavior:
            - wait=True, cancel_futures=False: 等待所有任务完成（推荐）
            - wait=True, cancel_futures=True: 取消等待任务，等待运行任务完成
            - wait=False, cancel_futures=True: 立即取消所有任务（不等待）
        
        Note:
            ⚠️ shutdown 后，executor_manager 不可再用
            调用 submit_task() 会抛出 RuntimeError
        """
        with self._lock:
            if self._shutdown:
                logger.warning("线程池已经关闭")
                return
            
            self._shutdown = True
            active_count = len(self._task_futures)
            
            # ✅ 设置所有任务的取消标志
            if cancel_futures:
                for task_id, token in self._cancellation_tokens.items():
                    token.cancel()
                logger.info(f"已设置 {len(self._cancellation_tokens)} 个任务的取消标志")
        
        # ✅ 在锁外执行 shutdown（避免死锁）
        logger.info(f"关闭线程池: wait={wait}, cancel_futures={cancel_futures}, timeout={timeout}s, 活跃任务={active_count}")
        
        try:
            # 🐛 修复3：正确传递 timeout 参数
            if PYTHON_39_PLUS:
                self._executor.shutdown(
                    wait=wait, 
                    cancel_futures=cancel_futures,
                    timeout=timeout  # ✅ Python 3.9+ 支持
                )
            else:
                # Python 3.8 及以下不支持 timeout 参数
                logger.warning(f"Python {sys.version_info.major}.{sys.version_info.minor} 不支持 shutdown timeout，忽略 timeout 参数")
                self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            
            logger.info("线程池已关闭")
        except Exception as e:
            logger.error(f"关闭线程池时发生错误: {e}")
        finally:
            with self._lock:
                # ✅ shutdown 时清理所有资源
                self._task_futures.clear()
                self._cancellation_tokens.clear()


# ✅ 全局单例实例
executor_manager = ExecutorManager()