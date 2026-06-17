"""Closing form MinIO storage adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import delete_from_minio, upload_stream_to_minio

logger = get_logger("closing_form.storage")


class ClosingFormStorageAdapter:

    def upload_image(self, file_stream, original_filename: str, content_type: str, uploader: str) -> str:
        prefix = settings.CLOSING_FORM_IMAGE_PREFIX
        ext = Path(original_filename).suffix or ".jpg"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_name = f"{ts}_{uuid4().hex}{ext}"
        object_name = f"{prefix}/{uploader}_{unique_name}"

        result = upload_stream_to_minio(file_stream, object_name, content_type=content_type)
        if result.startswith("Error"):
            raise RuntimeError(result)

        logger.info("上传报单图片成功: user=%s, object=%s", uploader, object_name)
        return object_name

    @staticmethod
    def delete_form_images(*image_urls: Optional[str]) -> None:
        for url in image_urls:
            if not url:
                continue
            if not delete_from_minio(url):
                logger.warning("MinIO 图片删除失败（已继续业务流程）: object=%s", url)
            else:
                logger.debug("已删除 MinIO 图片: %s", url)
