"""Document async processing API."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.task_manager import task_manager
from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.executor import executor_manager
from app.core.logging import get_logger
from app.core.security import get_current_user, normalize_self_uploader
from app.integrations.doc_processing.document_task_runner import (
    process_documents_background,
    upload_and_register_documents,
)
from app.models.orm.platform.user import User, UserRole

router = APIRouter()
logger = get_logger("document_processing")


class DocumentProcessRequest(BaseModel):
    """（表单/文档用）处理参数模型。"""
    instance_id: int = Field(..., description="知识库实例ID")
    chunk_size: int = Field(500, ge=100, le=2000, description="文本块大小")
    chunk_overlap: int = Field(50, ge=0, le=500, description="文本块重叠大小")
    uploader: str = Field("anonymous", description="上传者标识")


class TaskSubmitResponse(BaseModel):
    """提交任务后的即时响应。"""
    task_id: str
    status: str = "pending"
    message: str = "任务已创建，开始处理"
    files_count: int


class TaskStatusResponse(BaseModel):
    """单任务状态。"""
    task_id: str
    status: str
    progress: int
    message: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class TaskListResponse(BaseModel):
    """任务列表。"""
    tasks: List[TaskStatusResponse]
    total: int


@router.post("/process", response_model=TaskSubmitResponse, summary="提交文档处理任务")
async def submit_document_processing(
    files: List[UploadFile] = File(..., description="要处理的文档文件"),
    instance_id: int = Query(..., description="知识库实例ID"),
    chunk_size: int = Query(500, ge=100, le=2000, description="文本块大小"),
    chunk_overlap: int = Query(50, ge=0, le=500, description="文本块重叠大小"),
    uploader: str = Query("anonymous", description="上传者标识（仅允许传本人信息）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload to MinIO, persist rows, create task, submit to thread pool; returns task_id."""
    try:
        if not files:
            raise ValidationError("至少需要上传一个文件")
        logger.info("收到文档处理请求: %s 个文件, instance_id=%s", len(files), instance_id)
        normalized_uploader = normalize_self_uploader(uploader, current_user)
        file_ids = upload_and_register_documents(db, files, normalized_uploader)
        if not file_ids:
            raise ValidationError("没有成功上传任何文件")
        task_id = await task_manager.create_task(
            task_type="doc_process",
            metadata={
                "file_ids": file_ids,
                "instance_id": instance_id,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "uploader": normalized_uploader,
                "owner_id": str(current_user.id),
                "files_count": len(file_ids),
            },
        )
        logger.info("创建文档处理任务: %s, 文件数: %s", task_id, len(file_ids))
        executor_manager.submit_task(
            task_id,
            process_documents_background,
            task_id,
            file_ids,
            instance_id,
            chunk_size,
            chunk_overlap,
        )
        executor_manager.set_task_owner(task_id, str(current_user.id))
        return TaskSubmitResponse(
            task_id=task_id,
            status="pending",
            message="任务已创建，开始处理",
            files_count=len(file_ids),
        )
    except ValidationError:
        raise
    except Exception as e:
        logger.error("提交文档处理任务失败: %s", e, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="提交任务失败") from e


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="查询任务状态")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务"
            )
        return TaskStatusResponse(
            task_id=task_status.task_id,
            status=task_status.status,
            progress=task_status.progress,
            message=task_status.message,
            created_at=task_status.created_at,
            started_at=task_status.started_at,
            completed_at=task_status.completed_at,
            result=task_status.result,
            error=task_status.error,
        )
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error("查询任务状态失败 %s: %s", task_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="查询任务状态失败") from e


@router.get("/tasks", response_model=TaskListResponse, summary="获取任务列表")
async def list_tasks(
    status: Optional[str] = Query(
        None, description="按状态筛选 (pending/running/completed/failed)"
    ),
    limit: int = Query(10, ge=1, le=100, description="返回数量限制"),
    current_user: User = Depends(get_current_user),
):
    try:
        tasks = await task_manager.list_tasks(task_type="doc_process", limit=limit)
        if status:
            tasks = [t for t in tasks if t.status == status]
        if current_user.role != UserRole.superuser:
            tasks = [
                t
                for t in tasks
                if str(t.metadata.get("owner_id", "")).strip() == str(current_user.id)
            ]
        task_responses = [
            TaskStatusResponse(
                task_id=t.task_id,
                status=t.status,
                progress=t.progress,
                message=t.message,
                created_at=t.created_at,
                started_at=t.started_at,
                completed_at=t.completed_at,
                result=t.result,
                error=t.error,
            )
            for t in tasks
        ]
        return TaskListResponse(tasks=task_responses, total=len(task_responses))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取任务列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="获取任务列表失败") from e


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
async def cancel_task_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权取消该任务"
            )
        if task_status.status in ["completed", "failed"]:
            return {
                "success": False,
                "message": f"任务已{task_status.status}，无法取消",
            }
        success = executor_manager.cancel_task(task_id)
        if success:
            fut = executor_manager.get_task_future(task_id)
            if fut is not None and fut.cancelled():
                await task_manager.fail_task(
                    task_id, "用户取消任务", "任务在队列中已取消"
                )
            elif task_status.status in ("running", "pending"):
                task_status.message = "正在取消任务..."
                await task_manager._save_task_status(task_status)
            return {"success": True, "message": "任务取消请求已发送"}
        return {"success": False, "message": "任务取消失败"}
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error("取消任务失败 %s: %s", task_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="取消任务失败") from e


@router.delete("/tasks/{task_id}", summary="删除任务记录")
async def delete_task_endpoint(
    task_id: str,
    cancel_if_running: bool = Query(True, description="是否取消正在运行的任务"),
    current_user: User = Depends(get_current_user),
):
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该任务"
            )
        if cancel_if_running and task_status.status in ["pending", "running"]:
            logger.info("任务正在运行，先尝试取消: %s", task_id)
            executor_manager.cancel_task(task_id)
        success = await task_manager.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除任务记录失败")
        return {
            "success": True,
            "message": f"任务 {task_id} 已{'取消并' if cancel_if_running else ''}删除",
        }
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除任务失败 %s: %s", task_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="删除任务失败") from e
