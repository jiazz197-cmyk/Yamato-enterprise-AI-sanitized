"""MinIO：按线程 TLS 建 client，bucket 懒检查；分块阈值见 DEFAULT_CHUNK_SIZE。"""
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

MINIO_ENDPOINT = settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME
MINIO_SECURE = settings.MINIO_SECURE

DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024
STREAM_CHUNK_SIZE = 1 * 1024 * 1024


class MinioClientPool:
    """单例：每线程一个 Minio；bucket 存在性按名缓存。"""
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """仅首次初始化。"""
        if self._initialized:
            return
        
        self._local = threading.local()
        self._bucket_checked: Dict[str, bool] = {}
        self._bucket_lock = threading.Lock()
        
        self.__class__._initialized = True
    
    def get_client(self) -> Minio:
        """当前线程懒创建 Minio。"""
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
        """无则创建；异常只打日志并返回 False。同一 bucket 只检查一次。"""
        if self._bucket_checked.get(bucket_name, False):
            return True
        
        with self._bucket_lock:
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


_minio_pool = MinioClientPool()


def get_minio_client() -> Minio:
    """取当前线程 client；勿模块级缓存以免跨线程复用。"""
    return _minio_pool.get_client()


def upload_to_minio(file_path: str, file_name: str) -> str:
    """fput 上传本地文件；失败返回 Error 前缀字符串。"""
    try:
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
    """能 seek 则带 length 直传，否则分块；不要用 read 全长估大小。"""
    try:
        if not _minio_pool.ensure_bucket():
            return "Error: MinIO service unavailable"
        
        size = -1
        try:
            current_pos = buffer.tell()
            buffer.seek(0, 2)
            size = buffer.tell()
            buffer.seek(current_pos)
        except (OSError, AttributeError):
            pass
        
        client = get_minio_client()
        
        if size > 0:
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=buffer,
                length=size,
                content_type=content_type,
            )
        else:
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=buffer,
                length=-1,
                content_type=content_type,
                part_size=DEFAULT_CHUNK_SIZE,
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
    """file_size>0 直传；否则分块。"""
    try:
        if not _minio_pool.ensure_bucket():
            return "Error: MinIO service unavailable"
        
        client = get_minio_client()
        
        if file_size > 0:
            client.put_object(
                bucket_name=MINIO_BUCKET_NAME,
                object_name=file_name,
                data=file_stream,
                length=file_size,
                content_type=content_type,
            )
        else:
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
    """remove_object；异常返回 False。"""
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
    """get_object 流；finally 关闭并 release_conn。"""
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(MINIO_BUCKET_NAME, object_name)
        yield response
    finally:
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
    """NamedTemporaryFile(delete=False) 写入；失败删临时文件。路径需调用方自行清理。"""
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            prefix=temp_prefix, 
            delete=False,
            suffix=Path(object_name).suffix
        )
        temp_path = Path(temp_file.name)
        temp_file.close()
        
        with download_object_stream(object_name) as response:
            with temp_path.open("wb") as file_handle:
                for chunk in response.stream(STREAM_CHUNK_SIZE):
                    file_handle.write(chunk)
        
        logger.debug(f"下载到临时文件: {temp_path}")
        return temp_path
        
    except Exception as exc:
        if temp_file and Path(temp_file.name).exists():
            try:
                Path(temp_file.name).unlink()
            except:
                pass
        logger.error(f"下载文件失败: {exc}")
        raise RuntimeError(f"下载文件失败: {exc}") from exc


def download_to_file(object_name: str, local_path: str) -> Path:
    """fget_object；父目录不存在则创建。"""
    try:
        client = get_minio_client()
        file_path = Path(local_path)
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
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
