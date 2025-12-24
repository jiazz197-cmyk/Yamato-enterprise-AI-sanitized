import os
import uuid
import logging
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, File, UploadFile
from pydantic import BaseModel, Field

from app.integrations.ocr.pdf2image import pdf_to_images, pdf_to_single_image, get_pdf_page_count
from app.integrations.ocr.image2url import upload_file_to_minio
from app.core.executor import executor_manager, CancellationToken

router = APIRouter()

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 支持的 PDF 类型常量
SUPPORTED_PDF_TYPES = {
    "application/pdf"
}

# 响应模型
class PdfConvertRequest(BaseModel):
    """PDF 转图片请求模型"""
    dpi: Optional[int] = Field(default=200, ge=72, le=600, description="DPI resolution (72-600)")
    quality: Optional[int] = Field(default=85, ge=1, le=100, description="JPEG quality (1-100)")
    first_page: Optional[int] = Field(default=None, ge=1, description="First page to convert (1-indexed)")
    last_page: Optional[int] = Field(default=None, ge=1, description="Last page to convert (1-indexed)")
    upload_to_minio: Optional[bool] = Field(default=True, description="Upload images to MinIO")
    file_name_prefix: Optional[str] = Field(default=None, description="Filename prefix for MinIO")

class PdfConvertResponse(BaseModel):
    """PDF 转图片响应模型"""
    task_id: str
    status: str
    message: str

class ImageInfo(BaseModel):
    """图片信息模型"""
    page_number: int
    filename: str
    url: Optional[str] = None
    file_size: int

class PdfConvertResult(BaseModel):
    """PDF 转图片结果模型"""
    total_pages: int
    converted_pages: int
    images: List[ImageInfo]
    original_filename: str

def background_pdf_convert_task(
    token: CancellationToken,
    task_id: str,
    file_data: bytes,
    original_filename: str,
    dpi: int = 200,
    quality: int = 85,
    first_page: Optional[int] = None,
    last_page: Optional[int] = None,
    upload_to_minio: bool = True,
    file_name_prefix: Optional[str] = None
) -> Dict[str, Any]:
    """
    后台执行 PDF 转图片任务（使用 ExecutorManager）
    
    Args:
        token: 取消令牌（用于协作式取消）
        task_id: 任务ID
        file_data: PDF 文件二进制数据
        original_filename: 原始文件名
        dpi: DPI 分辨率
        quality: JPEG 质量
        first_page: 起始页码（可选）
        last_page: 结束页码（可选）
        upload_to_minio: 是否上传到 MinIO
        file_name_prefix: 文件名前缀（可选）
    
    Returns:
        转换结果字典
    """
    try:
        logger.info(f"开始 PDF 转图片任务: {task_id}")
        
        # 检查是否被取消
        if token.is_cancelled():
            logger.warning(f"任务 {task_id} 在开始前被取消")
            return {"status": "cancelled", "message": "任务已取消"}
        
        # 获取 PDF 总页数
        total_pages = get_pdf_page_count(file_data)
        logger.info(f"PDF 文件 {original_filename} 共有 {total_pages} 页")
        
        # 验证页码范围
        if first_page and first_page > total_pages:
            return {
                "status": "error",
                "message": f"起始页码 {first_page} 超出范围（总页数：{total_pages}）"
            }
        
        if last_page and last_page > total_pages:
            last_page = total_pages
            logger.warning(f"结束页码超出范围，自动调整为 {last_page}")
        
        # 检查是否被取消
        if token.is_cancelled():
            logger.warning(f"任务 {task_id} 在转换前被取消")
            return {"status": "cancelled", "message": "任务已取消"}
        
        # 转换 PDF 为图片
        logger.info(f"开始转换 PDF: {original_filename} (DPI: {dpi}, Quality: {quality})")
        image_results = pdf_to_images(
            file_data=file_data,
            dpi=dpi,
            quality=quality,
            first_page=first_page,
            last_page=last_page
        )
        
        logger.info(f"成功转换 {len(image_results)} 页")
        
        # 处理转换结果
        images_info = []
        base_filename = os.path.splitext(original_filename)[0]
        
        for idx, (img_bytes, suggested_filename) in enumerate(image_results, start=1):
            # 检查是否被取消
            if token.is_cancelled():
                logger.warning(f"任务 {task_id} 在处理第 {idx} 张图片时被取消")
                return {"status": "cancelled", "message": "任务已取消"}
            
            page_num = (first_page or 1) + idx - 1
            
            # 生成文件名
            filename = f"{base_filename}_page_{page_num:03d}.jpg"
            
            url = None
            if upload_to_minio:
                # 上传到 MinIO
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                if file_name_prefix:
                    unique_filename = f"{file_name_prefix}/{unique_filename}"
                # 统一存入 temp 目录
                unique_filename = f"temp/{unique_filename}"
                
                logger.info(f"上传图片 {idx}/{len(image_results)}: {unique_filename}")
                url = upload_file_to_minio(img_bytes, unique_filename)
                filename = unique_filename
            
            images_info.append(
                ImageInfo(
                    page_number=page_num,
                    filename=filename,
                    url=url,
                    file_size=len(img_bytes)
                ).model_dump()
            )
        
        # 构建结果
        result = {
            "status": "success",
            "message": "PDF 转图片成功",
            "data": PdfConvertResult(
                total_pages=total_pages,
                converted_pages=len(image_results),
                images=images_info,
                original_filename=original_filename
            ).model_dump()
        }
        
        logger.info(f"PDF 转图片任务 {task_id} 成功完成")
        return result
        
    except Exception as e:
        error_msg = f"PDF 转图片失败: {str(e)}"
        logger.error(f"任务 {task_id} 失败: {error_msg}", exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "error": str(e)
        }

@router.post("/pdf/convert", response_model=PdfConvertResponse)
async def convert_pdf_to_images(
    file: UploadFile = File(...),
    request: PdfConvertRequest = PdfConvertRequest()
) -> PdfConvertResponse:
    """
    异步转换 PDF 为图片（使用 ExecutorManager）
    
    Args:
        file: 待转换的 PDF 文件
        request: 转换配置参数
    
    Returns:
        包含任务ID的响应（客户端可通过 task_id 查询结果）
    """
    try:
        logger.info(f"收到 PDF 转图片请求: {file.filename}")
        
        # 验证文件类型
        if file.content_type not in SUPPORTED_PDF_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 PDF 文件"
            )
        
        # 读取文件数据
        file_data = await file.read()
        
        # 验证文件大小（可选，避免过大文件）
        file_size_mb = len(file_data) / (1024 * 1024)
        if file_size_mb > 100:  # 限制 100MB
            raise HTTPException(
                status_code=400,
                detail=f"文件过大: {file_size_mb:.2f} MB，最大支持 100 MB"
            )
        
        logger.info(f"PDF 文件大小: {file_size_mb:.2f} MB")
        
        # 生成唯一任务ID
        task_id = f"pdf_convert_{uuid.uuid4().hex}"
        
        # 提交到线程池执行
        # submit_task 会自动注入 token，然后传递其他参数
        executor_manager.submit_task(
            task_id,  # 任务ID（传给 submit_task 方法）
            background_pdf_convert_task,  # 执行函数
            task_id,  # 作为位置参数传递给函数（token 之后）
            file_data,
            file.filename,
            request.dpi,
            request.quality,
            request.first_page,
            request.last_page,
            request.upload_to_minio,
            request.file_name_prefix
        )
        
        logger.info(f"启动 PDF 转图片任务: {task_id}")
        return PdfConvertResponse(
            task_id=task_id,
            status="started",
            message="PDF 转图片任务已启动，请通过 task_id 查询结果"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动 PDF 转图片任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动转换任务失败: {str(e)}")

@router.get("/pdf/task/{task_id}")
async def get_pdf_convert_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取 PDF 转图片任务状态（使用 ExecutorManager）
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务状态信息
    """
    try:
        logger.debug(f"查询 PDF 转图片任务状态: {task_id}")
        
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
        logger.error(f"获取 PDF 转图片任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")

@router.get("/pdf/task/{task_id}/result")
async def get_pdf_convert_task_result(task_id: str) -> Dict[str, Any]:
    """
    获取 PDF 转图片任务结果（仅限已完成任务，使用 ExecutorManager）
    
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
        logger.error(f"获取 PDF 转图片任务结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务结果失败: {str(e)}")

@router.delete("/pdf/task/{task_id}")
async def cancel_pdf_convert_task(task_id: str) -> Dict[str, Any]:
    """
    取消 PDF 转图片任务（使用 ExecutorManager 协作式取消）
    
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
        logger.error(f"取消 PDF 转图片任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")

@router.post("/pdf/page-count")
async def get_pdf_pages(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    快速获取 PDF 文件页数（同步接口，用于预览）
    
    Args:
        file: PDF 文件
    
    Returns:
        页数信息
    """
    try:
        logger.info(f"获取 PDF 页数: {file.filename}")
        
        # 验证文件类型
        if file.content_type not in SUPPORTED_PDF_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}，仅支持 PDF 文件"
            )
        
        # 读取文件数据
        file_data = await file.read()
        
        # 获取页数
        page_count = get_pdf_page_count(file_data)
        
        return {
            "filename": file.filename,
            "total_pages": page_count,
            "message": f"PDF 文件共有 {page_count} 页"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 PDF 页数失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取页数失败: {str(e)}")

