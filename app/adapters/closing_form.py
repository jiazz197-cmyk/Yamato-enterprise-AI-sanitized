"""Closing form service adapter."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.integrations.closing_form import service as closing_form_service
from app.ports.domains.closing_form import ClosingFormServicePort


class IntegrationClosingFormAdapter(ClosingFormServicePort):
    def submit_closing_form(self, db: Session, uploader: str, form_data: Any) -> Any:
        return closing_form_service.submit_closing_form(db, uploader, form_data)

    def list_merged_forms(self, db: Session, *, uploader: str, is_privileged: bool) -> Any:
        return closing_form_service.list_merged_forms(db, uploader=uploader, is_privileged=is_privileged)

    def approve_pending_form(self, db: Session, form_id: int, approved_by_username: str) -> Any:
        return closing_form_service.approve_pending_form(db, form_id, approved_by_username)

    def reject_pending_form(self, db: Session, form_id: int, rejected_by_username: str) -> Any:
        return closing_form_service.reject_pending_form(db, form_id, rejected_by_username)

    def list_collection2(self, db: Session) -> Any:
        return closing_form_service.list_collection2(db)

    def delete_collection2_record(self, db: Session, record_id: int, deleted_by_username: str) -> Any:
        return closing_form_service.delete_collection2_record(db, record_id, deleted_by_username)

    def delete_approved_closing_form(self, db: Session, record_id: int, deleted_by_username: str) -> Any:
        return closing_form_service.delete_approved_closing_form(db, record_id, deleted_by_username)
