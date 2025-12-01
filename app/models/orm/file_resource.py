"""
文件资源 ORM 模型
用于记录上传到 MinIO 的文件元数据
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime

from app.core.database import Base


class FileResource(Base):
    """文件资源表"""
    __tablename__ = "file_resource"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(256), nullable=False, comment="原始文件名")
    unique_name = Column(String(256), nullable=False, unique=True, index=True, comment="唯一文件名")
    minio_object_path = Column(String(512), nullable=False, comment="MinIO对象路径")
    content_type = Column(String(128), default="application/octet-stream", comment="文件MIME类型")
    file_size = Column(Integer, nullable=True, comment="文件大小(字节)")
    uploader = Column(String(64), default="", index=True, comment="上传者")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def __repr__(self) -> str:
        return f"<FileResource(id={self.id}, file_name='{self.file_name}')>"

