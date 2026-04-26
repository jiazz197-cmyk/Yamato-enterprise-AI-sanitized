"""
智能组合秤订单填表 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.closing_form import IntegrationClosingFormAdapter
from app.core.dependencies import get_db
from app.core.exceptions import APIException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import get_current_user, require_roles
from app.models.orm.platform.user import User, UserRole
from app.schemas.endpoints.closing_form import (
    ClosingFormApproveResponse,
    ClosingFormDeleteResponse,
    ClosingFormListResponse,
    ClosingFormRejectResponse,
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
    Collection2ListResponse,
)
from app.usecases.closing_form.operations import (
    ApproveClosingFormUseCase,
    DeleteApprovedClosingFormUseCase,
    DeleteCollection2RecordUseCase,
    ListClosingFormsUseCase,
    ListCollection2UseCase,
    RejectClosingFormUseCase,
    SubmitClosingFormUseCase,
)

router = APIRouter()
logger = get_logger("closing_form")

_svc = IntegrationClosingFormAdapter()


@router.post("/submit", response_model=ClosingFormSubmitResponse)
def submit_closing_form(
    form_data: ClosingFormSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return SubmitClosingFormUseCase(_svc).execute(db, current_user, form_data)
    except Exception:
        logger.exception("填表提交失败")
        raise HTTPException(status_code=500, detail="提交失败，请稍后重试")


@router.get("/list", response_model=ClosingFormListResponse)
def list_closing_forms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return ListClosingFormsUseCase(_svc).execute(db, current_user)
    except Exception:
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
    try:
        return ApproveClosingFormUseCase(_svc).execute(db, form_id, current_user)
    except (NotFoundError, ValidationError, APIException):
        raise
    except Exception:
        logger.exception("审批失败: form_id=%s", form_id)
        raise HTTPException(status_code=500, detail="审批失败，请稍后重试")


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
    try:
        return RejectClosingFormUseCase(_svc).execute(db, form_id, current_user)
    except (NotFoundError, ValidationError, APIException):
        raise
    except Exception:
        logger.exception("拒绝审批失败: form_id=%s", form_id)
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.get(
    "/collection2/list",
    response_model=Collection2ListResponse,
    summary="获取 data_doc_collection_2 列表（admin / superuser）",
)
def list_collection2_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.superuser)),
):
    _ = current_user
    try:
        return ListCollection2UseCase(_svc).execute(db)
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
    try:
        return DeleteCollection2RecordUseCase(_svc).execute(db, record_id, current_user)
    except (NotFoundError, APIException):
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
    try:
        return DeleteApprovedClosingFormUseCase(_svc).execute(db, record_id, current_user)
    except (NotFoundError, APIException):
        raise
    except Exception:
        logger.exception("删除已通过表单记录失败: record_id=%s", record_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")
