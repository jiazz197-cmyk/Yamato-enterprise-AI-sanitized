from minio import Minio
from minio.error import S3Error
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# 拼接数据库连接 URL
db_url = settings.SQLALCHEMY_DATABASE_URI
# 创建数据库引擎
engine = create_engine(db_url, echo=True, pool_pre_ping=True)

# 创建会话
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)




# # 基础类
Base = declarative_base()

# MinIO 连接设置
MINIO_URL = settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME

# 创建 MinIO 客户端实例
minio_client = Minio(
    MINIO_URL,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE
)



# 确保桶存在，如果不存在则创建
try:
    if not minio_client.bucket_exists(MINIO_BUCKET_NAME):
        minio_client.make_bucket(MINIO_BUCKET_NAME)
    else:
        print(f"Bucket '{MINIO_BUCKET_NAME}' already exists.")
except S3Error as err:
    print(f"Error occurred while connecting to MinIO: {err}")

def upload_to_minio(file_path: str, file_name: str):
    try:
        # 上传文件到 MinIO
        minio_client.fput_object(MINIO_BUCKET_NAME, file_name, file_path)
        return file_name
    except S3Error as err:
        print(f"Error uploading file to MinIO: {err}")
        return f"Error uploading file to MinIO: {err}"

def upload_buffer_to_minio(buffer, file_name: str, content_type: str = "application/octet-stream"):
    try:
        buffer.seek(0)  # 确保从头读取
        size = len(buffer.getvalue())  # 获取 buffer 大小
        minio_client.put_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
            data=buffer,
            length=size,
            content_type=content_type
        )
        return file_name
    except S3Error as err:
        print(f"Error uploading buffer to MinIO: {err}")
        return f"Error uploading buffer to MinIO: {err}"
def delete_from_minio(file_name: str):
    """根据文件名删除 MinIO 对象"""
    try:
        minio_client.remove_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name
        )
        return True
    except S3Error as err:
        print(f"Error deleting file from MinIO: {err}")
        return False


import tempfile
import os
import atexit
from pathlib import Path

def save_file_from_minio(object_name: str, temp_prefix: str = "minio_download_"):
    """
    从 MinIO 下载文件到临时目录，程序退出时自动清理

    Args:
        object_name: MinIO 中的对象名称
        temp_prefix: 临时文件前缀

    Returns:
        Path: 临时文件路径对象
    """
    try:
        # 创建临时文件（自动生成唯一文件名）
        temp_file = tempfile.NamedTemporaryFile(
            prefix=temp_prefix,
            delete=False  # 不自动删除，我们自己管理
        )
        temp_path = Path(temp_file.name)

        # 注册退出时自动清理
        atexit.register(lambda: temp_path.unlink(missing_ok=True))

        # 下载文件到临时路径
        response = minio_client.get_object(MINIO_BUCKET_NAME, object_name)
        with temp_path.open("wb") as f:
            for chunk in response.stream(32 * 1024):
                f.write(chunk)

        # 释放资源
        response.close()
        response.release_conn()

        return temp_path  # 返回 Path 对象

    except Exception as e:
        # 如果出错，确保删除临时文件
        if 'temp_path' in locals():
            temp_path.unlink(missing_ok=True)
        raise Exception(f"下载文件失败: {str(e)}")

    except Exception as e:
        # 如果出错，确保删除临时文件
        if 'temp_path' in locals():
            temp_path.unlink(missing_ok=True)
        raise Exception(f"下载文件失败: {str(e)}")

def download_from_minio(file_name: str):
    try:
        # 创建临时文件夹（如果你想用系统默认临时目录）
        # clean_file_name = re.sub(r"^[0-9a-f]{32}_", "", file_name)

        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, file_name)
        # 如果文件已存在，先删除，避免 MinIO 尝试删除时报 PermissionError
        if os.path.exists(file_path):
            return file_path
        # 下载文件到指定路径
        minio_client.fget_object(MINIO_BUCKET_NAME, file_name, file_path)

        return file_path
    except S3Error as err:
        print(f"Error downloading file from MinIO: {err}")
        return f"Error downloading file from MinIO: {err}"