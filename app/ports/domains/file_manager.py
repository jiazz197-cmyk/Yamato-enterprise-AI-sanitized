"""File manager outbound port."""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, Tuple

from app.ports.contracts.identity import CurrentUserPort
from app.ports.dto.files import FileRecordDTO


class FileManagerPort(Protocol):
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
        ...

    def get_file_or_not_found(self, file_id: int) -> FileRecordDTO:
        ...

    def list_files_page(
        self,
        *,
        current_user: CurrentUserPort,
        page: int,
        page_size: int,
        uploader: Optional[str],
    ) -> Tuple[int, List[FileRecordDTO]]:
        ...

    def search_files_page(
        self,
        *,
        current_user: CurrentUserPort,
        keyword: str,
        page: int,
        page_size: int,
    ) -> Tuple[int, List[FileRecordDTO]]:
        ...

    def delete_file_and_object(self, file_record: FileRecordDTO) -> None:
        ...

    def batch_delete_ids(self, file_ids: List[int]) -> Tuple[int, int, List[int]]:
        ...
