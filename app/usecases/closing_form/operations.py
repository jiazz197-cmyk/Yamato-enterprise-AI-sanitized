"""Closing form use cases — owns business logic and orchestration."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.ports.contracts.identity import CurrentUserPort
from app.ports.domains.closing_form import (
    ClosingFormEmbeddingPort,
    ClosingFormImageStoragePort,
    ClosingFormPersistencePort,
)
from app.ports.dto.closing_form import ClosingFormCommand

logger = get_logger("closing_form.usecase")


class SubmitClosingFormUseCase:
    def __init__(self, persistence: ClosingFormPersistencePort):
        self._persistence = persistence

    def execute(self, current_user: CurrentUserPort, cmd: ClosingFormCommand):
        from app.schemas.endpoints.closing_form import ClosingFormSubmitResponse

        formatted_text = cmd.to_formatted_text()
        result = self._persistence.submit_pending(
            form_text_raw=formatted_text,
            uploader=current_user.username,
            image_url_1=cmd.image_url_1,
            image_url_2=cmd.image_url_2,
        )
        logger.info("填表已暂存至待审批队列: uploader=%s", current_user.username)
        return ClosingFormSubmitResponse(
            success=True,
            message="提交成功，等待审批",
            form_text=result["form_text"],
            image_url_1=cmd.image_url_1,
            image_url_2=cmd.image_url_2,
        )


class ListClosingFormsUseCase:
    def __init__(self, persistence: ClosingFormPersistencePort):
        self._persistence = persistence

    def execute(self, current_user: CurrentUserPort):
        from app.schemas.endpoints.closing_form import ClosingFormListResponse, ClosingFormRecord

        is_privileged = current_user.is_admin_like()
        uploader_filter = None if is_privileged else current_user.username
        pending = self._persistence.list_pending_forms(uploader=uploader_filter)
        approved = self._persistence.list_approved_forms(uploader=uploader_filter)
        records = [ClosingFormRecord(**row) for row in pending] + [ClosingFormRecord(**row) for row in approved]
        records.sort(key=lambda r: r.upload_time or "", reverse=True)
        logger.info("查询填表记录: user=%s, pending=%d, approved=%d", current_user.username, len(pending), len(approved))
        return ClosingFormListResponse(success=True, total=len(records), records=records)


class ApproveClosingFormUseCase:
    """Owns the approval business flow: validate → embed → cleanup."""

    def __init__(
        self,
        persistence: ClosingFormPersistencePort,
        embedding: ClosingFormEmbeddingPort,
    ):
        self._persistence = persistence
        self._embedding = embedding

    def execute(self, form_id: int, current_user: CurrentUserPort):
        from app.schemas.endpoints.closing_form import ClosingFormApproveResponse

        row = self._persistence.get_pending_form(form_id)
        if row is None:
            raise NotFoundError("待审批表单不存在")
        if row["status"] != "pending":
            raise ValidationError(f"表单状态不是待审批（当前状态：{row['status']}）")

        self._embedding.upsert_approved_form(
            text=row["text"],
            uploader=row["uploader"],
            upload_time=str(row["upload_time"]),
            image_url_1=row.get("image_url_1"),
            image_url_2=row.get("image_url_2"),
        )
        self._persistence.delete_pending_form(form_id)

        logger.info("表单审批通过: form_id=%s, approved_by=%s", form_id, current_user.username)
        return ClosingFormApproveResponse(success=True, message="审批通过")


class RejectClosingFormUseCase:
    """Owns the rejection business flow: validate → delete images → mark rejected."""

    def __init__(
        self,
        persistence: ClosingFormPersistencePort,
        image_storage: ClosingFormImageStoragePort,
    ):
        self._persistence = persistence
        self._image_storage = image_storage

    def execute(self, form_id: int, current_user: CurrentUserPort):
        from app.schemas.endpoints.closing_form import ClosingFormRejectResponse

        row = self._persistence.get_pending_form(form_id)
        if row is None:
            raise NotFoundError("待审批表单不存在")
        if row["status"] != "pending":
            raise ValidationError(f"表单状态不是待审批（当前状态：{row['status']}）")

        self._image_storage.delete_form_images(row.get("image_url_1"), row.get("image_url_2"))
        self._persistence.reject_pending_form(form_id)

        logger.info("表单审批不通过: form_id=%s, rejected_by=%s", form_id, current_user.username)
        return ClosingFormRejectResponse(success=True, message="审批已拒绝")


class ListCollection2UseCase:
    def __init__(self, persistence: ClosingFormPersistencePort):
        self._persistence = persistence

    def execute(self):
        from app.schemas.endpoints.closing_form import Collection2ListResponse, Collection2Record

        rows = self._persistence.list_collection2_records()
        records = [Collection2Record(**row) for row in rows]
        return Collection2ListResponse(success=True, total=len(records), records=records)


class DeleteCollection2RecordUseCase:
    def __init__(self, persistence: ClosingFormPersistencePort):
        self._persistence = persistence

    def execute(self, record_id: int, current_user: CurrentUserPort):
        from app.core.exceptions import APIException
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        if not self._persistence.check_collection2_exists(record_id):
            raise NotFoundError("记录不存在")
        rowcount = self._persistence.delete_collection2_record(record_id)
        if rowcount <= 0:
            raise APIException("删除失败，请稍后重试", status_code=500)
        logger.info("删除 collection2 记录: record_id=%s, deleted_by=%s", record_id, current_user.username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))


class DeleteApprovedClosingFormUseCase:
    def __init__(self, persistence: ClosingFormPersistencePort, image_storage: ClosingFormImageStoragePort):
        self._persistence = persistence
        self._image_storage = image_storage

    def execute(self, record_id: int, current_user: CurrentUserPort):
        from app.core.exceptions import APIException
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        row = self._persistence.get_approved_form(record_id)
        if row is None:
            raise NotFoundError("记录不存在")
        self._image_storage.delete_form_images(row.get("image_url_1"), row.get("image_url_2"))
        rowcount = self._persistence.delete_approved_form(record_id)
        if rowcount <= 0:
            raise APIException("删除失败，请稍后重试", status_code=500)
        logger.info("删除已通过表单: record_id=%s, deleted_by=%s", record_id, current_user.username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))


class DeleteRejectedClosingFormUseCase:
    def __init__(self, persistence: ClosingFormPersistencePort):
        self._persistence = persistence

    def execute(self, form_id: int, current_user: CurrentUserPort):
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        status = self._persistence.get_rejected_form_status(form_id)
        if status is None:
            raise NotFoundError("记录不存在")
        if status != "rejected":
            raise ValidationError("仅允许删除不通过状态的表单")
        self._persistence.delete_pending_form(form_id)
        logger.info("删除不通过表单: form_id=%s, deleted_by=%s", form_id, current_user.username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(form_id))


class UploadClosingFormImageUseCase:
    def __init__(self, image_storage: ClosingFormImageStoragePort):
        self._image_storage = image_storage

    def execute(self, file_stream, original_filename, content_type, uploader):
        return self._image_storage.upload_image(file_stream, original_filename, content_type, uploader)
