import os
import uuid
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, File, UploadFile, BackgroundTasks
from pydantic import BaseModel

from app.ocr.image2url import upload_file_to_minio
from app.api.taskmanager import TaskManager
task_manager = TaskManager()

router = APIRouter()

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 支持的图片类型常量
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/webp"
}

# 响应模型
class ImageUploadRequest(BaseModel):
    """图片上传请求模型（支持可选参数扩展）"""
    file_name_prefix: Optional[str] = None
    overwrite: Optional[bool] = False

class TaskResponse(BaseModel):
    """任务响应模型（与数据治理服务保持一致）"""
    task_id: str
    status: str
    message: str
    check_status_url: str

class ImageUploadResult(BaseModel):
    """图片上传结果模型"""
    url: str
    filename: str
    original_filename: str
    content_type: str
    file_size: int

async def background_image_upload_task(
    task_id: str,
    file_data: bytes,          # 二进制文件数据
    original_filename: str,    # 原始文件名（从 UploadFile 获取）
    content_type: str,         # 文件类型（从 UploadFile 获取）
    file_name_prefix: Optional[str] = None
):
    """后台执行图片上传任务"""
    try:
        logger.info(f"{task_id}")
        
        # 标记任务开始
        success = await task_manager.start_task(task_id)
        if not success:
            logger.error(f"无法启动任务: {task_id}")
            return
        
        # 更新进度：初始化
        await task_manager.update_task_progress(task_id, 20, "初始化图片上传...")
        
        try:
            # 生成唯一文件名
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4()}{file_ext}"
            if file_name_prefix:
                unique_filename = f"{file_name_prefix}/{unique_filename}"
            # 统一存入images目录
            unique_filename = f"images/{unique_filename}"
            
            # 更新进度：上传中
            await task_manager.update_task_progress(task_id, 50, "正在上传至MinIO...")
            logger.info(f"🔄 任务 {task_id}: 上传文件 {original_filename}")
            
            # 执行上传（同步操作，无需线程池，因文件较小）
            image_url = upload_file_to_minio(file_data, unique_filename)
            
            # 更新进度：上传完成
            await task_manager.update_task_progress(task_id, 90, "图片上传完成...")
            
            # 构建结果
            result = {
                "status": "success",
                "message": "图片上传成功",
                "data": ImageUploadResult(
                    url=image_url,
                    filename=unique_filename,
                    original_filename=original_filename,
                    content_type=content_type,
                    file_size=len(file_data)
                ).model_dump()  
            }
            
        except Exception as upload_error:
            error_msg = f"图片上传失败: {str(upload_error)}"
            logger.error(f"任务 {task_id}: {error_msg}")
            await task_manager.fail_task(task_id, error_msg, "图片上传失败")
            return
        
        # 标记任务完成
        await task_manager.complete_task(task_id, result, "图片上传完成")
        logger.info(f" 图片上传任务 {task_id} 成功完成")
        
    except Exception as e:
        error_msg = f"任务执行异常: {str(e)}"
        logger.error(f" 图片上传任务 {task_id} 失败: {error_msg}")
        await task_manager.fail_task(task_id, error_msg, "图片上传任务执行失败")

@router.post("/image/upload", response_model=TaskResponse)
async def upload_image(
    file: UploadFile = File(...),
    request: ImageUploadRequest = ImageUploadRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> TaskResponse:
    """
    异步上传图片至MinIO并返回访问URL
    
    Args:
        file: 待上传的图片文件
        request: 上传配置参数
        background_tasks: FastAPI后台任务管理器
    
    Returns:
        包含任务ID和状态查询URL的响应
    """
    try:
        logger.info(f"收到图片上传请求: {file.filename}")
        
        # 验证文件类型
        if file.content_type not in SUPPORTED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的图片类型: {file.content_type}，支持类型: {list(SUPPORTED_IMAGE_TYPES)}"
            )
        
        # 读取文件数据（小文件可直接读取）
        file_data = await file.read()
        
        # 创建任务
        metadata = {
            "original_filename": file.filename,
            "content_type": file.content_type,
            "file_size": len(file_data),
            "file_name_prefix": request.file_name_prefix,
            "overwrite": request.overwrite
        }
        task_id = await task_manager.create_task(
            task_type="image_upload",
            metadata=metadata
        )
        
        # 添加后台任务
        background_tasks.add_task(
            background_image_upload_task,
            task_id,
            file_data,
            file.filename,
            file.content_type,
            request.file_name_prefix
        )
        
        logger.info(f"启动图片上传任务: {task_id}")
        return TaskResponse(
            task_id=task_id,
            status="started",
            message="图片上传任务已启动",
            check_status_url=f"/api/v1/image/task/{task_id}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动图片上传任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动上传任务失败: {str(e)}")

@router.get("/image/task/{task_id}")
async def get_image_upload_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取图片上传任务状态
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务状态信息
    """
    try:
        logger.debug(f"查询图片上传任务状态: {task_id}")
        
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            logger.warning(f"任务不存在: {task_id}")
            raise HTTPException(status_code=404, detail="任务不存在")
        
        response = {
            "task_id": task_status.task_id,
            "task_type": task_status.task_type,
            "status": task_status.status,
            "progress": task_status.progress,
            "message": task_status.message,
            "created_at": task_status.created_at,
            "started_at": task_status.started_at,
            "completed_at": task_status.completed_at,
            "metadata": task_status.metadata
        }
        
        # 任务完成时添加结果摘要
        if task_status.status == "completed" and task_status.result:
            result_summary = {}
            if isinstance(task_status.result, dict):
                result_summary = {
                    "status": task_status.result.get("status"),
                    "image_url": task_status.result.get("data", {}).get("url"),
                    "filename": task_status.result.get("data", {}).get("filename"),
                    "file_size": task_status.result.get("data", {}).get("file_size", 0)
                }
            response["result_summary"] = result_summary
        
        # 任务失败时添加错误信息
        if task_status.status == "failed" and task_status.error:
            response["error"] = task_status.error
        
        logger.debug(f"图片上传任务 {task_id} 状态: {task_status.status} ({task_status.progress}%)")
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图片上传任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")

@router.get("/image/task/{task_id}/result")
async def get_image_upload_task_result(task_id: str) -> Dict[str, Any]:
    """
    获取图片上传任务结果（仅限已完成任务）
    
    Args:
        task_id: 任务ID
    
    Returns:
        完整任务结果
    """
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if task_status.status != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"任务尚未完成，当前状态: {task_status.status}"
            )
        
        if not task_status.result:
            raise HTTPException(status_code=404, detail="任务结果不存在")
        
        return {
            "task_id": task_id,
            "completed_at": task_status.completed_at,
            "result": task_status.result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图片上传任务结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务结果失败: {str(e)}")

@router.delete("/image/task/{task_id}")
async def delete_image_upload_task(task_id: str) -> Dict[str, Any]:
    """
    删除图片上传任务记录（仅支持已完成/失败任务）
    
    Args:
        task_id: 任务ID
    
    Returns:
        删除结果
    """
    try:
        task_status = await task_manager.get_task_status(task_id)
        if not task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if task_status.status in ["running", "pending"]:
            raise HTTPException(status_code=400, detail="无法删除正在运行的任务")
        
        success = await task_manager.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除任务失败")
        
        return {
            "task_id": task_id,
            "message": "图片上传任务已删除",
            "deleted": True
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图片上传任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")

@router.get("/image/tasks")
async def list_image_upload_tasks(
    status: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    列出图片上传任务（用于管理和调试）
    
    Args:
        status: 任务状态过滤
        limit: 返回数量限制
    
    Returns:
        任务列表及过滤信息
    """
    try:
        tasks = await task_manager.list_tasks(task_type="image_upload", status=status)
        
        task_list = []
        for task_id, task_status in list(tasks.items())[:limit]:
            task_info = {
                "task_id": task_status.task_id,
                "task_type": task_status.task_type,
                "status": task_status.status,
                "progress": task_status.progress,
                "message": task_status.message,
                "created_at": task_status.created_at,
                "started_at": task_status.started_at,
                "completed_at": task_status.completed_at,
                "metadata": task_status.metadata
            }
            
            # 简化结果展示
            if task_status.result:
                task_info["has_result"] = True
                task_info["image_url"] = task_status.result.get("data", {}).get("url")
            
            if task_status.status == "failed" and task_status.error:
                task_info["error"] = task_status.error
            
            task_list.append(task_info)
        
        return {
            "tasks": task_list,
            "total": len(task_list),
            "filters": {
                "task_type": "image_upload",
                "status": status
            }
        }
    
    except Exception as e:
        logger.error(f"列出图片上传任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"列出任务失败: {str(e)}")
