"""
智能组合秤订单填表 API
"""
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from minio.error import S3Error

from app.adapters.closing_form import IntegrationClosingFormAdapter
from app.core.config import settings
from app.core.exceptions import APIException, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import get_current_user, require_roles
from app.core.storage import (
    MINIO_BUCKET_NAME,
    delete_from_minio,
    download_object_stream,
    get_minio_client,
)
from app.ports.contracts.identity import CurrentUserPort, ROLE_SUPERUSER, ROLE_ADMIN
from app.ports.dto.closing_form import ClosingFormCommand
from app.schemas.endpoints.closing_form import (
    ClosingFormApproveResponse,
    ClosingFormDeleteResponse,
    ClosingFormListResponse,
    ClosingFormRejectResponse,
    ClosingFormSubmit,
    ClosingFormSubmitResponse,
    Collection2ListResponse,
    ImageUploadResponse,
)
from app.usecases.closing_form.operations import (
    ApproveClosingFormUseCase,
    DeleteApprovedClosingFormUseCase,
    DeleteCollection2RecordUseCase,
    DeleteRejectedClosingFormUseCase,
    ListClosingFormsUseCase,
    ListCollection2UseCase,
    RejectClosingFormUseCase,
    SubmitClosingFormUseCase,
    UploadClosingFormImageUseCase,
)

router = APIRouter()
logger = get_logger("closing_form")

try:
    _svc = IntegrationClosingFormAdapter()
except Exception as e:
    logger.critical("ClosingFormAdapter 初始化失败: %s", e, exc_info=True)
    raise

# 诊断端点：验证 adapter 和 persistence 是否正常
@router.get("/_diag", summary="内部诊断", include_in_schema=False)
def diag():
    try:
        pending = _svc._persistence.list_pending_forms()
        approved = _svc._persistence.list_approved_forms()
        return {
            "adapter": type(_svc).__name__,
            "pending_count": len(pending),
            "approved_count": len(approved),
            "sample_approved": approved[0] if approved else None,
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@router.get("/image/{object_name:path}")
def get_closing_form_image(object_name: str):
    """下载/预览报单图片（根据 MinIO object name 流式返回）"""
    if not object_name.startswith(f"{settings.CLOSING_FORM_IMAGE_PREFIX}/"):
        logger.warning("非法图片访问路径: object=%s", object_name)
        raise HTTPException(status_code=400, detail="非法的图片路径")

    ext = Path(object_name).suffix.lower()
    content_type_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp",
    }
    content_type = content_type_map.get(ext, "application/octet-stream")

    try:
        get_minio_client().stat_object(MINIO_BUCKET_NAME, object_name)
        logger.info("报单图片存在，开始流式返回: object=%s", object_name)
    except S3Error as e:
        if e.code in {"NoSuchKey", "NoSuchObject", "NoSuchVersion"}:
            logger.warning("报单图片不存在: object=%s, code=%s", object_name, e.code)
            raise HTTPException(status_code=404, detail="图片不存在或已删除")
        logger.error(
            "报单图片预检失败: object=%s, code=%s, message=%s",
            object_name,
            e.code,
            e.message,
        )
        raise HTTPException(status_code=500, detail="图片读取失败")
    except Exception:
        logger.exception("报单图片预检异常: object=%s", object_name)
        raise HTTPException(status_code=500, detail="图片读取失败")

    def iter_image_bytes():
        try:
            with download_object_stream(object_name) as stream:
                for chunk in stream.stream(1024 * 1024):
                    yield chunk
        except S3Error as e:
            logger.error(
                "报单图片流式读取失败: object=%s, code=%s, message=%s",
                object_name,
                e.code,
                e.message,
            )
            raise
        except Exception:
            logger.exception("报单图片流式读取异常: object=%s", object_name)
            raise

    raw_filename = Path(object_name).name
    encoded_filename = quote(raw_filename, safe="")
    return StreamingResponse(
        iter_image_bytes(),
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        },
    )


@router.post("/image/upload", response_model=ImageUploadResponse)
def upload_closing_form_image(
    image: UploadFile = File(...),
    current_user: CurrentUserPort = Depends(get_current_user),
):
    """上传报单图片到 MinIO(form_pic/)，返回 object_name"""
    if not image.filename:
        raise HTTPException(status_code=400, detail="图片文件名为空")
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只允许上传图片文件")

    try:
        object_name = UploadClosingFormImageUseCase(_svc).execute(
            file_stream=image.file,
            original_filename=image.filename,
            content_type=image.content_type or "image/jpeg",
            uploader=current_user.username,
        )
        return ImageUploadResponse(success=True, object_name=object_name)
    except RuntimeError as e:
        logger.error("图片上传 MinIO 失败: %s", e)
        raise HTTPException(status_code=500, detail="图片上传失败")
    except Exception:
        logger.exception("图片上传异常")
        raise HTTPException(status_code=500, detail="图片上传失败")


@router.delete("/image")
def delete_closing_form_image(
    object_name: str = Query(..., description="MinIO object name"),
    current_user: CurrentUserPort = Depends(get_current_user),
):
    """删除已上传的报单图片（仅限配置的前缀，防越权）"""
    if not object_name.startswith(f"{settings.CLOSING_FORM_IMAGE_PREFIX}/"):
        raise HTTPException(status_code=400, detail="非法的图片路径")

    ok = delete_from_minio(object_name)
    if not ok:
        logger.warning("删除图片失败（MinIO 返回 False）: %s", object_name)
    return {"success": True, "message": "已删除"}


@router.post("/submit", response_model=ClosingFormSubmitResponse)
def submit_closing_form(
    form_data: ClosingFormSubmit,
    current_user: CurrentUserPort = Depends(get_current_user),
):
    cmd = ClosingFormCommand(
        date=form_data.date,
        deal_time=form_data.closing_date,
        customer_name=form_data.customer_name,
        product_type=form_data.product_type,
        model_spec=form_data.model_spec,
        quantity=form_data.quantity,
        original_price=form_data.price_excluding_tax,
        production_code=form_data.production_number,
        material_name=form_data.material_name,
        weighing_spec=form_data.weighing_spec,
        speed=str(form_data.speed) if form_data.speed is not None else None,
        accuracy=form_data.precision,
        top_cone_type=form_data.top_cone_type,
        linear_vibrator_type=form_data.linear_vibration_type,
        layer_adjustment_ring=form_data.material_layer_ring,
        feeding_hopper=form_data.feed_hopper,
        weigh_bucket=form_data.metering_hopper,
        memory_bucket=form_data.memory_hopper,
        chute_angle=form_data.chute_angle,
        collecting_cone_type=form_data.collection_hopper_type,
        scale_config=form_data.scale_type,
        image_urls=[url for url in (form_data.image_url_1, form_data.image_url_2) if url],
    )
    try:
        return SubmitClosingFormUseCase(_svc).execute(current_user, cmd)
    except Exception:
        logger.exception("填表提交失败")
        raise HTTPException(status_code=500, detail="提交失败，请稍后重试")


@router.get("/list", response_model=ClosingFormListResponse)
def list_closing_forms(
    current_user: CurrentUserPort = Depends(get_current_user),
):
    try:
        result = ListClosingFormsUseCase(_svc).execute(current_user)
        logger.debug("列表查询成功: user=%s records=%d", current_user.username, result.total)
        return result
    except Exception:
        logger.exception("查询填表记录失败: user=%s", current_user.username)
        raise HTTPException(status_code=500, detail="查询失败，请稍后重试")


@router.patch(
    "/approve/{form_id}",
    response_model=ClosingFormApproveResponse,
    summary="审批通过表单（admin / superuser 专属）",
)
def approve_closing_form(
    form_id: int,
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    try:
        return ApproveClosingFormUseCase(_svc).execute(form_id, current_user)
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
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    try:
        return RejectClosingFormUseCase(_svc).execute(form_id, current_user)
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
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    _ = current_user
    try:
        return ListCollection2UseCase(_svc).execute()
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
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    try:
        return DeleteCollection2RecordUseCase(_svc).execute(record_id, current_user)
    except (NotFoundError, APIException):
        raise
    except Exception:
        logger.exception("删除 data_doc_collection_2 记录失败: record_id=%s", record_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")


@router.delete(
    "/rejected/{form_id}",
    response_model=ClosingFormDeleteResponse,
    summary="删除不通过表单（admin / superuser 专属）",
)
def delete_rejected_closing_form(
    form_id: int,
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    try:
        return DeleteRejectedClosingFormUseCase(_svc).execute(form_id, current_user)
    except (NotFoundError, APIException):
        raise
    except Exception:
        logger.exception("删除不通过表单记录失败: form_id=%s", form_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")


@router.delete(
    "/approved/{record_id}",
    response_model=ClosingFormDeleteResponse,
    summary="删除已通过表单（admin / superuser 专属）",
)
def delete_approved_closing_form(
    record_id: int,
    current_user: CurrentUserPort = Depends(require_roles(ROLE_ADMIN, ROLE_SUPERUSER)),
):
    try:
        return DeleteApprovedClosingFormUseCase(_svc).execute(record_id, current_user)
    except (NotFoundError, APIException):
        raise
    except Exception:
        logger.exception("删除已通过表单记录失败: record_id=%s", record_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")
