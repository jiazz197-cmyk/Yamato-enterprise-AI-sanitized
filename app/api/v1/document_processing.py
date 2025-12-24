"""
文档处理路由模块
提供异步文档处理、进度查询等服务
"""
import asyncio
from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query
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

router = APIRouter()
logger = get_logger("document_processing")


# ==================== 响应模型 ====================
class DocumentProcessRequest(BaseModel):
    """文档处理请求"""
    instance_id: int = Field(..., description="知识库实例ID")
    chunk_size: int = Field(500, ge=100, le=2000, description="文本块大小")
    chunk_overlap: int = Field(50, ge=0, le=500, description="文本块重叠大小")
    uploader: str = Field("anonymous", description="上传者标识")


class TaskSubmitResponse(BaseModel):
    """任务提交响应"""
    task_id: str
    status: str = "pending"
    message: str = "任务已创建，开始处理"
    files_count: int


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
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
    """任务列表响应"""
    tasks: List[TaskStatusResponse]
    total: int


# ==================== 后台处理函数 ====================
def process_documents_background(
    token: CancellationToken,  # ✅ 第一个参数必须是 CancellationToken
    task_id: str,
    file_ids: List[int],
    instance_id: int,
    chunk_size: int,
    chunk_overlap: int,
):
    """
    后台文档处理函数（在线程池中执行）
    
    🆕 使用改进的协作模式：
    1. 第一个参数是 CancellationToken，由 ExecutorManager 自动注入
    2. 在多个检查点使用 token.is_cancelled() 检查取消状态
    3. 协作式取消 - 任务主动退出
    4. 🆕 使用独立的 TaskManager 实例避免事件循环冲突
    
    注意：这个函数在独立线程中运行，不能直接使用 async/await
    """
    import asyncio
    import time
    from app.integrations.doc_processing.pipeline import DocumentProcessingPipeline
    
    logger.info(f"[{task_id}] 开始后台处理，文件数: {len(file_ids)}")
    
    # 🆕 创建线程专用的 TaskManager 实例（避免事件循环冲突）
    thread_task_manager = TaskManager.create_thread_safe_instance()
    
    # 创建线程专用的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # ✅ 检查点1：启动前检查
        if token.is_cancelled():
            logger.info(f"[{task_id}] 任务在启动前被取消")
            return {"status": "cancelled", "message": "任务在启动前被取消"}
        
        # 🆕 等待任务创建完成（最多重试5次）
        task_exists = False
        for attempt in range(5):
            try:
                task_status = loop.run_until_complete(thread_task_manager.get_task_status(task_id))
                if task_status:
                    task_exists = True
                    logger.info(f"[{task_id}] 任务已找到，开始处理")
                    break
            except Exception as e:
                logger.warning(f"[{task_id}] 查询任务状态失败 (尝试 {attempt + 1}/5): {e}")
            
            time.sleep(0.3)  # 等待 300ms
        
        if not task_exists:
            logger.error(f"[{task_id}] 任务创建超时，无法启动")
            return {"status": "error", "message": "任务创建超时"}
        
        # 启动任务
        loop.run_until_complete(thread_task_manager.start_task(task_id))
        
        # 构建数据库配置
        db_config = {
            "host": settings.POSTGRES_SERVER,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "database": settings.POSTGRES_DB,
            "port": settings.POSTGRES_PORT,
        }
        
        # 初始化处理管线
        pipeline = DocumentProcessingPipeline(
            db_config=db_config,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        
        # 从 MinIO 下载文件流
        logger.info(f"[{task_id}] 正在从 MinIO 下载 {len(file_ids)} 个文件...")
        streams = []
        
        # 使用独立的数据库会话查询文件
        from app.core.database import SessionLocal
        db = SessionLocal()
        
        try:
            for i, file_id in enumerate(file_ids):
                # ✅ 检查点2：每个文件下载前检查
                if token.is_cancelled():
                    logger.info(f"[{task_id}] 任务被取消，停止下载")
                    loop.run_until_complete(
                        thread_task_manager.fail_task(task_id, "用户取消任务", "任务已取消")
                    )
                    return {"status": "cancelled", "message": "任务被取消"}
                
                file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
                if not file_record:
                    logger.warning(f"[{task_id}] 文件 ID {file_id} 不存在，跳过")
                    continue
                
                # 更新进度：下载阶段
                progress = int((i / len(file_ids)) * 30)  # 下载占30%进度
                loop.run_until_complete(
                    thread_task_manager.update_task_progress(
                        task_id, progress, f"正在下载第 {i+1}/{len(file_ids)} 个文件: {file_record.file_name}"
                    )
                )
                
                # ✅ 从 MinIO 获取文件流（使用 context manager 防止泄漏）
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
            
            # ✅ 检查点3：处理前检查
            if token.is_cancelled():
                logger.info(f"[{task_id}] 任务被取消，停止处理")
                loop.run_until_complete(
                    thread_task_manager.fail_task(task_id, "用户取消任务", "任务已取消")
                )
                return {"status": "cancelled", "message": "任务被取消"}
            
            logger.info(f"[{task_id}] 成功下载 {len(streams)} 个文件，开始处理...")
            
            # 更新进度：处理阶段
            loop.run_until_complete(
                thread_task_manager.update_task_progress(task_id, 30, f"开始处理 {len(streams)} 个文件...")
            )
            
            # 处理文档（这里可以添加进度回调）
            result = pipeline.process(
                input_data=streams,
                instance_id=instance_id,
            )
            
            # 更新进度：完成
            loop.run_until_complete(
                thread_task_manager.update_task_progress(task_id, 90, "正在保存结果...")
            )
            
            # 标记任务完成
            final_result = {
                "processed_files": result.get("processed_files", 0),
                "total_files": len(file_ids),
                "status": result.get("status"),
                "instance_id": instance_id,
            }
            
            loop.run_until_complete(
                thread_task_manager.complete_task(task_id, final_result, "文档处理完成")
            )
            
            logger.info(f"[{task_id}] 处理完成: {final_result}")
            return final_result
            
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"[{task_id}] 处理失败: {e}", exc_info=True)
        try:
            loop.run_until_complete(
                thread_task_manager.fail_task(task_id, str(e), "文档处理失败")
            )
        except Exception as e2:
            logger.error(f"[{task_id}] 标记失败状态时出错: {e2}")
        return {"status": "error", "message": str(e)}
    finally:
        # 清理资源
        try:
            if hasattr(thread_task_manager.storage, 'redis_client'):
                loop.run_until_complete(thread_task_manager.storage.redis_client.aclose())
            loop.close()
        except Exception as e:
            logger.warning(f"[{task_id}] 清理资源时出错: {e}")


# ==================== 路由定义 ====================
@router.post("/process", response_model=TaskSubmitResponse, summary="提交文档处理任务")
async def submit_document_processing(
    files: List[UploadFile] = File(..., description="要处理的文档文件"),
    instance_id: int = Query(..., description="知识库实例ID"),
    chunk_size: int = Query(500, ge=100, le=2000, description="文本块大小"),
    chunk_overlap: int = Query(50, ge=0, le=500, description="文本块重叠大小"),
    uploader: str = Query("anonymous", description="上传者标识"),
    db: Session = Depends(get_db),
):
    """
    提交文档处理任务（异步）
    
    工作流程：
    1. 上传文件到 MinIO 并记录元数据
    2. 创建异步任务
    3. 提交到后台线程池处理
    4. 立即返回任务ID（不等待处理完成）
    
    - **files**: 要处理的文档文件（支持多文件）
    - **instance_id**: 知识库实例ID
    - **chunk_size**: 文本分块大小（默认500）
    - **chunk_overlap**: 分块重叠大小（默认50）
    - **uploader**: 上传者标识
    """
    try:
        # 验证文件
        if not files:
            raise ValidationError("至少需要上传一个文件")
        
        logger.info(f"收到文档处理请求: {len(files)} 个文件, instance_id={instance_id}")
        
        # 步骤1: 上传文件到 MinIO 并保存元数据
        file_ids = []
        for file in files:
            if not file.filename:
                logger.warning("跳过没有文件名的文件")
                continue
            
            try:
                # 生成唯一文件名
                from datetime import datetime
                import uuid
                from pathlib import Path
                
                suffix = Path(file.filename).suffix
                unique_id = uuid.uuid4().hex
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_name = f"{timestamp}_{unique_id}{suffix}"
                minio_path = f"documents/{unique_name}"
                
                # 获取文件大小
                file_size = getattr(file, 'size', None) or -1
                
                # 流式上传到 MinIO
                content_type = file.content_type or "application/octet-stream"
                result = upload_stream_to_minio(file.file, minio_path, file_size, content_type)
                
                if result.startswith("Error"):
                    logger.error(f"上传文件失败: {file.filename} - {result}")
                    continue
                
                # 如果文件大小未知，从 MinIO 获取
                if file_size == -1:
                    try:
                        client = get_minio_client()
                        stat = client.stat_object(MINIO_BUCKET_NAME, minio_path)
                        file_size = stat.size
                    except:
                        file_size = 0
                
                # 保存元数据到数据库
                file_record = FileResource(
                    file_name=file.filename,
                    unique_name=unique_name,
                    minio_object_path=minio_path,
                    content_type=content_type,
                    file_size=file_size,
                    uploader=uploader,
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
        
        # 步骤2: 创建异步任务
        task_id = await task_manager.create_task(
            task_type="doc_process",
            metadata={
                "file_ids": file_ids,
                "instance_id": instance_id,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "uploader": uploader,
                "files_count": len(file_ids),
            }
        )
        
        logger.info(f"创建文档处理任务: {task_id}, 文件数: {len(file_ids)}")
        
        # 步骤3: 提交到后台线程池（使用 ExecutorManager）
        # submit_task 签名: submit_task(task_id, fn, *args, **kwargs)
        # fn 的签名: process_documents_background(token, task_id, file_ids, instance_id, chunk_size, chunk_overlap)
        # token 会自动注入，所以这里传递 task_id 开始的参数
        executor_manager.submit_task(
            task_id,
            process_documents_background,
            task_id,  # 作为位置参数传递给函数
            file_ids,
            instance_id,
            chunk_size,
            chunk_overlap,
        )
        
        # 步骤4: 立即返回
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
        raise HTTPException(status_code=500, detail=f"提交任务失败: {str(e)}")


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="查询任务状态")
async def get_task_status(task_id: str):
    """
    查询文档处理任务的状态和进度
    
    - **task_id**: 任务ID
    
    返回任务的详细状态信息，包括进度、消息、结果等
    """
    try:
        task_status = await task_manager.get_task_status(task_id)
        
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
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
    except Exception as e:
        logger.error(f"查询任务状态失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询任务状态失败: {str(e)}")


@router.get("/tasks", response_model=TaskListResponse, summary="获取任务列表")
async def list_tasks(
    status: Optional[str] = Query(None, description="按状态筛选 (pending/running/completed/failed)"),
    limit: int = Query(10, ge=1, le=100, description="返回数量限制"),
):
    """
    获取文档处理任务列表
    
    - **status**: 可选，按状态筛选
    - **limit**: 返回数量限制（1-100）
    """
    try:
        tasks = await task_manager.list_tasks(task_type="doc_process", limit=limit)
        
        # 按状态筛选
        if status:
            tasks = [t for t in tasks if t.status == status]
        
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
        
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
async def cancel_task_endpoint(task_id: str):
    """
    取消正在运行或等待中的任务
    
    工作原理：
    - 未开始的任务：立即取消，不会执行
    - 正在运行的任务：设置取消标志，任务会在检查点主动退出
    - 已完成/失败的任务：无法取消
    
    - **task_id**: 任务ID
    """
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
        if task_status.status in ["completed", "failed"]:
            return {
                "success": False,
                "message": f"任务已{task_status.status}，无法取消"
            }
        
        # 通过 ExecutorManager 取消任务
        success = executor_manager.cancel_task(task_id)
        
        if success:
            # 更新任务状态
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
    except Exception as e:
        logger.error(f"取消任务失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@router.delete("/tasks/{task_id}", summary="删除任务记录")
async def delete_task_endpoint(
    task_id: str,
    cancel_if_running: bool = Query(True, description="是否取消正在运行的任务"),
):
    """
    取消或删除文档处理任务
    
    行为说明：
    - 未开始的任务：立即取消，不会执行
    - 正在运行的任务：设置取消标志，任务会在检查点退出
    - 已完成的任务：仅删除记录
    
    注意：Python 无法强制杀死线程，正在运行的任务需要主动检查取消标志
    
    - **task_id**: 任务ID
    - **cancel_if_running**: 是否尝试取消正在运行的任务
    """
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise NotFoundError(f"任务 {task_id} 不存在")
        
        # 1. 如果任务正在运行且需要取消，先取消
        if cancel_if_running and task_status.status in ["pending", "running"]:
            logger.info(f"任务正在运行，先尝试取消: {task_id}")
            executor_manager.cancel_task(task_id)
        
        # 2. 删除任务记录
        success = await task_manager.delete_task(task_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="删除任务记录失败")
        
        return {
            "success": True,
            "message": f"任务 {task_id} 已{'取消并' if cancel_if_running else ''}删除"
        }
        
    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"删除任务失败 {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")



