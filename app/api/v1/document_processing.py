"""文档异步处理与任务查询路由。"""
import asyncio
from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.taskmanager import task_manager, TaskManager
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.executor import executor_manager, CancellationToken
from app.core.logging import get_logger
from app.core.storage import (
    download_object_stream,
    upload_stream_to_minio,
    get_minio_client,
    MINIO_BUCKET_NAME,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User, UserRole
from app.core.security import get_current_user, normalize_self_uploader

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


def process_documents_background(
    token: CancellationToken,
    task_id: str,
    file_ids: List[int],
    instance_id: int,
    chunk_size: int,
    chunk_overlap: int,
):
    """在线程池里跑 pipeline：首参 token 由 ExecutorManager 注入；内含独立 asyncio 循环与线程内 TaskManager。此处勿直接 await。"""
    import asyncio
    import time
    from app.integrations.doc_processing.pipeline import DocumentProcessingPipeline
    from app.api.taskmanager import TaskManager
    
    logger.info(f"[{task_id}] 开始后台处理，文件数: {len(file_ids)}")
    
    thread_tm = TaskManager.create_thread_safe_instance()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        if token.is_cancelled():
            logger.info(f"[{task_id}] 任务在启动前被取消")
            return {"status": "cancelled", "message": "任务在启动前被取消"}
        
        task_exists = False
        for attempt in range(5):
            try:
                task_status = loop.run_until_complete(thread_tm.get_task_status(task_id))
                if task_status:
                    task_exists = True
                    logger.info(f"[{task_id}] 任务已找到，开始处理")
                    break
            except Exception as e:
                logger.warning(f"[{task_id}] 查询任务状态失败 (尝试 {attempt + 1}/5): {e}")
            
            time.sleep(0.3)
        
        if not task_exists:
            logger.error(f"[{task_id}] 任务创建超时，无法启动")
            return {"status": "error", "message": "任务创建超时"}
        
        loop.run_until_complete(thread_tm.start_task(task_id))
        
        db_config = {
            "host": settings.POSTGRES_SERVER,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "database": settings.POSTGRES_DB,
            "port": settings.POSTGRES_PORT,
        }
        
        pipeline = DocumentProcessingPipeline(
            db_config=db_config,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        
        logger.info(f"[{task_id}] 正在从 MinIO 下载 {len(file_ids)} 个文件...")
        streams = []
        
        from app.core.database import SessionLocal
        db = SessionLocal()
        
        try:
            for i, file_id in enumerate(file_ids):
                if token.is_cancelled():
                    logger.info(f"[{task_id}] 任务被取消，停止下载")
                    loop.run_until_complete(
                        thread_tm.fail_task(task_id, "用户取消任务", "任务已取消")
                    )
                    return {"status": "cancelled", "message": "任务被取消"}
                
                file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
                if not file_record:
                    logger.warning(f"[{task_id}] 文件 ID {file_id} 不存在，跳过")
                    continue
                
                progress = int((i / len(file_ids)) * 30)
                loop.run_until_complete(
                    thread_tm.update_task_progress(
                        task_id, progress, f"正在下载第 {i+1}/{len(file_ids)} 个文件: {file_record.file_name}"
                    )
                )
                
                try:
                    with download_object_stream(file_record.minio_object_path) as response:
                        stream = BytesIO(response.read())
                        stream.name = file_record.file_name
                        streams.append(stream)
                except Exception as e:
                    logger.error(f"[{task_id}] 下载文件失败 {file_record.file_name}: {e}")
                    continue
            
            if not streams:
                raise ValueError("没有成功下载任何文件")
            
            if token.is_cancelled():
                logger.info(f"[{task_id}] 任务被取消，停止处理")
                loop.run_until_complete(
                    thread_tm.fail_task(task_id, "用户取消任务", "任务已取消")
                )
                return {"status": "cancelled", "message": "任务被取消"}
            
            logger.info(f"[{task_id}] 成功下载 {len(streams)} 个文件，开始处理...")
            
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, 30, f"开始处理 {len(streams)} 个文件...")
            )
            
            result = pipeline.process(
                input_data=streams,
                instance_id=instance_id,
            )
            
            loop.run_until_complete(
                thread_tm.update_task_progress(task_id, 90, "正在保存结果...")
            )
            
            final_result = {
                "processed_files": result.get("processed_files", 0),
                "total_files": len(file_ids),
                "status": result.get("status"),
                "instance_id": instance_id,
            }
            
            loop.run_until_complete(
                thread_tm.complete_task(task_id, final_result, "文档处理完成")
            )
            
            logger.info(f"[{task_id}] 处理完成: {final_result}")
            return final_result
            
        finally:
            try:
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        
    except Exception as e:
        logger.error(f"[{task_id}] 处理失败: {e}", exc_info=True)
        try:
            loop.run_until_complete(
                thread_tm.fail_task(task_id, str(e), "文档处理失败")
            )
        except Exception as e2:
            logger.error(f"[{task_id}] 标记失败状态时出错: {e2}")
        return {"status": "error", "message": str(e)}
    finally:
        try:
            if hasattr(thread_tm, 'storage') and hasattr(thread_tm.storage, 'redis_client'):
                if thread_tm.storage.redis_client is not None:
                    try:
                        async def close_redis_with_timeout():
                            if hasattr(thread_tm.storage.redis_client, 'connection_pool'):
                                await thread_tm.storage.redis_client.connection_pool.disconnect()
                            await thread_tm.storage.redis_client.aclose()
                        
                        loop.run_until_complete(
                            asyncio.wait_for(close_redis_with_timeout(), timeout=2.0)
                        )
                        logger.debug(f"[{task_id}] Redis连接已关闭")
                    except asyncio.TimeoutError:
                        logger.warning(f"[{task_id}] Redis关闭超时，强制继续")
                    except Exception as e:
                        logger.warning(f"[{task_id}] 关闭Redis连接失败: {e}")
            
            if loop and not loop.is_closed():
                loop.close()
                logger.debug(f"[{task_id}] 事件循环已关闭")
        except Exception as e:
            logger.warning(f"[{task_id}] 清理资源时出错: {e}")


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
    """上传 MinIO、落库、建 task、丢进线程池；接口立即返回 task_id。"""
    try:
        if not files:
            raise ValidationError("至少需要上传一个文件")
        
        logger.info(f"收到文档处理请求: {len(files)} 个文件, instance_id={instance_id}")

        normalized_uploader = normalize_self_uploader(uploader, current_user)

        file_ids = []
        for file in files:
            if not file.filename:
                logger.warning("跳过没有文件名的文件")
                continue
            
            try:
                from datetime import datetime
                import uuid
                from pathlib import Path
                
                suffix = Path(file.filename).suffix
                unique_id = uuid.uuid4().hex
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_name = f"{timestamp}_{unique_id}{suffix}"
                minio_path = f"documents/{unique_name}"
                
                file_size = getattr(file, 'size', None) or -1
                
                content_type = file.content_type or "application/octet-stream"
                result = upload_stream_to_minio(file.file, minio_path, file_size, content_type)
                
                if result.startswith("Error"):
                    logger.error(f"上传文件失败: {file.filename} - {result}")
                    continue
                
                if file_size == -1:
                    try:
                        client = get_minio_client()
                        stat = client.stat_object(MINIO_BUCKET_NAME, minio_path)
                        file_size = stat.size
                    except:
                        file_size = 0
                
                file_record = FileResource(
                    file_name=file.filename,
                    unique_name=unique_name,
                    minio_object_path=minio_path,
                    content_type=content_type,
                    file_size=file_size,
                    uploader=normalized_uploader,
                )
                db.add(file_record)
                db.commit()
                db.refresh(file_record)
                
                file_ids.append(file_record.id)
                logger.info(f"文件上传成功: {file.filename} (ID: {file_record.id})")
                
            except Exception as e:
                logger.error(f"上传文件失败 {file.filename}: {e}", exc_info=True)
                db.rollback()
                continue
        
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
            }
        )
        
        logger.info(f"创建文档处理任务: {task_id}, 文件数: {len(file_ids)}")
        
        executor_manager.submit_task(
            task_id,
            process_documents_background,
            task_id,
            file_ids,
            instance_id,
            chunk_size,
            chunk_overlap,
        )
        
        return TaskSubmitResponse(
            task_id=task_id,
            status="pending",
            message="任务已创建，开始处理",
            files_count=len(file_ids),
        )
        
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"提交文档处理任务失败: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="提交任务失败")


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="查询任务状态")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """按 task_id 查状态；非 superuser 仅能看自己的任务。"""
    try:
        task_status = await task_manager.get_task_status(task_id)
        
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务")

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
        logger.error(f"查询任务状态失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询任务状态失败")


@router.get("/tasks", response_model=TaskListResponse, summary="获取任务列表")
async def list_tasks(
    status: Optional[str] = Query(None, description="按状态筛选 (pending/running/completed/failed)"),
    limit: int = Query(10, ge=1, le=100, description="返回数量限制"),
    current_user: User = Depends(get_current_user),
):
    """doc_process 类型任务列表，可按 status 过滤。"""
    try:
        tasks = await task_manager.list_tasks(task_type="doc_process", limit=limit)
        
        if status:
            tasks = [t for t in tasks if t.status == status]

        if current_user.role != UserRole.superuser:
            tasks = [
                t for t in tasks
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
        
        return TaskListResponse(
            tasks=task_responses,
            total=len(task_responses),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取任务列表失败")


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
async def cancel_task_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """协作式取消：ExecutorManager.cancel_task + 必要时更新 TaskManager 文案。"""
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权取消该任务")

        if task_status.status in ["completed", "failed"]:
            return {
                "success": False,
                "message": f"任务已{task_status.status}，无法取消"
            }
        
        success = executor_manager.cancel_task(task_id)
        
        if success:
            if task_status.status == "running":
                task_status.message = "正在取消任务..."
                await task_manager._save_task_status(task_status)
            
            return {
                "success": True,
                "message": "任务取消请求已发送"
            }
        else:
            return {
                "success": False,
                "message": "任务取消失败"
            }
        
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="取消任务失败")


@router.delete("/tasks/{task_id}", summary="删除任务记录")
async def delete_task_endpoint(
    task_id: str,
    cancel_if_running: bool = Query(True, description="是否取消正在运行的任务"),
    current_user: User = Depends(get_current_user),
):
    """可先 cancel 再删记录；线程内任务仍须自行响应 token。"""
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
        owner_id = str(task_status.metadata.get("owner_id", "")).strip()
        if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该任务")

        if cancel_if_running and task_status.status in ["pending", "running"]:
            logger.info(f"任务正在运行，先尝试取消: {task_id}")
            executor_manager.cancel_task(task_id)
        
        success = await task_manager.delete_task(task_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="删除任务记录失败")
        
        return {
            "success": True,
            "message": f"任务 {task_id} 已{'取消并' if cancel_if_running else ''}删除"
        }
        
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除任务失败")



