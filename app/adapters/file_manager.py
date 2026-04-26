"""File manager port adapter over integrations.file_manager.service."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.integrations.file_manager import service as file_service
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User
from app.ports.domains.file_manager import FileManagerPort
from app.ports.dto.files import FileRecordDTO


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
    def __init__(self, db: Session):
        self._db = db

    def upload_stream_persist(
        self,
        *,
        file_stream: Any,
        original_filename: str,
        file_size: int,
        content_type: str,
        uploader: str,
        current_user: User,
    ) -> FileRecordDTO:
        try:
            rec = file_service.upload_stream_persist(
                self._db,
                file_stream=file_stream,
                original_filename=original_filename,
                file_size=file_size,
                content_type=content_type,
                uploader=uploader,
                current_user=current_user,
            )
        except RuntimeError as e:
            err = str(e)
            if err.startswith("Error"):
                raise APIException(err, status_code=500, error_code="MINIO_UPLOAD_FAILED") from e
            raise
        return _to_dto(rec)

    def get_file_or_not_found(self, file_id: int) -> FileRecordDTO:
        return _to_dto(file_service.get_file_or_not_found(self._db, file_id))

    def list_files_page(
        self,
        *,
        current_user: User,
        page: int,
        page_size: int,
        uploader: Optional[str],
    ) -> Tuple[int, List[FileRecordDTO]]:
        total, items = file_service.list_files_page(
            self._db,
            current_user=current_user,
            page=page,
            page_size=page_size,
            uploader=uploader,
        )
        return total, [_to_dto(i) for i in items]

    def search_files_page(
        self,
        *,
        current_user: User,
        keyword: str,
        page: int,
        page_size: int,
    ) -> Tuple[int, List[FileRecordDTO]]:
        total, items = file_service.search_files_page(
            self._db,
            current_user=current_user,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return total, [_to_dto(i) for i in items]

    def delete_file_and_object(self, file_record: FileRecordDTO) -> None:
        rec = file_service.get_file_or_not_found(self._db, file_record.id)
        file_service.delete_file_and_object(self._db, rec)

    def batch_delete_ids(self, file_ids: List[int]) -> Tuple[int, int, List[int]]:
        return file_service.batch_delete_ids(self._db, file_ids)
