"""Closing form integration outbound port."""

from __future__ import annotations

from typing import Any, Protocol


class ClosingFormServicePort(Protocol):
    def submit_closing_form(self, uploader: str, form_data: Any) -> Any:
        ...

    def list_merged_forms(self, *, uploader: str, is_privileged: bool) -> Any:
        ...

    def approve_pending_form(self, form_id: int, approved_by_username: str) -> Any:
        ...

    def reject_pending_form(self, form_id: int, rejected_by_username: str) -> Any:
        ...

    def list_collection2(self) -> Any:
        ...

    def delete_collection2_record(self, record_id: int, deleted_by_username: str) -> Any:
        ...

    def delete_approved_closing_form(self, record_id: int, deleted_by_username: str) -> Any:
        ...

    def delete_rejected_closing_form(self, form_id: int, deleted_by_username: str) -> Any:
        ...

    def upload_closing_form_image(
        self, file_stream: Any, original_filename: str, content_type: str, uploader: str
    ) -> str:
        ...
