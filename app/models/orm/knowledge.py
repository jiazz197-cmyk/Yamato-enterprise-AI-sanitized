from app.core.time_utils import utcnow_naive

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from app.models.orm.platform.base import Base


class KnowledgeInstance(Base):
    __tablename__ = "knowledge_instance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, comment="知识库实例名称")
    description = Column(Text, default="", comment="知识库描述")
    type = Column(String(32), nullable=False, default="default", comment="知识库类型")  # 新增
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    # 可扩展：向量模型、访问权限等


class KnowledgeFragment(Base):
    __tablename__ = "knowledge_fragment"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("knowledge_instance.id"), nullable=False)
    content = Column(Text, nullable=False, comment="知识片段原文")
    vector = Column(Vector(1024), comment="向量化内容，可选")
    file_id = Column(Integer, nullable=True, comment="源文件ID")
    chunk_id = Column(String(64), unique=True, nullable=False, comment="分块唯一ID")
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    # 可扩展：来源、标签等


class KnowledgeResourceTag(Base):
    __tablename__ = "knowledge_resource_tag"
    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(Integer, nullable=False, comment="数据资源ID")
    tag = Column(String(64), nullable=False, comment="标签，如'可入知识库'")
    created_at = Column(DateTime, default=utcnow_naive)


# 新增：知识库实例权限表
class KnowledgeInstancePermission(Base):
    __tablename__ = "knowledge_instance_permission"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("knowledge_instance.id"), nullable=False, comment="知识库实例ID")
    user_id = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True, comment="用户ID")
    role_id = Column(Integer, nullable=True, comment="角色ID")
    permission = Column(String(32), nullable=False, comment="权限类型：read/write/admin")
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
