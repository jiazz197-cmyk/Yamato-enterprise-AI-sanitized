"""
MinIO 存储工具集
"""
import atexit
import tempfile
from pathlib import Path
from typing import IO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import database_logger

logger = database_logger

MINIO_ENDPOINT = settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def _ensure_bucket():
    """确保目标 Bucket 存在。"""
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET_NAME):
            minio_client.make_bucket(MINIO_BUCKET_NAME)
            logger.info("Created MinIO bucket %s", MINIO_BUCKET_NAME)
        else:
            logger.debug("MinIO bucket %s already exists", MINIO_BUCKET_NAME)
    except S3Error as err:
        logger.error("Error ensuring MinIO bucket: %s", err)


_ensure_bucket()


def upload_to_minio(file_path: str, file_name: str) -> str:
    """将本地文件上传到 MinIO。"""
    try:
        minio_client.fput_object(MINIO_BUCKET_NAME, file_name, file_path)
        return file_name
    except S3Error as err:
        logger.error("Error uploading file to MinIO: %s", err)
        return f"Error uploading file to MinIO: {err}"


def upload_buffer_to_minio(buffer: IO[bytes], file_name: str,
                           content_type: str = "application/octet-stream") -> str:
    """上传内存缓冲区，例如 BytesIO。"""
    try:
        buffer.seek(0, 2)
        size = buffer.tell()
        buffer.seek(0)
        minio_client.put_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
            data=buffer,
            length=size,
            content_type=content_type,
        )
        return file_name
    except S3Error as err:
        logger.error("Error uploading buffer to MinIO: %s", err)
        return f"Error uploading buffer to MinIO: {err}"


def delete_from_minio(file_name: str) -> bool:
    """删除 MinIO 中的单个对象。"""
    try:
        minio_client.remove_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
        )
        return True
    except S3Error as err:
        logger.error("Error deleting MinIO object: %s", err)
        return False


def save_file_from_minio(object_name: str, temp_prefix: str = "minio_download_") -> Path:
    """下载对象到临时文件，返回路径。"""
    temp_file = tempfile.NamedTemporaryFile(prefix=temp_prefix, delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        atexit.register(lambda: temp_path.unlink(missing_ok=True))
        response = minio_client.get_object(MINIO_BUCKET_NAME, object_name)
        with temp_path.open("wb") as file_handle:
            for chunk in response.stream(32 * 1024):
                file_handle.write(chunk)
        response.close()
        response.release_conn()
        return temp_path
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"下载文件失败: {exc}") from exc


def download_to_temp(file_name: str) -> Path:
    """直接下载到系统临时目录，若存在则复用。"""
    temp_dir = Path(tempfile.gettempdir())
    file_path = temp_dir / file_name
    try:
        if file_path.exists():
            return file_path
        minio_client.fget_object(MINIO_BUCKET_NAME, file_name, str(file_path))
        return file_path
    except S3Error as err:
        logger.error("Error downloading file from MinIO: %s", err)
        raise RuntimeError(f"Error downloading file from MinIO: {err}") from err
