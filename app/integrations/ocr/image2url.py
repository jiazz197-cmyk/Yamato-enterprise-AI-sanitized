"""Upload bytes or streams to MinIO and return a public object URL."""

import io
from minio.error import S3Error
from app.core.storage import get_minio_client
from app.core.config import settings

MINIO_ENDPOINT = settings.MINIO_ENDPOINT
MINIO_PUBLIC_ENDPOINT = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME
MINIO_SECURE = settings.MINIO_SECURE

def upload_file_to_minio(file_data, file_name):
    """put_object then build http(s)://endpoint/bucket/key URL."""
    client = get_minio_client()
    
    if not client.bucket_exists(MINIO_BUCKET_NAME):
        client.make_bucket(MINIO_BUCKET_NAME)
        client.set_bucket_policy(
            MINIO_BUCKET_NAME,
            '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::%s/*"}]}' % MINIO_BUCKET_NAME
        )
    
    file_stream = None
    try:
        if isinstance(file_data, bytes):
            file_stream = io.BytesIO(file_data)
            file_size = len(file_data)
        else:
            file_stream = file_data
            file_stream.seek(0, 2)
            file_size = file_stream.tell()
            file_stream.seek(0)
        
        client.put_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
            data=file_stream,
            length=file_size,
            content_type="application/octet-stream"
        )
        
        protocol = "https" if MINIO_SECURE else "http"
        return f"{protocol}://{MINIO_PUBLIC_ENDPOINT}/{MINIO_BUCKET_NAME}/{file_name}"
    
    except S3Error as e:
        raise Exception(f"MinIO 上传失败: {e}")
    except Exception as e:
        raise Exception(f"上传文件异常: {str(e)}")
    finally:
        if file_stream is not None and hasattr(file_stream, "close"):
            file_stream.close()