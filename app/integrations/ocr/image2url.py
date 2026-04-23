"""Upload bytes or streams to MinIO and return a presigned (or opt-in public) object URL."""

import io
from datetime import timedelta
from minio.error import S3Error
from app.core.storage import get_minio_client, get_minio_client_for_presign
from app.core.config import settings
from app.core.logging import get_logger

_logger = get_logger("image2url")

MINIO_PUBLIC_ENDPOINT = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
MINIO_SECURE = settings.MINIO_SECURE

_DEFAULT_BUCKET = settings.MINIO_BUCKET_NAME


def _target_bucket() -> str:
    return (settings.MINIO_OCR_TEMP_BUCKET or _DEFAULT_BUCKET).strip() or _DEFAULT_BUCKET


def _public_http_url(bucket: str, file_name: str) -> str:
    protocol = "https" if MINIO_SECURE else "http"
    return f"{protocol}://{MINIO_PUBLIC_ENDPOINT}/{bucket}/{file_name}"


def upload_file_to_minio(file_data, file_name):
    """put_object, then return presigned GetObject URL (default) or opt-in public URL for a dedicated bucket."""
    client = get_minio_client()
    bucket = _target_bucket()

    anonymous_read = bool(
        settings.MINIO_OCR_ENABLE_ANONYMOUS_BUCKET
        and settings.MINIO_OCR_ANONYMOUS_BUCKET
        and bucket == settings.MINIO_OCR_ANONYMOUS_BUCKET.strip()
    )

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        if anonymous_read:
            _logger.warning(
                "Applying anonymous s3:GetObject on bucket %s — ensure this is intentional and not your default app bucket",
                bucket,
            )
            client.set_bucket_policy(
                bucket,
                '{"Version":"2012-10-17","Statement":[{'
                '"Effect":"Allow","Principal":"*","Action":"s3:GetObject",'
                '"Resource":"arn:aws:s3:::%s/*"}]}' % bucket,
            )
    elif anonymous_read and settings.MINIO_OCR_ENABLE_ANONYMOUS_BUCKET:
        # Ensure policy exists for opt-in anonymous bucket (idempotent in practice)
        try:
            _logger.warning(
                "Refreshing anonymous GetObject policy on bucket %s — verify MINIO_OCR_ANONYMOUS_BUCKET is correct",
                bucket,
            )
            client.set_bucket_policy(
                bucket,
                '{"Version":"2012-10-17","Statement":[{'
                '"Effect":"Allow","Principal":"*","Action":"s3:GetObject",'
                '"Resource":"arn:aws:s3:::%s/*"}]}' % bucket,
            )
        except S3Error:
            pass

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
            bucket_name=bucket,
            object_name=file_name,
            data=file_stream,
            length=file_size,
            content_type="application/octet-stream",
        )

        if anonymous_read:
            return _public_http_url(bucket, file_name)

        expires = timedelta(hours=settings.MINIO_PRESIGN_EXPIRES_HOURS)
        # Sign with MINIO_PUBLIC_ENDPOINT (see get_minio_client_for_presign) so fetchers (OCR) are not
        # given 127.0.0.1 when they run outside the app host.
        return get_minio_client_for_presign().presigned_get_object(
            bucket, file_name, expires=expires
        )

    except S3Error as e:
        raise Exception(f"MinIO 上传失败: {e}")
    except Exception as e:
        raise Exception(f"上传文件异常: {str(e)}")
    finally:
        if file_stream is not None and hasattr(file_stream, "close"):
            file_stream.close()
