"""Closing form service adapter — orchestrates persistence, embedding, and storage."""

from __future__ import annotations

from typing import Any

from app.adapters.closing_form.embedding import ClosingFormEmbeddingAdapter
from app.adapters.closing_form.persistence import ClosingFormPersistence
from app.adapters.closing_form.storage import ClosingFormStorageAdapter
from app.core.exceptions import APIException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.ports.domains.closing_form import ClosingFormServicePort

logger = get_logger("closing_form.adapter")


class IntegrationClosingFormAdapter(ClosingFormServicePort):
    def __init__(self):
        self._persistence = ClosingFormPersistence()
        self._embedding = ClosingFormEmbeddingAdapter()
        self._storage = ClosingFormStorageAdapter()

    def submit_closing_form(self, uploader: str, form_data: Any) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormSubmitResponse

        formatted_text = form_data.to_formatted_text()
        result = self._persistence.submit_pending(
            form_text_raw=formatted_text,
            uploader=uploader,
            image_url_1=getattr(form_data, "image_url_1", None),
            image_url_2=getattr(form_data, "image_url_2", None),
        )
        logger.info("填表已暂存至待审批队列: uploader=%s", uploader)
        return ClosingFormSubmitResponse(
            success=True,
            message="提交成功，等待审批",
            form_text=result["form_text"],
            image_url_1=getattr(form_data, "image_url_1", None),
            image_url_2=getattr(form_data, "image_url_2", None),
        )

    def list_merged_forms(self, *, uploader: str, is_privileged: bool) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormListResponse, ClosingFormRecord

        uploader_filter = None if is_privileged else uploader
        pending = self._persistence.list_pending_forms(uploader=uploader_filter)
        approved = self._persistence.list_approved_forms(uploader=uploader_filter)
        records = [
            ClosingFormRecord(**row) for row in pending
        ] + [
            ClosingFormRecord(**row) for row in approved
        ]
        records.sort(key=lambda r: r.upload_time or "", reverse=True)
        logger.info("查询填表记录: user=%s, pending=%d, approved=%d", uploader, len(pending), len(approved))
        return ClosingFormListResponse(success=True, total=len(records), records=records)

    def approve_pending_form(self, form_id: int, approved_by_username: str) -> Any:
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
        logger.info(
            "表单审批通过并移入知识库: form_id=%s, uploader=%s, approved_by=%s",
            form_id, row["uploader"], approved_by_username,
        )
        return ClosingFormApproveResponse(success=True, message="审批通过")

    def reject_pending_form(self, form_id: int, rejected_by_username: str) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormRejectResponse

        row = self._persistence.get_pending_form(form_id)
        if row is None:
            raise NotFoundError("待审批表单不存在")
        if row["status"] != "pending":
            raise ValidationError(f"表单状态不是待审批（当前状态：{row['status']}）")

        self._storage.delete_form_images(row.get("image_url_1"), row.get("image_url_2"))
        self._persistence.reject_pending_form(form_id)
        logger.info(
            "表单审批不通过: form_id=%s, uploader=%s, rejected_by=%s",
            form_id, row["uploader"], rejected_by_username,
        )
        return ClosingFormRejectResponse(success=True, message="审批已拒绝")

    def list_collection2(self) -> Any:
        from app.schemas.endpoints.closing_form import Collection2ListResponse, Collection2Record

        rows = self._persistence.list_collection2_records()
        records = [Collection2Record(**row) for row in rows]
        return Collection2ListResponse(success=True, total=len(records), records=records)

    def delete_collection2_record(self, record_id: int, deleted_by_username: str) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        if not self._persistence.check_collection2_exists(record_id):
            raise NotFoundError("记录不存在")
        rowcount = self._persistence.delete_collection2_record(record_id)
        if rowcount <= 0:
            raise APIException("删除失败，请稍后重试", status_code=500)
        logger.info("删除 data_doc_collection_2 记录: record_id=%s, deleted_by=%s", record_id, deleted_by_username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))

    def delete_approved_closing_form(self, record_id: int, deleted_by_username: str) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        row = self._persistence.get_approved_form(record_id)
        if row is None:
            raise NotFoundError("记录不存在")
        self._storage.delete_form_images(row.get("image_url_1"), row.get("image_url_2"))
        rowcount = self._persistence.delete_approved_form(record_id)
        if rowcount <= 0:
            raise APIException("删除失败，请稍后重试", status_code=500)
        logger.info("删除已通过表单记录: record_id=%s, deleted_by=%s", record_id, deleted_by_username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))

    def delete_rejected_closing_form(self, form_id: int, deleted_by_username: str) -> Any:
        from app.schemas.endpoints.closing_form import ClosingFormDeleteResponse

        status = self._persistence.get_rejected_form_status(form_id)
        if status is None:
            raise NotFoundError("记录不存在")
        if status != "rejected":
            raise ValidationError("仅允许删除不通过状态的表单")
        self._persistence.delete_pending_form(form_id)
        logger.info("删除不通过表单记录: form_id=%s, deleted_by=%s", form_id, deleted_by_username)
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(form_id))

    def upload_closing_form_image(
        self, file_stream: Any, original_filename: str, content_type: str, uploader: str
    ) -> str:
        return self._storage.upload_image(file_stream, original_filename, content_type, uploader)
