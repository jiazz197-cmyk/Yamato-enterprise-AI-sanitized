import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, File, UploadFile, Query, Depends, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.executor import executor_manager
from app.core.security import get_current_user, normalize_self_uploader
from app.integrations.ocr.pdf2image import get_pdf_page_count
from app.integrations.ocr.pdf_convert_tasks import background_pdf_convert_task
from app.models.orm.platform.user import User, UserRole

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_PDF_TYPES = {
    "application/pdf",
}


class PdfConvertRequest(BaseModel):
    dpi: Optional[int] = Field(default=200, ge=72, le=600, description="DPI resolution (72-600)")
    quality: Optional[int] = Field(default=85, ge=1, le=100, description="JPEG quality (1-100)")
    first_page: Optional[int] = Field(default=None, ge=1, description="First page to convert (1-indexed)")
    last_page: Optional[int] = Field(default=None, ge=1, description="Last page to convert (1-indexed)")
    upload_to_minio: Optional[bool] = Field(default=True, description="Upload images to MinIO")
    file_name_prefix: Optional[str] = Field(default=None, description="Filename prefix for MinIO")


class PdfConvertResponse(BaseModel):
    task_id: str
    status: str
    message: str


@router.post("/pdf/convert", response_model=PdfConvertResponse)
async def convert_pdf_to_images(
    file: UploadFile = File(...),
    request: PdfConvertRequest = PdfConvertRequest(),
    uploader: str = Query(default="anonymous", description="上传者标识（仅允许传本人信息）"),
    current_user: User = Depends(get_current_user),
) -> PdfConvertResponse:
    try:
        logger.info("收到 PDF 转图片请求: %s", file.filename)
        if file.content_type not in SUPPORTED_PDF_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 PDF 文件",
            )
        file_data = await file.read()
        file_size_mb = len(file_data) / (1024 * 1024)
        if file_size_mb > 100:
            raise HTTPException(
                status_code=400,
                detail=f"文件过大: {file_size_mb:.2f} MB，最大支持 100 MB",
            )
        logger.info("PDF 文件大小: %.2f MB", file_size_mb)
        normalized_uploader = normalize_self_uploader(uploader, current_user)
        task_id = executor_manager.generate_task_id("pdf_convert")
        executor_manager.set_task_owner(task_id, str(current_user.id))
        executor_manager.submit_task(
            task_id,
            background_pdf_convert_task,
            task_id,
            file_data,
            file.filename,
            request.dpi,
            request.quality,
            request.first_page,
            request.last_page,
            request.upload_to_minio,
            request.file_name_prefix,
            normalized_uploader,
        )
        logger.info("启动 PDF 转图片任务: %s", task_id)
        return PdfConvertResponse(
            task_id=task_id,
            status="started",
            message="PDF 转图片任务已启动，请通过 task_id 查询结果",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("启动 PDF 转图片任务失败: %s", e)
        raise HTTPException(status_code=500, detail="启动转换任务失败")


@router.get("/pdf/task/{task_id}")
async def get_pdf_convert_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        logger.debug("查询 PDF 转图片任务状态: %s", task_id)
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        owner_id = executor_manager.get_task_owner(task_id)
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务")
        if not future.done():
            return {
                "task_id": task_id,
                "status": "running",
                "message": "任务正在执行中",
            }
        try:
            result = future.result(timeout=0.1)
            if isinstance(result, dict) and result.get("status") == "cancelled":
                return {
                    "task_id": task_id,
                    "status": "cancelled",
                    "message": result.get("message", "任务已取消"),
                }
            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "message": result.get("message", "任务执行失败"),
                    "error": result.get("error"),
                }
            return {
                "task_id": task_id,
                "status": "completed",
                "message": "任务完成",
                "result": result,
            }
        except Exception as e:
            logger.error("任务 %s 执行失败: %s", task_id, e)
            return {
                "task_id": task_id,
                "status": "failed",
                "message": "任务执行失败",
                "error": str(e),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取 PDF 转图片任务状态失败: %s", e)
        raise HTTPException(status_code=500, detail="获取任务状态失败")


@router.get("/pdf/task/{task_id}/result")
async def get_pdf_convert_task_result(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        owner_id = executor_manager.get_task_owner(task_id)
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务")
        if not future.done():
            raise HTTPException(
                status_code=400,
                detail="任务尚未完成，请稍后再试",
            )
        try:
            result = future.result(timeout=0.1)
            if isinstance(result, dict):
                if result.get("status") == "success":
                    return {
                        "task_id": task_id,
                        "status": "success",
                        "result": result,
                    }
                if result.get("status") == "cancelled":
                    raise HTTPException(status_code=400, detail="任务已取消")
                if result.get("status") == "error":
                    raise HTTPException(
                        status_code=500,
                        detail=f"任务执行失败: {result.get('message', '未知错误')}",
                    )
            return {
                "task_id": task_id,
                "result": result,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error("任务 %s 执行失败: %s", task_id, e)
            raise HTTPException(
                status_code=500,
                detail="任务执行失败",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取 PDF 转图片任务结果失败: %s", e)
        raise HTTPException(status_code=500, detail="获取任务结果失败")


@router.delete("/pdf/task/{task_id}")
async def cancel_pdf_convert_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        owner_id = executor_manager.get_task_owner(task_id)
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权取消该任务")
        if future.done():
            raise HTTPException(status_code=400, detail="任务已完成，无法取消")
        success = executor_manager.cancel_task(task_id)
        if success:
            return {
                "task_id": task_id,
                "message": "任务取消请求已发送（任务需主动检查取消标志）",
                "cancelled": True,
            }
        raise HTTPException(status_code=500, detail="取消任务失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("取消 PDF 转图片任务失败: %s", e)
        raise HTTPException(status_code=500, detail="取消任务失败")


@router.post("/pdf/page-count")
async def get_pdf_pages(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        logger.info("获取 PDF 页数: %s", file.filename)
        if file.content_type not in SUPPORTED_PDF_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 PDF 文件",
            )
        file_data = await file.read()
        max_size = settings.MAX_FILE_SIZE
        if len(file_data) > max_size:
            raise HTTPException(
                status_code=413,
                detail="文件过大",
            )
        page_count = get_pdf_page_count(file_data)
        return {
            "filename": file.filename,
            "total_pages": page_count,
            "message": f"PDF 文件共有 {page_count} 页",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取 PDF 页数失败: %s", e)
        raise HTTPException(status_code=500, detail="获取页数失败")
