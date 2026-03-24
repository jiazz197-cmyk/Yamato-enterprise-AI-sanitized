"""
文件管理路由模块
提供文件上传、下载、删除、列表查询等服务
"""
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.storage import (
    download_object_stream,
    upload_stream_to_minio,
    delete_from_minio,
    get_minio_client,
    MINIO_BUCKET_NAME,
    STREAM_CHUNK_SIZE,
)
from app.models.orm.file_resource import FileResource
from app.models.orm.platform.user import User, UserRole
from app.core.security import get_current_user, normalize_self_uploader

router = APIRouter()
logger = get_logger("file_manager")


# ==================== 响应模型 ====================
class FileUploadResponse(BaseModel):
    """文件上传响应"""
    id: int
    file_name: str
    unique_name: str
    minio_path: str
    content_type: str
    file_size: int
    uploader: str
    created_at: datetime
    message: str = "文件上传成功"


class FileInfoResponse(BaseModel):
    """文件信息响应"""
    id: int
    file_name: str
    unique_name: str
    content_type: str
    file_size: int
    uploader: str
    created_at: datetime
    updated_at: datetime


class FileListResponse(BaseModel):
    """文件列表响应"""
    total: int
    page: int
    page_size: int
    items: List[FileInfoResponse]


class DeleteResponse(BaseModel):
    """删除响应"""
    success: bool
    message: str
    deleted_id: int


class BatchDeleteResponse(BaseModel):
    """批量删除响应"""
    success_count: int
    failed_count: int
    failed_ids: List[int] = []
    message: str


# ==================== 辅助函数 ====================
def _generate_unique_filename(original_filename: str) -> str:
    """生成唯一文件名，保留原始扩展名"""
    suffix = Path(original_filename).suffix
    unique_id = uuid.uuid4().hex
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{unique_id}{original_filename}"


def _get_file_or_404(db: Session, file_id: int) -> FileResource:
    """获取文件记录，不存在则抛出 404"""
    file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
    if not file_record:
        raise NotFoundError(f"文件 ID {file_id} 不存在")
    return file_record


# ==================== 路由定义 ====================
@router.post("/upload", response_model=FileUploadResponse, summary="上传文件")
async def upload_file(
    file: UploadFile = File(..., description="要上传的文件"),
    uploader: str = Query(default="anonymous", description="上传者标识（仅允许传本人信息）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传文件到 MinIO 并记录元数据到数据库。
    
    - **file**: 上传的文件对象
    - **uploader**: 上传者标识（可选，默认为 anonymous）
    
    返回：文件元数据信息
    """
    try:
        # 验证文件
        if not file.filename:
            raise ValidationError("文件名不能为空")
        
        # 尝试获取文件大小（避免读取整个文件）
        file_size = getattr(file, 'size', None) or -1
        
        # 生成唯一文件名
        unique_name = _generate_unique_filename(file.filename)
        minio_path = f"uploads/{unique_name}"
        
        # 流式上传到 MinIO（无需一次性读入内存）
        content_type = file.content_type or "application/octet-stream"
        result = upload_stream_to_minio(file.file, minio_path, file_size, content_type)
        
        if result.startswith("Error"):
            raise HTTPException(status_code=500, detail=result)
        
        # 如果文件大小未知，需要获取实际大小
        if file_size == -1:
            try:
                minio_client = get_minio_client()
                stat = minio_client.stat_object(MINIO_BUCKET_NAME, minio_path)
                file_size = stat.size
            except Exception as e:
                logger.warning(f"无法获取上传文件大小: {e}")
                file_size = 0
        
        # 保存元数据到数据库
        normalized_uploader = normalize_self_uploader(uploader, current_user)

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
        
        logger.info(f"文件上传成功: {file.filename} -> {minio_path} (ID: {file_record.id})")
        
        return FileUploadResponse(
            id=file_record.id,
            file_name=file_record.file_name,
            unique_name=file_record.unique_name,
            minio_path=file_record.minio_object_path,
            content_type=file_record.content_type,
            file_size=file_record.file_size,
            uploader=file_record.uploader,
            created_at=file_record.created_at,
        )
        
    except ValidationError:
        raise
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


@router.get("/download/{file_id}", summary="下载文件")
async def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    根据文件 ID 下载文件。
    
    - **file_id**: 文件记录 ID
    
    返回：文件流
    """
    try:
        # 查询文件记录
        file_record = _get_file_or_404(db, file_id)
        if current_user.role != UserRole.superuser and file_record.uploader != current_user.username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权下载该文件")
        
        # ✅ 使用 context manager 防止资源泄漏
        # 创建生成器函数，在 StreamingResponse 中延迟执行
        def file_stream_generator():
            with download_object_stream(file_record.minio_object_path) as response:
                # ✅ 使用 1MB chunk 提升下载速度
                for chunk in response.stream(STREAM_CHUNK_SIZE):
                    yield chunk
        
        logger.info(f"文件下载: {file_record.file_name} (ID: {file_id})")
        
        # 返回流式响应
        return StreamingResponse(
            file_stream_generator(),
            media_type=file_record.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{file_record.file_name}"'
            }
        )
        
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件下载失败 (ID: {file_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件下载失败: {str(e)}")


@router.get("/info/{file_id}", response_model=FileInfoResponse, summary="获取文件信息")
async def get_file_info(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    根据 ID 获取文件元数据信息。
    
    - **file_id**: 文件记录 ID
    """
    file_record = _get_file_or_404(db, file_id)
    if current_user.role != UserRole.superuser and file_record.uploader != current_user.username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该文件信息")
    
    return FileInfoResponse(
        id=file_record.id,
        file_name=file_record.file_name,
        unique_name=file_record.unique_name,
        content_type=file_record.content_type,
        file_size=file_record.file_size,
        uploader=file_record.uploader,
        created_at=file_record.created_at,
        updated_at=file_record.updated_at,
    )


@router.get("/list", response_model=FileListResponse, summary="获取文件列表")
async def list_files(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    uploader: Optional[str] = Query(None, description="按上传者筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    分页查询文件列表。
    
    - **page**: 页码（从 1 开始）
    - **page_size**: 每页数量（1-100）
    - **uploader**: 可选，按上传者筛选
    """
    try:
        # 构建查询
        query = db.query(FileResource)
        
        if current_user.role != UserRole.superuser:
            query = query.filter(FileResource.uploader == current_user.username)
        elif uploader:
            query = query.filter(FileResource.uploader == uploader)
        
        # 获取总数
        total = query.count()
        
        # 分页
        offset = (page - 1) * page_size
        items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
        
        # 转换为响应模型
        file_list = [
            FileInfoResponse(
                id=item.id,
                file_name=item.file_name,
                unique_name=item.unique_name,
                content_type=item.content_type,
                file_size=item.file_size,
                uploader=item.uploader,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ]
        
        return FileListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=file_list,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


@router.delete("/delete/{file_id}", response_model=DeleteResponse, summary="删除文件")
async def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    根据 ID 删除文件（同时删除 MinIO 对象和数据库记录）。
    
    - **file_id**: 文件记录 ID
    """
    try:
        # 查询文件记录
        file_record = _get_file_or_404(db, file_id)
        if current_user.role != UserRole.superuser and file_record.uploader != current_user.username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该文件")
        
        # 从 MinIO 删除
        delete_success = delete_from_minio(file_record.minio_object_path)
        
        if not delete_success:
            logger.warning(f"MinIO 删除失败，但继续删除数据库记录: {file_record.minio_object_path}")
        
        # 从数据库删除
        db.delete(file_record)
        db.commit()
        
        logger.info(f"文件删除成功: {file_record.file_name} (ID: {file_id})")
        
        return DeleteResponse(
            success=True,
            message="文件删除成功",
            deleted_id=file_id,
        )
        
    except NotFoundError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件删除失败 (ID: {file_id}): {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"文件删除失败: {str(e)}")


@router.post("/batch-delete", response_model=BatchDeleteResponse, summary="批量删除文件")
async def batch_delete_files(
    file_ids: List[int] = Query(..., description="要删除的文件 ID 列表"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量删除多个文件。
    
    - **file_ids**: 文件 ID 列表
    """
    if current_user.role != UserRole.superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员可批量删除")

    success_count = 0
    failed_count = 0
    failed_ids = []
    
    for file_id in file_ids:
        try:
            file_record = db.query(FileResource).filter(FileResource.id == file_id).first()
            if not file_record:
                failed_count += 1
                failed_ids.append(file_id)
                continue
            
            # 删除 MinIO 对象
            delete_from_minio(file_record.minio_object_path)
            
            # 删除数据库记录
            db.delete(file_record)
            db.commit()
            success_count += 1
            
        except Exception as e:
            logger.error(f"批量删除失败 (ID: {file_id}): {e}")
            failed_count += 1
            failed_ids.append(file_id)
            db.rollback()
    
    logger.info(f"批量删除完成: 成功 {success_count}, 失败 {failed_count}")
    
    return BatchDeleteResponse(
        success_count=success_count,
        failed_count=failed_count,
        failed_ids=failed_ids,
        message=f"批量删除完成: 成功 {success_count} 个, 失败 {failed_count} 个",
    )


@router.get("/search", response_model=FileListResponse, summary="搜索文件")
async def search_files(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    根据关键词搜索文件（搜索文件名）。
    
    - **keyword**: 搜索关键词
    - **page**: 页码
    - **page_size**: 每页数量
    """
    try:
        # 模糊查询
        query = db.query(FileResource).filter(
            FileResource.file_name.ilike(f"%{keyword}%")
        )
        if current_user.role != UserRole.superuser:
            query = query.filter(FileResource.uploader == current_user.username)
        
        total = query.count()
        offset = (page - 1) * page_size
        items = query.order_by(FileResource.created_at.desc()).offset(offset).limit(page_size).all()
        
        file_list = [
            FileInfoResponse(
                id=item.id,
                file_name=item.file_name,
                unique_name=item.unique_name,
                content_type=item.content_type,
                file_size=item.file_size,
                uploader=item.uploader,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ]
        
        return FileListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=file_list,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"搜索文件失败: {str(e)}")
