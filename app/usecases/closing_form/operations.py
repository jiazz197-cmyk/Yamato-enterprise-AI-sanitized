"""Closing form use cases (thin delegation)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.orm.platform.user import User, UserRole
from app.ports.domains.closing_form import ClosingFormServicePort
from app.schemas.endpoints.closing_form import ClosingFormSubmit


class SubmitClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, current_user: User, form_data: ClosingFormSubmit):
        return self._svc.submit_closing_form(db, current_user.username, form_data)


class ListClosingFormsUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, current_user: User):
        is_privileged = current_user.role in (UserRole.admin, UserRole.superuser)
        return self._svc.list_merged_forms(db, uploader=current_user.username, is_privileged=is_privileged)


class ApproveClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, form_id: int, current_user: User):
        return self._svc.approve_pending_form(db, form_id, current_user.username)


class RejectClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, form_id: int, current_user: User):
        return self._svc.reject_pending_form(db, form_id, current_user.username)


class ListCollection2UseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session):
        return self._svc.list_collection2(db)


class DeleteCollection2RecordUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, record_id: int, current_user: User):
        return self._svc.delete_collection2_record(db, record_id, current_user.username)


class DeleteApprovedClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, record_id: int, current_user: User):
        return self._svc.delete_approved_closing_form(db, record_id, current_user.username)


class DeleteRejectedClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, db: Session, form_id: int, current_user: User):
        return self._svc.delete_rejected_closing_form(db, form_id, current_user.username)


class UploadClosingFormImageUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(
        self, file_stream: Any, original_filename: str, content_type: str, uploader: str
    ) -> str:
        return self._svc.upload_closing_form_image(
            file_stream, original_filename, content_type, uploader
        )
