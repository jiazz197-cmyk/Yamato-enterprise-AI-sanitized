import os
import uuid
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, File, UploadFile
from pydantic import BaseModel

from app.integrations.ocr.image2url import upload_file_to_minio
from app.core.executor import executor_manager, CancellationToken

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

class ImageUploadResponse(BaseModel):
    """图片上传响应模型（简化版，直接返回任务ID）"""
    task_id: str
    status: str
    message: str

class ImageUploadResult(BaseModel):
    """图片上传结果模型"""
    url: str
    filename: str
    original_filename: str
    content_type: str
    file_size: int

def background_image_upload_task(
    token: CancellationToken,
    task_id: str,
    file_data: bytes,
    original_filename: str,
    content_type: str,
    file_name_prefix: Optional[str] = None
) -> Dict[str, Any]:
    """
    后台执行图片上传任务（使用 ExecutorManager）
    
    Args:
        token: 取消令牌（用于协作式取消）
        task_id: 任务ID
        file_data: 二进制文件数据
        original_filename: 原始文件名
        content_type: 文件类型
        file_name_prefix: 文件名前缀（可选）
    
    Returns:
        上传结果字典
    """
    try:
        logger.info(f"开始图片上传任务: {task_id}")
        
        # 检查是否被取消
        if token.is_cancelled():
            logger.warning(f"任务 {task_id} 在开始前被取消")
            return {"status": "cancelled", "message": "任务已取消"}
        
        # 生成唯一文件名
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        if file_name_prefix:
            unique_filename = f"{file_name_prefix}/{unique_filename}"
        # 统一存入images目录
        unique_filename = f"images/{unique_filename}"
        
        # 再次检查是否被取消
        if token.is_cancelled():
            logger.warning(f"任务 {task_id} 在上传前被取消")
            return {"status": "cancelled", "message": "任务已取消"}
        
        logger.info(f"上传文件 {original_filename} -> {unique_filename}")
        
        # 执行上传（同步操作）
        image_url = upload_file_to_minio(file_data, unique_filename)
        
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
        
        logger.info(f"图片上传任务 {task_id} 成功完成")
        return result
        
    except Exception as e:
        error_msg = f"图片上传失败: {str(e)}"
        logger.error(f"任务 {task_id} 失败: {error_msg}", exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "error": str(e)
        }

@router.post("/image/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    request: ImageUploadRequest = ImageUploadRequest()
) -> ImageUploadResponse:
    """
    异步上传图片至MinIO并返回访问URL（使用 ExecutorManager）
    
    Args:
        file: 待上传的图片文件
        request: 上传配置参数
    
    Returns:
        包含任务ID的响应（客户端可通过 task_id 查询结果）
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
        
        # 🆕 使用 ExecutorManager 的统一任务ID生成方法
        task_id = executor_manager.generate_task_id("image_upload")
        
        # 提交到线程池执行
        # submit_task 会自动注入 token，然后传递其他参数
        executor_manager.submit_task(
            task_id,  # 任务ID（传给 submit_task 方法）
            background_image_upload_task,  # 执行函数
            task_id,  # 作为位置参数传递给函数（token 之后）
            file_data,
            file.filename,
            file.content_type,
            request.file_name_prefix
        )
        
        logger.info(f"启动图片上传任务: {task_id}")
        return ImageUploadResponse(
            task_id=task_id,
            status="started",
            message="图片上传任务已启动，请通过 task_id 查询结果"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动图片上传任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动上传任务失败: {str(e)}")

@router.get("/image/task/{task_id}")
async def get_image_upload_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取图片上传任务状态（使用 ExecutorManager）
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务状态信息
    """
    try:
        logger.debug(f"查询图片上传任务状态: {task_id}")
        
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # 检查任务状态
        if not future.done():
            # 任务仍在运行
            return {
                "task_id": task_id,
                "status": "running",
                "message": "任务正在执行中"
            }
        
        # 任务已完成，获取结果
        try:
            result = future.result(timeout=0.1)  # 已完成，立即返回
            
            # 检查是否被取消
            if isinstance(result, dict) and result.get("status") == "cancelled":
                return {
                    "task_id": task_id,
                    "status": "cancelled",
                    "message": result.get("message", "任务已取消")
                }
            
            # 检查是否执行失败
            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "message": result.get("message", "任务执行失败"),
                    "error": result.get("error")
                }
            
            # 任务成功完成
            return {
                "task_id": task_id,
                "status": "completed",
                "message": "任务完成",
                "result": result
            }
            
        except Exception as e:
            # 任务执行过程中出现异常
            logger.error(f"任务 {task_id} 执行失败: {e}")
            return {
                "task_id": task_id,
                "status": "failed",
                "message": "任务执行失败",
                "error": str(e)
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图片上传任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")

@router.get("/image/task/{task_id}/result")
async def get_image_upload_task_result(task_id: str) -> Dict[str, Any]:
    """
    获取图片上传任务结果（仅限已完成任务，使用 ExecutorManager）
    
    Args:
        task_id: 任务ID
    
    Returns:
        完整任务结果
    """
    try:
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if not future.done():
            raise HTTPException(
                status_code=400,
                detail="任务尚未完成，请稍后再试"
            )
        
        try:
            result = future.result(timeout=0.1)
            
            # 检查结果类型
            if isinstance(result, dict):
                if result.get("status") == "success":
                    return {
                        "task_id": task_id,
                        "status": "success",
                        "result": result
                    }
                elif result.get("status") == "cancelled":
                    raise HTTPException(status_code=400, detail="任务已取消")
                elif result.get("status") == "error":
                    raise HTTPException(
                        status_code=500, 
                        detail=f"任务执行失败: {result.get('message', '未知错误')}"
                    )
            
            return {
                "task_id": task_id,
                "result": result
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"任务执行失败: {str(e)}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图片上传任务结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务结果失败: {str(e)}")

@router.delete("/image/task/{task_id}")
async def cancel_image_upload_task(task_id: str) -> Dict[str, Any]:
    """
    取消图片上传任务（使用 ExecutorManager 协作式取消）
    
    Args:
        task_id: 任务ID
    
    Returns:
        取消结果
    """
    try:
        future = executor_manager.get_task_future(task_id)
        if not future:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if future.done():
            raise HTTPException(status_code=400, detail="任务已完成，无法取消")
        
        # 尝试取消任务
        success = executor_manager.cancel_task(task_id)
        
        if success:
            return {
                "task_id": task_id,
                "message": "任务取消请求已发送（任务需主动检查取消标志）",
                "cancelled": True
            }
        else:
            raise HTTPException(status_code=500, detail="取消任务失败")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消图片上传任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")

@router.get("/image/tasks/stats")
async def get_image_upload_tasks_stats() -> Dict[str, Any]:
    """
    获取图片上传任务统计信息（使用 ExecutorManager）
    
    Returns:
        任务统计信息
    """
    try:
        active_count = executor_manager.get_active_task_count()
        running_count = executor_manager.get_running_task_count()
        
        return {
            "total_tasks": active_count,
            "running_tasks": running_count,
            "completed_tasks": active_count - running_count,
            "message": "ExecutorManager 简化模式：仅提供统计信息，不支持详细列表"
        }
    
    except Exception as e:
        logger.error(f"获取任务统计信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
