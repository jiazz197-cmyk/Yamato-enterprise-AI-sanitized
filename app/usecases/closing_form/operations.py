"""Closing form use cases (thin delegation)."""

from __future__ import annotations

from typing import Any

from app.ports.contracts.identity import CurrentUserPort
from app.ports.domains.closing_form import ClosingFormServicePort
from app.ports.dto.closing_form import ClosingFormCommand


class SubmitClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, current_user: CurrentUserPort, cmd: ClosingFormCommand):
        return self._svc.submit_closing_form(current_user.username, cmd)


class ListClosingFormsUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, current_user: CurrentUserPort):
        is_privileged = current_user.is_admin_like()
        return self._svc.list_merged_forms(uploader=current_user.username, is_privileged=is_privileged)


class ApproveClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, form_id: int, current_user: CurrentUserPort):
        return self._svc.approve_pending_form(form_id, current_user.username)


class RejectClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, form_id: int, current_user: CurrentUserPort):
        return self._svc.reject_pending_form(form_id, current_user.username)


class ListCollection2UseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self):
        return self._svc.list_collection2()


class DeleteCollection2RecordUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, record_id: int, current_user: CurrentUserPort):
        return self._svc.delete_collection2_record(record_id, current_user.username)


class DeleteApprovedClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, record_id: int, current_user: CurrentUserPort):
        return self._svc.delete_approved_closing_form(record_id, current_user.username)


class DeleteRejectedClosingFormUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(self, form_id: int, current_user: CurrentUserPort):
        return self._svc.delete_rejected_closing_form(form_id, current_user.username)


class UploadClosingFormImageUseCase:
    def __init__(self, svc: ClosingFormServicePort):
        self._svc = svc

    def execute(
        self, file_stream: Any, original_filename: str, content_type: str, uploader: str
    ) -> str:
        return self._svc.upload_closing_form_image(
            file_stream, original_filename, content_type, uploader
        )
