"""
OCR 图片转 URL 工具

TODO: 待实现功能
- 图片上传到 MinIO
- 生成访问 URL
- OCR 文字识别集成
"""
import io  # 关键：导入 io 模块，用于将 bytes 转为文件流
from minio.error import S3Error
from app.core.storage import get_minio_client
from app.core.config import settings

# MinIO 连接设置（从 settings 读取）
MINIO_ENDPOINT = settings.MINIO_ENDPOINT
MINIO_ACCESS_KEY = settings.MINIO_ACCESS_KEY
MINIO_SECRET_KEY = settings.MINIO_SECRET_KEY
MINIO_BUCKET_NAME = settings.MINIO_BUCKET_NAME
MINIO_SECURE = settings.MINIO_SECURE

def upload_file_to_minio(file_data, file_name):
    """
    上传文件到 MinIO 并返回访问 URL
    :param file_data: 文件二进制数据 (bytes) 或文件流（如 UploadFile.file）
    :param file_name: 文件名
    :return: 公开访问 URL
    """
    client = get_minio_client()
    
    # 确保存储桶存在（保持不变）
    if not client.bucket_exists(MINIO_BUCKET_NAME):
        client.make_bucket(MINIO_BUCKET_NAME)
        # 设置桶为公开读（生产环境建议更精细的权限，这里保持你的原有逻辑）
        client.set_bucket_policy(
            MINIO_BUCKET_NAME,
            '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::%s/*"}]}' % MINIO_BUCKET_NAME
        )
    
    try:
        # 关键修复：将 bytes 转为可迭代的 BytesIO 流（模拟文件流）
        if isinstance(file_data, bytes):
            file_stream = io.BytesIO(file_data)
            file_size = len(file_data)
        else:
            # 如果传入的是文件流（如 UploadFile.file），直接使用并获取大小
            file_stream = file_data
            file_stream.seek(0, 2)  # 移动到流末尾 (SEEK_END = 2)
            file_size = file_stream.tell()     # 获取流大小
            file_stream.seek(0)                # 移回流开头（必须，否则上传为空）
        
        # 上传文件（data 传流对象，length 传实际大小）
        client.put_object(
            bucket_name=MINIO_BUCKET_NAME,
            object_name=file_name,
            data=file_stream,  # 传流对象（而非直接传 bytes）
            length=file_size,
            content_type="application/octet-stream"  # 可选：指定默认 Content-Type，避免 MinIO 默认为 binary/octet-stream
        )
        
        # 生成公开访问 URL（保持不变）
        protocol = "https" if MINIO_SECURE else "http"
        return f"{protocol}://{MINIO_ENDPOINT}/{MINIO_BUCKET_NAME}/{file_name}"
    
    except S3Error as e:
        raise Exception(f"MinIO 上传失败: {e}")
    except Exception as e:
        raise Exception(f"上传文件异常: {str(e)}")
    finally:
        # 可选：关闭流（BytesIO 无实际文件句柄，但养成习惯）
        if hasattr(file_stream, 'close'):
            file_stream.close()