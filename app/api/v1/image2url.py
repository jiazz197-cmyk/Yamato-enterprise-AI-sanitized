import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, File, UploadFile, Depends, status
from pydantic import BaseModel

from app.core.executor import executor_manager
from app.core.security import get_current_user
from app.integrations.ocr.image_upload_tasks import background_image_upload_task
from app.models.orm.platform.user import User, UserRole

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/webp",
}


class ImageUploadRequest(BaseModel):
    file_name_prefix: Optional[str] = None
    overwrite: Optional[bool] = False


class ImageUploadResponse(BaseModel):
    task_id: str
    status: str
    message: str


@router.post("/image/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    request: ImageUploadRequest = ImageUploadRequest(),
    current_user: User = Depends(get_current_user),
) -> ImageUploadResponse:
    try:
        logger.info("收到图片上传请求: %s", file.filename)
        if file.content_type not in SUPPORTED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的图片类型: {file.content_type}，支持类型: {list(SUPPORTED_IMAGE_TYPES)}",
            )
        file_data = await file.read()
        task_id = executor_manager.generate_task_id("image_upload")
        executor_manager.submit_task(
            task_id,
            background_image_upload_task,
            task_id,
            file_data,
            file.filename,
            file.content_type,
            request.file_name_prefix,
        )
        executor_manager.set_task_owner(task_id, str(current_user.id))
        logger.info("启动图片上传任务: %s", task_id)
        return ImageUploadResponse(
            task_id=task_id,
            status="started",
            message="图片上传任务已启动，请通过 task_id 查询结果",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("启动图片上传任务失败: %s", e)
        raise HTTPException(status_code=500, detail="启动上传任务失败")


@router.get("/image/task/{task_id}")
async def get_image_upload_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        logger.debug("查询图片上传任务状态: %s", task_id)
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
        logger.error("获取图片上传任务状态失败: %s", e)
        raise HTTPException(status_code=500, detail="获取任务状态失败")


@router.get("/image/task/{task_id}/result")
async def get_image_upload_task_result(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        owner_id = executor_manager.get_task_owner(task_id)
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务结果")
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
        logger.error("获取图片上传任务结果失败: %s", e)
        raise HTTPException(status_code=500, detail="获取任务结果失败")


@router.delete("/image/task/{task_id}")
async def cancel_image_upload_task(
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
        logger.error("取消图片上传任务失败: %s", e)
        raise HTTPException(status_code=500, detail="取消任务失败")


@router.get("/image/tasks/stats")
async def get_image_upload_tasks_stats(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        if current_user.role != UserRole.superuser:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员可查看任务统计")
        active_count = executor_manager.get_active_task_count()
        running_count = executor_manager.get_running_task_count()
        return {
            "total_tasks": active_count,
            "running_tasks": running_count,
            "completed_tasks": active_count - running_count,
            "message": "ExecutorManager 简化模式：仅提供统计信息，不支持详细列表",
        }
    except Exception as e:
        logger.error("获取任务统计信息失败: %s", e)
        raise HTTPException(status_code=500, detail="获取统计信息失败")
