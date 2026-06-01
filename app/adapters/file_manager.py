"""File manager adapter: encapsulates ORM + MinIO behind FileManagerPort."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.exceptions import APIException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import normalize_self_uploader
from app.core.storage import (
    MINIO_BUCKET_NAME,
    delete_from_minio,
    get_minio_client,
    upload_stream_to_minio,
)
from app.domain.file_manager.naming import generate_unique_filename
from app.models.orm.file_resource import FileResource
from app.ports.contracts.identity import CurrentUserPort
from app.ports.domains.file_manager import FileManagerPort
from app.ports.dto.files import FileRecordDTO

logger = get_logger("file_manager")


def _to_dto(rec: FileResource) -> FileRecordDTO:
    return FileRecordDTO(
        id=rec.id,
        file_name=rec.file_name,
        unique_name=rec.unique_name,
        minio_object_path=rec.minio_object_path,
        content_type=rec.content_type,
        file_size=rec.file_size,
        uploader=rec.uploader,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


class SqlAlchemyFileManagerAdapter(FileManagerPort):
    """Encapsulates all ORM queries and MinIO operations.

    Each method manages its own session lifecycle internally.
    """

    def upload_stream_persist(
        self,
        *,
        file_stream: Any,
        original_filename: str,
        file_size: int,
        content_type: str,
        uploader: str,
        current_user: CurrentUserPort,
    ) -> FileRecordDTO:
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

        db: Session = SessionLocal()
        try:
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
            return _to_dto(file_record)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_file_or_not_found(self, file_id: int) -> FileRecordDTO:
        db: Session = SessionLocal()
        try:
            file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
            if not file_record:
                raise NotFoundError(f"文件 ID {file_id} 不存在")
            return _to_dto(file_record)
        finally:
            db.close()

    def list_files_page(
        self,
        *,
        current_user: CurrentUserPort,
        page: int,
        page_size: int,
        uploader: Optional[str],
    ) -> Tuple[int, List[FileRecordDTO]]:
        db: Session = SessionLocal()
        try:
            query = db.query(FileResource)
            if not current_user.is_superuser():
                query = query.filter(FileResource.uploader == current_user.username)
            elif uploader:
                query = query.filter(FileResource.uploader == uploader)
            total = query.count()
            offset = (page - 1) * page_size
            items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
            return total, [_to_dto(i) for i in items]
        finally:
            db.close()

    def search_files_page(
        self,
        *,
        current_user: CurrentUserPort,
        keyword: str,
        page: int,
        page_size: int,
    ) -> Tuple[int, List[FileRecordDTO]]:
        db: Session = SessionLocal()
        try:
            query = db.query(FileResource).filter(FileResource.file_name.ilike(f"%{keyword}%"))
            if not current_user.is_superuser():
                query = query.filter(FileResource.uploader == current_user.username)
            total = query.count()
            offset = (page - 1) * page_size
            items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
            return total, [_to_dto(i) for i in items]
        finally:
            db.close()

    def delete_file_and_object(self, file_record: FileRecordDTO) -> None:
        db: Session = SessionLocal()
        try:
            rec = db.query(FileResource).filter(FileResource.id == file_record.id).first()
            if not rec:
                raise NotFoundError(f"文件 ID {file_record.id} 不存在")
            if not delete_from_minio(rec.minio_object_path):
                logger.warning("MinIO 删除失败，但继续删除数据库记录: %s", rec.minio_object_path)
            db.delete(rec)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def batch_delete_ids(self, file_ids: List[int]) -> Tuple[int, int, List[int]]:
        db: Session = SessionLocal()
        success_count = 0
        failed_count = 0
        failed_ids: List[int] = []
        try:
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
        finally:
            db.close()
        return success_count, failed_count, failed_ids
