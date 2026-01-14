"""
MinIO 存储工具集

⚠️ 关键改进：
1. 延迟初始化 - 不在模块加载时连接 MinIO
2. 线程安全连接池 - 每个线程独立 client
3. 资源管理 - 使用 context manager 防止泄漏
4. 错误处理 - 优雅降级，不阻塞启动
"""
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Optional, Generator, Dict

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("storage")

# 配置常量
MINIO_ENDPOINT = settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME
MINIO_SECURE = settings.MINIO_SECURE

# ⚠️ 默认 chunk 大小（5MB）- MinIO 要求分块大小 >= 5MB
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024  # 5MB

# ⚠️ 流式下载 chunk 大小（1MB）- 平衡内存和性能
STREAM_CHUNK_SIZE = 1 * 1024 * 1024  # 1MB


class MinioClientPool:
    """
    MinIO 客户端连接池（线程安全 + 单例模式）
    
    ✅ 解决问题：
    1. MinIO client 不是线程安全的，需要每个线程独立实例
    2. 延迟初始化，不在模块加载时连接
    3. 自动管理 Bucket 创建
    4. ✅ 单例模式确保全局唯一连接池
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """确保只创建一个 MinioClientPool 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化（只执行一次）"""
        if self._initialized:
            return
        
        self._local = threading.local()
        self._bucket_checked: Dict[str, bool] = {}  # ✅ 按 bucket 名称记录检查状态
        self._bucket_lock = threading.Lock()
        
        self.__class__._initialized = True
    
    def get_client(self) -> Minio:
        """
        获取当前线程的 MinIO 客户端
        
        ✅ 每个线程独立实例，避免竞态条件
        """
        if not hasattr(self._local, 'client'):
            self._local.client = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE,
            )
            logger.debug(f"创建 MinIO 客户端: 线程 {threading.current_thread().name}")
        
        return self._local.client
    
    def ensure_bucket(self, bucket_name: str = MINIO_BUCKET_NAME) -> bool:
        """
        确保 Bucket 存在（每个 bucket 只检查一次，延迟执行）
        
        ✅ 改进：
        1. 只在第一次使用时检查
        2. 使用双重检查锁，避免多线程重复创建
        3. 失败不抛异常，只记录日志
        4. 按 bucket 名称记录检查状态（支持多 bucket）
        
        Returns:
            True - Bucket 可用
            False - Bucket 不可用（降级模式）
        """
        # ✅ 快速路径：该 bucket 已经检查过
        if self._bucket_checked.get(bucket_name, False):
            return True
        
        # 慢速路径：需要检查
        with self._bucket_lock:
            # ✅ 双重检查（防止多线程同时进入）
            if self._bucket_checked.get(bucket_name, False):
                return True
            
            try:
                client = self.get_client()
                if not client.bucket_exists(bucket_name):
                    client.make_bucket(bucket_name)
                    logger.info(f"创建 MinIO bucket: {bucket_name}")
                else:
                    logger.debug(f"MinIO bucket 已存在: {bucket_name}")
                
                self._bucket_checked[bucket_name] = True
                return True
                
            except S3Error as e:
                logger.error(f"MinIO bucket 检查失败: {e}，服务降级运行")
                return False
            except Exception as e:
                logger.error(f"MinIO 连接失败: {e}，服务降级运行")
                return False


# ✅ 全局连接池（延迟初始化）
_minio_pool = MinioClientPool()


def get_minio_client() -> Minio:
    """
    获取 MinIO 客户端（线程安全）
    
    ⚠️ 重要：每次调用都使用此函数，不要缓存返回值
    
    ⚠️ 团队约定：
    - 禁止缓存客户端：不要写 `global_client = get_minio_client()`
    - 每个函数内部调用：确保线程隔离
    - 优先使用封装函数：upload_to_minio(), download_object_stream() 等
    
    Usage:
        # ✅ 推荐：使用封装函数
        upload_to_minio(file_path, file_name)
        
        # ✅ 可选：临时获取 client（函数作用域内）
        def my_function():
            client = get_minio_client()
            client.put_object(...)
        
        # ❌ 禁止：缓存客户端
        # global_client = get_minio_client()  # 危险！破坏线程隔离
    """
    return _minio_pool.get_client()


def upload_to_minio(file_path: str, file_name: str) -> str:
    """
    将本地文件上传到 MinIO
    
    Args:
        file_path: 本地文件路径
        file_name: MinIO 对象名
    
    Returns:
        成功返回文件名，失败返回错误信息
    """
    try:
        # ✅ 延迟检查 bucket
        if not _minio_pool.ensure_bucket():
            return "Error: MinIO service unavailable"
        
        client = get_minio_client()
        client.fput_object(MINIO_BUCKET_NAME, file_name, file_path)
        logger.debug(f"上传文件成功: {file_name}")
        return file_name
    except S3Error as err:
        logger.error(f"上传文件到 MinIO 失败: {err}")
        return f"Error uploading file to MinIO: {err}"
    except Exception as e:
        logger.error(f"上传文件异常: {e}")
        return f"Error: {e}"


def upload_buffer_to_minio(
    buffer: IO[bytes], 
    file_name: str,
    content_type: str = "application/octet-stream"
) -> str:
    """
    上传缓冲区或流到 MinIO（智能判断大小）
    
    ✅ 改进：
    1. 优先尝试获取准确大小（避免分块上传）
    2. 分块上传时使用合理的 chunk_size
    3. 不读取流内容（避免内存爆炸）
    
    Args:
        buffer: 字节流（支持 seek 最佳）
        file_name: MinIO 对象名
        content_type: MIME 类型
    
    Returns:
        成功返回文件名，失败返回错误信息
    """
    try:
        if not _minio_pool.ensure_bucket():
            return "Error: MinIO service unavailable"
        
        # ✅ 智能获取大小（只用 seek，不读取内容）
        size = -1
        try:
            current_pos = buffer.tell()
            buffer.seek(0, 2)  # 移到末尾
            size = buffer.tell()
            buffer.seek(current_pos)  # 恢复原位置
        except (OSError, AttributeError):
            # 流不支持 seek，使用 -1 触发分块上传
            # ⚠️ 不要用 len(buffer.read())，会把流全读进内存
            pass
        
        client = get_minio_client()
        
        # ✅ 根据大小选择上传策略
        if size > 0:
            # 已知大小 - 使用标准上传（高效）
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=buffer,
                length=size,
                content_type=content_type,
            )
        else:
            # 未知大小 - 使用分块上传（兼容，MinIO 会自动处理）
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=buffer,
                length=-1,
                content_type=content_type,
                part_size=DEFAULT_CHUNK_SIZE,  # ✅ 显式指定 chunk
            )
        
        logger.debug(f"上传缓冲区成功: {file_name} (size={size})")
        return file_name
        
    except S3Error as err:
        logger.error(f"上传缓冲区到 MinIO 失败: {err}")
        return f"Error uploading buffer to MinIO: {err}"
    except Exception as e:
        logger.error(f"上传缓冲区异常: {e}")
        return f"Error: {e}"


def upload_stream_to_minio(
    file_stream: IO[bytes], 
    file_name: str, 
    file_size: int = -1,
    content_type: str = "application/octet-stream"
) -> str:
    """
    流式上传文件到 MinIO（显式指定大小）
    
    ⚠️ 建议：
    - 如果能获取 file_size，务必传入（提升性能）
    - file_size = -1 会使用分块上传（内存占用大）
    
    Args:
        file_stream: 文件流对象
        file_name: MinIO 对象名
        file_size: 文件大小（字节），-1 表示未知
        content_type: 内容类型
    
    Returns:
        成功返回文件名，失败返回错误信息
    """
    try:
        if not _minio_pool.ensure_bucket():
            return "Error: MinIO service unavailable"
        
        client = get_minio_client()
        
        # ✅ 根据 file_size 选择策略
        if file_size > 0:
            # 已知大小 - 标准上传
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=file_stream,
                length=file_size,
                content_type=content_type,
            )
        else:
            # 未知大小 - 分块上传
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=file_stream,
                length=-1,
                content_type=content_type,
                part_size=DEFAULT_CHUNK_SIZE,
            )
        
        logger.debug(f"流式上传成功: {file_name} (size={file_size})")
        return file_name
        
    except S3Error as err:
        logger.error(f"流式上传到 MinIO 失败: {err}")
        return f"Error uploading stream to MinIO: {err}"
    except Exception as e:
        logger.error(f"流式上传异常: {e}")
        return f"Error: {e}"


def delete_from_minio(file_name: str) -> bool:
    """
    删除 MinIO 中的单个对象
    
    Args:
        file_name: MinIO 对象名
    
    Returns:
        True - 删除成功
        False - 删除失败
    """
    try:
        client = get_minio_client()
        client.remove_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
        )
        logger.debug(f"删除对象成功: {file_name}")
        return True
    except S3Error as err:
        logger.error(f"删除 MinIO 对象失败: {err}")
        return False
    except Exception as e:
        logger.error(f"删除对象异常: {e}")
        return False


@contextmanager
def download_object_stream(object_name: str) -> Generator[IO[bytes], None, None]:
    """
    下载对象为流（使用 context manager 防止资源泄漏）
    
    ✅ 最佳实践：
    ```python
    with download_object_stream("file.pdf") as stream:
        for chunk in stream.stream(STREAM_CHUNK_SIZE):  # 1MB chunks
            process(chunk)
    # 自动关闭连接，无泄漏
    ```
    
    Args:
        object_name: MinIO 对象名
    
    Yields:
        HTTP 响应流对象
    
    Note:
        默认使用 STREAM_CHUNK_SIZE (1MB) chunk，适合大文件下载
    """
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(MINIO_BUCKET_NAME, object_name)
        yield response
    finally:
        # ✅ 确保资源释放
        if response:
            try:
                response.close()
                response.release_conn()
            except Exception as e:
                logger.warning(f"关闭 MinIO 响应失败: {e}")


def save_file_from_minio(
    object_name: str, 
    temp_prefix: str = "minio_download_"
) -> Path:
    """
    下载对象到临时文件（自动清理）
    
    ✅ 改进：
    1. 使用 context manager 防止资源泄漏
    2. 使用 NamedTemporaryFile(delete=False)，手动控制清理
    3. 异常时立即删除文件
    4. 使用 1MB chunk 提升下载速度
    
    Args:
        object_name: MinIO 对象名
        temp_prefix: 临时文件前缀
    
    Returns:
        临时文件路径
    
    ⚠️ 注意：
    - 文件在程序退出时不会自动删除（delete=False）
    - 如果需要自动清理，请使用 TemporaryFile 或手动删除
    """
    temp_file = None
    try:
        # ✅ 创建临时文件（delete=False，手动控制）
        temp_file = tempfile.NamedTemporaryFile(
            prefix=temp_prefix, 
            delete=False,
            suffix=Path(object_name).suffix
        )
        temp_path = Path(temp_file.name)
        temp_file.close()
        
        # ✅ 使用 context manager 下载（1MB chunks）
        with download_object_stream(object_name) as response:
            with temp_path.open("wb") as file_handle:
                for chunk in response.stream(STREAM_CHUNK_SIZE):
                    file_handle.write(chunk)
        
        logger.debug(f"下载到临时文件: {temp_path}")
        return temp_path
        
    except Exception as exc:
        # ✅ 失败时清理文件
        if temp_file and Path(temp_file.name).exists():
            try:
                Path(temp_file.name).unlink()
            except:
                pass
        logger.error(f"下载文件失败: {exc}")
        raise RuntimeError(f"下载文件失败: {exc}") from exc


def download_to_file(object_name: str, local_path: str) -> Path:
    """
    下载对象到指定本地路径（不使用缓存）
    
    ✅ 改进：
    1. 每次都重新下载（避免脏数据）
    2. 使用 fget_object（更高效）
    3. 支持断点续传
    
    Args:
        object_name: MinIO 对象名
        local_path: 本地文件路径
    
    Returns:
        本地文件路径
    """
    try:
        client = get_minio_client()
        file_path = Path(local_path)
        
        # ✅ 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # ✅ 直接下载（不检查是否存在，避免脏数据）
        client.fget_object(
            MINIO_BUCKET_NAME, 
            object_name, 
            str(file_path)
        )
        
        logger.debug(f"下载文件到: {file_path}")
        return file_path
        
    except S3Error as err:
        logger.error(f"从 MinIO 下载文件失败: {err}")
        raise RuntimeError(f"从 MinIO 下载文件失败: {err}") from err
    except Exception as e:
        logger.error(f"下载文件异常: {e}")
        raise RuntimeError(f"下载文件异常: {e}") from e
