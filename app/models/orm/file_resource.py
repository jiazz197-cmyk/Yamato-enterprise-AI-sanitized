from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime

from app.models.orm.platform.base import Base


class FileResource(Base):
    __tablename__ = "file_resource"
    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(256), nullable=False, comment="原始文件名")
    unique_name = Column(String(256), nullable=False, comment="唯一文件名")
    minio_object_path = Column(String(512), nullable=False, comment="MinIO对象路径")
    uploader = Column(String(64), default="", comment="上传者")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    instance_id = Column(Integer, nullable=True, comment="知识库ID")
