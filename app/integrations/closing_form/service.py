"""Closing form: pending table + doc_collection embedding. No HTTP types."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from llama_index.core.schema import TextNode
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import delete_from_minio, upload_stream_to_minio
from app.integrations.closing_form.constants import (
    CLOSING_FORM_INSTANCE_ID,
    CLOSING_FORM_TABLE,
    CLOSING_FORM_TABLE_PREFIX,
    COLLECTION2_TABLE,
    PENDING_TABLE,
)
from app.integrations.doc_processing.embedding_store import (
    BGEM3EmbeddingWrapper,
    VectorStoreManager,
)
from app.integrations.doc_processing.exceptions import EmbeddingError, VectorStoreError
from app.integrations.doc_processing.pipeline import clean_text_for_postgres
from app.schemas.endpoints.closing_form import (
    ClosingFormApproveResponse,
    ClosingFormDeleteResponse,
    ClosingFormListResponse,
    ClosingFormRecord,
    ClosingFormRejectResponse,
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
    Collection2ListResponse,
    Collection2Record,
)

logger = get_logger("closing_form")

_embed_fail_msg = "嵌入服务暂时不可用，表单已保留，请稍后重试"
_vector_fail_msg = "写入知识库失败，表单已保留，请稍后重试"
_generic_approve_fail = "审批失败，表单已保留，请稍后重试"


def upload_closing_form_image(
    file_stream, original_filename: str, content_type: str, uploader: str
) -> str:
    """上传报单图片到 MinIO，返回 object_name"""
    prefix = settings.CLOSING_FORM_IMAGE_PREFIX
    ext = Path(original_filename).suffix or ".jpg"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = f"{ts}_{uuid4().hex}{ext}"
    object_name = f"{prefix}/{uploader}_{unique_name}"

    result = upload_stream_to_minio(file_stream, object_name, content_type=content_type)
    if result.startswith("Error"):
        raise RuntimeError(result)

    logger.info("上传报单图片成功: user=%s, object=%s", uploader, object_name)
    return object_name


def submit_closing_form(db: Session, uploader: str, form_data: ClosingFormSubmit) -> ClosingFormSubmitResponse:
    form_text = clean_text_for_postgres(form_data.to_formatted_text())
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        text(
            f"INSERT INTO {PENDING_TABLE} "
            "(text, uploader, upload_time, status, image_url_1, image_url_2)"
            " VALUES (:t, :u, :ts, :st, :img1, :img2)"
        ),
        {
            "t": form_text, "u": uploader, "ts": upload_time, "st": "pending",
            "img1": form_data.image_url_1,
            "img2": form_data.image_url_2,
        },
    )
    logger.info("填表已暂存至待审批队列: uploader=%s, upload_time=%s", uploader, upload_time)
    return ClosingFormSubmitResponse(
        success=True,
        message="提交成功，等待审批",
        form_text=form_text,
        image_url_1=form_data.image_url_1,
        image_url_2=form_data.image_url_2,
    )


def list_merged_forms(
    db: Session, *, uploader: str, is_privileged: bool
) -> ClosingFormListResponse:
    if is_privileged:
        pending_rows = db.execute(
            text(
                f"SELECT id, text, uploader, upload_time, status, image_url_1, image_url_2"
                f" FROM {PENDING_TABLE}"
                f" ORDER BY upload_time DESC"
            )
        ).fetchall()
    else:
        pending_rows = db.execute(
            text(
                f"SELECT id, text, uploader, upload_time, status, image_url_1, image_url_2"
                f" FROM {PENDING_TABLE}"
                f" WHERE uploader = :uploader"
                f" ORDER BY upload_time DESC"
            ),
            {"uploader": uploader},
        ).fetchall()

    if is_privileged:
        approved_rows = db.execute(
            text(
                f"SELECT id, text,"
                f" metadata_->>'upload_time' AS upload_time,"
                f" metadata_->>'uploader'   AS uploader,"
                f" metadata_->>'image_url_1' AS image_url_1,"
                f" metadata_->>'image_url_2' AS image_url_2"
                f" FROM {CLOSING_FORM_TABLE}"
                f" ORDER BY metadata_->>'upload_time' DESC"
            )
        ).fetchall()
    else:
        approved_rows = db.execute(
            text(
                f"SELECT id, text,"
                f" metadata_->>'upload_time' AS upload_time,"
                f" metadata_->>'uploader'   AS uploader,"
                f" metadata_->>'image_url_1' AS image_url_1,"
                f" metadata_->>'image_url_2' AS image_url_2"
                f" FROM {CLOSING_FORM_TABLE}"
                f" WHERE metadata_->>'uploader' = :uploader"
                f" ORDER BY metadata_->>'upload_time' DESC"
            ),
            {"uploader": uploader},
        ).fetchall()

    records: List[ClosingFormRecord] = [
        ClosingFormRecord(
            id=str(row.id),
            text=row.text or "",
            upload_time=row.upload_time,
            uploader=row.uploader or "",
            status=getattr(row, "status", "pending"),
            image_url_1=getattr(row, "image_url_1", None) or None,
            image_url_2=getattr(row, "image_url_2", None) or None,
        )
        for row in pending_rows
    ] + [
        ClosingFormRecord(
            id=str(row.id),
            text=row.text or "",
            upload_time=row.upload_time,
            uploader=row.uploader or "",
            status="approved",
            image_url_1=getattr(row, "image_url_1", None) or None,
            image_url_2=getattr(row, "image_url_2", None) or None,
        )
        for row in approved_rows
    ]
    records.sort(key=lambda r: r.upload_time or "", reverse=True)
    logger.info(
        "查询填表记录: user=%s, pending=%d, approved=%d",
        uploader,
        len(pending_rows),
        len(approved_rows),
    )
    return ClosingFormListResponse(success=True, total=len(records), records=records)


def approve_pending_form(
    db: Session, form_id: int, approved_by_username: str
) -> ClosingFormApproveResponse:
    row = db.execute(
        text(
            f"SELECT id, text, uploader, upload_time, status, image_url_1, image_url_2"
            f" FROM {PENDING_TABLE}"
            f" WHERE id = :id"
        ),
        {"id": form_id},
    ).first()
    if row is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("待审批表单不存在")
    if row.status != "pending":
        from app.core.exceptions import ValidationError
        raise ValidationError(
            f"表单状态不是待审批（当前状态：{row.status}）"
        )
    try:
        node = TextNode(
            text=row.text,
            metadata={
                "uploader": row.uploader,
                "upload_time": row.upload_time,
                "status": "approved",
                "image_url_1": row.image_url_1 or "",
                "image_url_2": row.image_url_2 or "",
            },
        )
        db_config = {
            "host": settings.POSTGRES_SERVER,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "database": settings.POSTGRES_DB,
            "port": settings.POSTGRES_PORT,
        }
        embedding_model = BGEM3EmbeddingWrapper()
        vector_store_manager = VectorStoreManager(
            db_config=db_config,
            table_prefix=CLOSING_FORM_TABLE_PREFIX,
        )
        vector_store_manager.upsert_chunks(
            chunks=[node],
            instance_id=CLOSING_FORM_INSTANCE_ID,
            embedding_model=embedding_model,
        )
    except EmbeddingError as e:
        logger.error("审批嵌入失败，pending 记录已保留: form_id=%s, error=%s", form_id, e)
        from app.core.exceptions import APIException
        raise APIException(_embed_fail_msg, status_code=503) from e
    except VectorStoreError as e:
        logger.error("审批写入向量存储失败，pending 记录已保留: form_id=%s, error=%s", form_id, e)
        from app.core.exceptions import APIException
        raise APIException(_vector_fail_msg, status_code=500) from e
    except Exception:
        logger.exception("审批嵌入阶段异常，pending 记录已保留: form_id=%s", form_id)
        from app.core.exceptions import APIException
        raise APIException(_generic_approve_fail, status_code=500) from None

    db.execute(
        text(f"DELETE FROM {PENDING_TABLE} WHERE id = :id"),
        {"id": form_id},
    )
    logger.info(
        "表单审批通过并移入知识库: form_id=%s, uploader=%s, approved_by=%s",
        form_id,
        row.uploader,
        approved_by_username,
    )
    return ClosingFormApproveResponse(success=True, message="审批通过")


def reject_pending_form(db: Session, form_id: int, rejected_by_username: str) -> ClosingFormRejectResponse:
    row = db.execute(
        text(
            f"SELECT id, uploader, status, image_url_1, image_url_2"
            f" FROM {PENDING_TABLE}"
            f" WHERE id = :id"
        ),
        {"id": form_id},
    ).first()
    if row is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("待审批表单不存在")
    if getattr(row, "status", "pending") != "pending":
        from app.core.exceptions import ValidationError
        raise ValidationError(
            f"表单状态不是待审批（当前状态：{getattr(row, 'status', 'pending')}）"
        )

    _delete_form_images(row.image_url_1, row.image_url_2)

    db.execute(
        text(f"UPDATE {PENDING_TABLE} SET status = 'rejected',"
             f" image_url_1 = NULL, image_url_2 = NULL WHERE id = :id"),
        {"id": form_id},
    )
    logger.info(
        "表单审批不通过: form_id=%s, uploader=%s, rejected_by=%s",
        form_id,
        row.uploader,
        rejected_by_username,
    )
    return ClosingFormRejectResponse(success=True, message="审批已拒绝")


def delete_rejected_closing_form(
    db: Session, form_id: int, deleted_by_username: str
) -> ClosingFormDeleteResponse:
    row = db.execute(
        text(f"SELECT id, status FROM {PENDING_TABLE} WHERE id = :id"),
        {"id": form_id},
    ).first()
    if row is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("记录不存在")
    if getattr(row, "status", "") != "rejected":
        from app.core.exceptions import ValidationError
        raise ValidationError("仅允许删除不通过状态的表单")

    db.execute(text(f"DELETE FROM {PENDING_TABLE} WHERE id = :id"), {"id": form_id})
    logger.info(
        "删除不通过表单记录: form_id=%s, deleted_by=%s",
        form_id,
        deleted_by_username,
    )
    return ClosingFormDeleteResponse(
        success=True, message="删除成功", deleted_id=str(form_id)
    )


def list_collection2(db: Session) -> Collection2ListResponse:
    rows = db.execute(
        text(
            f"SELECT id, text,"
            f" COALESCE(metadata_->>'file_name', metadata_->>'source', metadata_->>'title') AS file_name,"
            f" metadata_->>'upload_time' AS upload_time,"
            f" metadata_->>'uploader'   AS uploader"
            f" FROM {COLLECTION2_TABLE}"
            f" ORDER BY metadata_->>'upload_time' DESC NULLS LAST, id DESC"
        )
    ).fetchall()
    records = [
        Collection2Record(
            id=str(row.id),
            text=row.text or "",
            file_name=getattr(row, "file_name", None),
            upload_time=row.upload_time,
            uploader=row.uploader or "",
            status="approved",
        )
        for row in rows
    ]
    return Collection2ListResponse(success=True, total=len(records), records=records)


def delete_collection2_record(
    db: Session, record_id: int, deleted_by_username: str
) -> ClosingFormDeleteResponse:
    exists = db.execute(
        text(f"SELECT id FROM {COLLECTION2_TABLE} WHERE id = :id"),
        {"id": record_id},
    ).first()
    if exists is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("记录不存在")
    delete_result = db.execute(
        text(f"DELETE FROM {COLLECTION2_TABLE} WHERE id = :id"),
        {"id": record_id},
    )
    if (delete_result.rowcount or 0) <= 0:
        from app.core.exceptions import APIException
        raise APIException("删除失败，请稍后重试", status_code=500)
    logger.info(
        "删除 data_doc_collection_2 记录: record_id=%s, deleted_by=%s",
        record_id,
        deleted_by_username,
    )
    return ClosingFormDeleteResponse(
        success=True, message="删除成功", deleted_id=str(record_id)
    )


def delete_approved_closing_form(
    db: Session, record_id: int, deleted_by_username: str
) -> ClosingFormDeleteResponse:
    row = db.execute(
        text(f"SELECT id, metadata_->>'image_url_1' AS image_url_1,"
             f" metadata_->>'image_url_2' AS image_url_2"
             f" FROM {CLOSING_FORM_TABLE} WHERE id = :id"),
        {"id": record_id},
    ).first()
    if row is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("记录不存在")

    _delete_form_images(row.image_url_1, row.image_url_2)

    delete_result = db.execute(
        text(f"DELETE FROM {CLOSING_FORM_TABLE} WHERE id = :id"),
        {"id": record_id},
    )
    if (delete_result.rowcount or 0) <= 0:
        from app.core.exceptions import APIException
        raise APIException("删除失败，请稍后重试", status_code=500)
    logger.info(
        "删除已通过表单记录: record_id=%s, deleted_by=%s",
        record_id,
        deleted_by_username,
    )
    return ClosingFormDeleteResponse(
        success=True, message="删除成功", deleted_id=str(record_id)
    )


def _delete_form_images(*image_urls: Optional[str]) -> None:
    """删除表单关联的 MinIO 图片。

    与 file_manager 的 delete_file_and_object 策略一致：
    - MinIO 删除失败仅打 warning，不抛异常
    - 业务操作（删除表单/拒绝审批）不受影响
    - 孤儿文件可通过 form_pic/ 前缀定期批量清理
    """
    for url in image_urls:
        if not url:
            continue
        if not delete_from_minio(url):
            logger.warning(
                "MinIO 图片删除失败（已继续业务流程）: object=%s", url
            )
        else:
            logger.debug("已删除 MinIO 图片: %s", url)
