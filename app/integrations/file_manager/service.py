"""File list/upload/delete business logic (MinIO via app.core.storage, DB via Session)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.storage import (
    MINIO_BUCKET_NAME,
    delete_from_minio,
    get_minio_client,
    upload_stream_to_minio,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User, UserRole
from app.core.security import normalize_self_uploader

logger = get_logger("file_manager")


def generate_unique_filename(original_filename: str) -> str:
    """Return unique name: timestamp + uuid + original base name (legacy behavior)."""
    unique_id = uuid.uuid4().hex
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{unique_id}{original_filename}"


def get_file_or_not_found(db: Session, file_id: int) -> FileResource:
    file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
    if not file_record:
        raise NotFoundError(f"文件 ID {file_id} 不存在")
    return file_record


def assert_can_access_file(
    file_record: FileResource,
    current_user: User,
) -> None:
    """Non-superuser may only access own uploader. Raises PermissionError for API to map to 403."""
    if current_user.role != UserRole.superuser and file_record.uploader != current_user.username:
        raise PermissionError("forbidden")


def upload_stream_persist(
    db: Session,
    *,
    file_stream,
    original_filename: str,
    file_size: int,
    content_type: str,
    uploader: str,
    current_user: User,
) -> FileResource:
    """
    Stream to MinIO, persist FileResource, refresh id.
    Raises ValidationError. Returns FileResource. MinIO 'Error*' result raises RuntimeError(result).
    """
    if not original_filename:
        raise ValidationError("文件名不能为空")

    unique_name = generate_unique_filename(original_filename)
    minio_path = f"uploads/{unique_name}"
    result = upload_stream_to_minio(file_stream, minio_path, file_size, content_type)
    if result.startswith("Error"):
        raise RuntimeError(result)

    if file_size == -1:
        try:
            minio_client = get_minio_client()
            stat = minio_client.stat_object(MINIO_BUCKET_NAME, minio_path)
            file_size = stat.size
        except Exception as e:
            logger.warning("无法获取上传文件大小: %s", e)
            file_size = 0

    normalized_uploader = normalize_self_uploader(uploader, current_user)
    file_record = FileResource(
        file_name=original_filename,
        unique_name=unique_name,
        minio_object_path=minio_path,
        content_type=content_type,
        file_size=file_size,
        uploader=normalized_uploader,
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)
    logger.info("文件上传成功: %s -> %s (ID: %s)", original_filename, minio_path, file_record.id)
    return file_record


def list_files_page(
    db: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
    uploader: Optional[str],
) -> Tuple[int, List[FileResource]]:
    query = db.query(FileResource)
    if current_user.role != UserRole.superuser:
        query = query.filter(FileResource.uploader == current_user.username)
    elif uploader:
        query = query.filter(FileResource.uploader == uploader)
    total = query.count()
    offset = (page - 1) * page_size
    items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
    return total, items


def delete_file_and_object(db: Session, file_record: FileResource) -> None:
    if not delete_from_minio(file_record.minio_object_path):
        logger.warning(
            "MinIO 删除失败，但继续删除数据库记录: %s", file_record.minio_object_path
        )
    db.delete(file_record)
    db.commit()


def search_files_page(
    db: Session,
    *,
    current_user: User,
    keyword: str,
    page: int,
    page_size: int,
) -> Tuple[int, List[FileResource]]:
    query = db.query(FileResource).filter(FileResource.file_name.ilike(f"%{keyword}%"))
    if current_user.role != UserRole.superuser:
        query = query.filter(FileResource.uploader == current_user.username)
    total = query.count()
    offset = (page - 1) * page_size
    items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
    return total, items


def batch_delete_ids(db: Session, file_ids: List[int]) -> tuple[int, int, List[int]]:
    """Delete each id: MinIO + DB. Returns (success_count, failed_count, failed_ids)."""
    success_count = 0
    failed_count = 0
    failed_ids: List[int] = []
    for file_id in file_ids:
        try:
            file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
            if not file_record:
                failed_count += 1
                failed_ids.append(file_id)
                continue
            delete_from_minio(file_record.minio_object_path)
            db.delete(file_record)
            db.commit()
            success_count += 1
        except Exception:
            logger.exception("批量删除失败 (ID: %s)", file_id)
            failed_count += 1
            failed_ids.append(file_id)
            db.rollback()
    return success_count, failed_count, failed_ids
