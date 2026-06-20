from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class KnowledgeInstanceBase(BaseModel):
    name: str
    description: Optional[str] = ""
    type: str = "default"


class KnowledgeInstanceCreate(KnowledgeInstanceBase):
    pass


class KnowledgeInstanceOut(KnowledgeInstanceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeFragmentBase(BaseModel):
    content: str
    vector: Optional[str] = None
    file_id: Optional[int] = None


class KnowledgeFragmentCreate(KnowledgeFragmentBase):
    instance_id: int


class KnowledgeFragmentOut(KnowledgeFragmentBase):
    id: int
    instance_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeResourceTagOut(BaseModel):
    id: int
    resource_id: int
    tag: str
    created_at: datetime

    class Config:
        from_attributes = True


# 知识库实例权限表 schema
class KnowledgeInstancePermissionBase(BaseModel):
    instance_id: int
    user_id: Optional[UUID] = None
    role_id: Optional[int] = None
    permission: str


class KnowledgeInstancePermissionCreate(KnowledgeInstancePermissionBase):
    pass


class KnowledgeInstancePermissionOut(KnowledgeInstancePermissionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[str] = None


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseOut(KnowledgeBaseBase):
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
