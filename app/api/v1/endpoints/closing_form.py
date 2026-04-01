"""
智能组合秤订单填表 API

数据流：
  提交 → data_pending（普通行，无嵌入）
  审批 → data_pending 取出 → embed → data_doc_collection_1 → 删除 data_pending
  列表 → data_pending（pending）+ data_doc_collection_1（approved）合并返回
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user, require_roles
from app.integrations.doc_processing.embedding_store import (
    BGEM3EmbeddingWrapper,
    VectorStoreManager,
)
from app.integrations.doc_processing.exceptions import EmbeddingError, VectorStoreError
from app.integrations.doc_processing.pipeline import clean_text_for_postgres
from app.models.orm.platform.user import User, UserRole
from app.schemas.endpoints.closing_form import (
    ClosingFormApproveResponse,
    ClosingFormDeleteResponse,
    ClosingFormRejectResponse,
    ClosingFormListResponse,
    Collection2ListResponse,
    Collection2Record,
    ClosingFormRecord,
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
)
from llama_index.core.schema import TextNode

router = APIRouter()
logger = get_logger("closing_form")

CLOSING_FORM_TABLE_PREFIX = "doc_collection"
CLOSING_FORM_INSTANCE_ID = 1
_CLOSING_FORM_TABLE = f"data_{CLOSING_FORM_TABLE_PREFIX}_{CLOSING_FORM_INSTANCE_ID}"
_COLLECTION2_TABLE = "data_doc_collection_2"
_PENDING_TABLE = "data_pending"


@router.post("/submit", response_model=ClosingFormSubmitResponse)
def submit_closing_form(
    form_data: ClosingFormSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    提交表单，写入 data_pending 暂存，不触发嵌入。
    提交者身份由 JWT 令牌确定，不可伪造。
    """
    try:
        uploader = current_user.username
        form_text = clean_text_for_postgres(form_data.to_formatted_text())
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db.execute(
            text(
                f"INSERT INTO {_PENDING_TABLE} (text, uploader, upload_time, status)"
                " VALUES (:t, :u, :ts, :st)"
            ),
            {"t": form_text, "u": uploader, "ts": upload_time, "st": "pending"},
        )
        # get_db 自动提交

        logger.info("填表已暂存至待审批队列: uploader=%s, upload_time=%s", uploader, upload_time)
        return ClosingFormSubmitResponse(
            success=True,
            message="提交成功，等待审批",
            form_text=form_text,
        )

    except Exception as e:
        logger.exception("填表提交失败")
        raise HTTPException(status_code=500, detail="提交失败，请稍后重试")


@router.get("/list", response_model=ClosingFormListResponse)
def list_closing_forms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    查询表单记录，合并 data_pending（待审批）和 data_doc_collection_1（已通过）。
    - admin / superuser：返回全部记录
    - user：仅返回当前登录用户的记录
    """
    try:
        is_privileged = current_user.role in (UserRole.admin, UserRole.superuser)

        # ---------- data_pending (status = pending 或 rejected) ----------
        if is_privileged:
            pending_rows = db.execute(
                text(
                    f"SELECT id, text, uploader, upload_time, status"
                    f" FROM {_PENDING_TABLE}"
                    f" ORDER BY upload_time DESC"
                )
            ).fetchall()
        else:
            pending_rows = db.execute(
                text(
                    f"SELECT id, text, uploader, upload_time, status"
                    f" FROM {_PENDING_TABLE}"
                    f" WHERE uploader = :uploader"
                    f" ORDER BY upload_time DESC"
                ),
                {"uploader": current_user.username},
            ).fetchall()

        # ---------- data_doc_collection_1 (status = approved) ----------
        if is_privileged:
            approved_rows = db.execute(
                text(
                    f"SELECT id, text,"
                    f" metadata_->>'upload_time' AS upload_time,"
                    f" metadata_->>'uploader'   AS uploader"
                    f" FROM {_CLOSING_FORM_TABLE}"
                    f" ORDER BY metadata_->>'upload_time' DESC"
                )
            ).fetchall()
        else:
            approved_rows = db.execute(
                text(
                    f"SELECT id, text,"
                    f" metadata_->>'upload_time' AS upload_time,"
                    f" metadata_->>'uploader'   AS uploader"
                    f" FROM {_CLOSING_FORM_TABLE}"
                    f" WHERE metadata_->>'uploader' = :uploader"
                    f" ORDER BY metadata_->>'upload_time' DESC"
                ),
                {"uploader": current_user.username},
            ).fetchall()

        records = [
            ClosingFormRecord(
                id=str(row.id),
                text=row.text or "",
                upload_time=row.upload_time,
                uploader=row.uploader or "",
                status=getattr(row, "status", "pending"),
            )
            for row in pending_rows
        ] + [
            ClosingFormRecord(
                id=str(row.id),
                text=row.text or "",
                upload_time=row.upload_time,
                uploader=row.uploader or "",
                status="approved",
            )
            for row in approved_rows
        ]

        # 按 upload_time 倒序排列（ISO 格式字符串可直接比较）
        records.sort(key=lambda r: r.upload_time or "", reverse=True)

        logger.info(
            "查询填表记录: user=%s, role=%s, pending=%d, approved=%d",
            current_user.username,
            current_user.role.value,
            len(pending_rows),
            len(approved_rows),
        )
        return ClosingFormListResponse(success=True, total=len(records), records=records)

    except Exception as e:
        logger.exception("查询填表记录失败")
        raise HTTPException(status_code=500, detail="查询失败，请稍后重试")


@router.patch(
    "/approve/{form_id}",
    response_model=ClosingFormApproveResponse,
    summary="审批通过表单（admin / superuser 专属）",
)
def approve_closing_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.superuser)),
):
    """
    四步移表流程：
    1. 从 data_pending 取出记录
    2. 向量化并写入 data_doc_collection_1
    3. 仅在嵌入成功后删除 data_pending 记录
    若嵌入失败，pending 记录原样保留，可重试。
    """
    # Step 1: 取出待审批记录
    row = db.execute(
        text(
            f"SELECT id, text, uploader, upload_time, status"
            f" FROM {_PENDING_TABLE}"
            f" WHERE id = :id"
        ),
        {"id": form_id},
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="待审批表单不存在",
        )
    
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"表单状态不是待审批（当前状态：{row.status}）",
        )

    # Step 2: 向量化并写入 data_doc_collection_1
    try:
        node = TextNode(
            text=row.text,
            metadata={
                "uploader": row.uploader,
                "upload_time": row.upload_time,
                "status": "approved",
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
        raise HTTPException(status_code=503, detail="嵌入服务暂时不可用，表单已保留，请稍后重试")
    except VectorStoreError as e:
        logger.error("审批写入向量存储失败，pending 记录已保留: form_id=%s, error=%s", form_id, e)
        raise HTTPException(status_code=500, detail="写入知识库失败，表单已保留，请稍后重试")
    except Exception as e:
        logger.exception("审批嵌入阶段异常，pending 记录已保留: form_id=%s", form_id)
        raise HTTPException(status_code=500, detail="审批失败，表单已保留，请稍后重试")

    # Step 3: 嵌入成功，删除 data_pending 记录
    db.execute(
        text(f"DELETE FROM {_PENDING_TABLE} WHERE id = :id"),
        {"id": form_id},
    )
    # get_db 自动提交

    logger.info(
        "表单审批通过并移入知识库: form_id=%s, uploader=%s, approved_by=%s",
        form_id,
        row.uploader,
        current_user.username,
    )
    return ClosingFormApproveResponse(success=True, message="审批通过")


@router.patch(
    "/reject/{form_id}",
    response_model=ClosingFormRejectResponse,
    summary="审批不通过表单（admin / superuser 专属）",
)
def reject_closing_form(
    form_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.superuser)),
):
    """
    表单审批不通过：
    保留在 data_pending 表中，将状态标记为 rejected。
    不进行向量化处理，不可进入 data_doc_collection_1。
    """
    row = db.execute(
        text(
            f"SELECT id, uploader, status"
            f" FROM {_PENDING_TABLE}"
            f" WHERE id = :id"
        ),
        {"id": form_id},
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="待审批表单不存在",
        )
        
    if getattr(row, "status", "pending") != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"表单状态不是待审批（当前状态：{getattr(row, 'status', 'pending')}）",
        )

    db.execute(
        text(f"UPDATE {_PENDING_TABLE} SET status = 'rejected' WHERE id = :id"),
        {"id": form_id},
    )
    # get_db 自动提交

    logger.info(
        "表单审批不通过: form_id=%s, uploader=%s, rejected_by=%s",
        form_id,
        row.uploader,
        current_user.username,
    )
    return ClosingFormRejectResponse(success=True, message="审批已拒绝")


@router.get(
    "/collection2/list",
    response_model=Collection2ListResponse,
    summary="获取 data_doc_collection_2 列表（admin / superuser）",
)
def list_collection2_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.superuser)),
):
    """
    列出 data_doc_collection_2 记录（仅 admin / superuser）。
    """
    _ = current_user
    try:
        rows = db.execute(
            text(
                f"SELECT id, text,"
                f" COALESCE(metadata_->>'file_name', metadata_->>'source', metadata_->>'title') AS file_name,"
                f" metadata_->>'upload_time' AS upload_time,"
                f" metadata_->>'uploader'   AS uploader"
                f" FROM {_COLLECTION2_TABLE}"
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
    except Exception:
        logger.exception("查询 data_doc_collection_2 列表失败")
        raise HTTPException(status_code=500, detail="查询失败，请稍后重试")


@router.delete(
    "/collection2/{record_id}",
    response_model=ClosingFormDeleteResponse,
    summary="删除 data_doc_collection_2 记录（admin / superuser）",
)
def delete_collection2_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.superuser)),
):
    """
    删除 data_doc_collection_2 中的单条记录（物理删除）。
    """
    try:
        exists = db.execute(
            text(f"SELECT id FROM {_COLLECTION2_TABLE} WHERE id = :id"),
            {"id": record_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")

        delete_result = db.execute(
            text(f"DELETE FROM {_COLLECTION2_TABLE} WHERE id = :id"),
            {"id": record_id},
        )
        if (delete_result.rowcount or 0) <= 0:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除失败，请稍后重试")

        logger.info(
            "删除 data_doc_collection_2 记录: record_id=%s, deleted_by=%s",
            record_id,
            current_user.username,
        )
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除 data_doc_collection_2 记录失败: record_id=%s", record_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")


@router.delete(
    "/approved/{record_id}",
    response_model=ClosingFormDeleteResponse,
    summary="删除已通过表单（superuser 专属）",
)
def delete_approved_closing_form(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.superuser)),
):
    """
    删除 data_doc_collection_1 中的已通过表单（物理删除，仅 superuser）。
    """
    try:
        exists = db.execute(
            text(f"SELECT id FROM {_CLOSING_FORM_TABLE} WHERE id = :id"),
            {"id": record_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")

        delete_result = db.execute(
            text(f"DELETE FROM {_CLOSING_FORM_TABLE} WHERE id = :id"),
            {"id": record_id},
        )
        if (delete_result.rowcount or 0) <= 0:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除失败，请稍后重试")

        logger.info(
            "删除已通过表单记录: record_id=%s, deleted_by=%s",
            record_id,
            current_user.username,
        )
        return ClosingFormDeleteResponse(success=True, message="删除成功", deleted_id=str(record_id))
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除已通过表单记录失败: record_id=%s", record_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")
