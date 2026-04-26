"""Closing form integration outbound port."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session


class ClosingFormServicePort(Protocol):
    def submit_closing_form(self, db: Session, uploader: str, form_data: Any) -> Any:
        ...

    def list_merged_forms(self, db: Session, *, uploader: str, is_privileged: bool) -> Any:
        ...

    def approve_pending_form(self, db: Session, form_id: int, approved_by_username: str) -> Any:
        ...

    def reject_pending_form(self, db: Session, form_id: int, rejected_by_username: str) -> Any:
        ...

    def list_collection2(self, db: Session) -> Any:
        ...

    def delete_collection2_record(self, db: Session, record_id: int, deleted_by_username: str) -> Any:
        ...

    def delete_approved_closing_form(self, db: Session, record_id: int, deleted_by_username: str) -> Any:
        ...
