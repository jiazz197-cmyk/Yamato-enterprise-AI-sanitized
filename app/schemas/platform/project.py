from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# 项目空间相关Schema
class ProjectSpaceBase(BaseModel):
    name: str = Field(..., description="项目空间名称", max_length=100)
    description: Optional[str] = Field(None, description="项目空间描述")


class ProjectSpaceCreate(ProjectSpaceBase):
    pass


class ProjectSpaceUpdate(BaseModel):
    name: Optional[str] = Field(None, description="项目空间名称", max_length=100)
    description: Optional[str] = Field(None, description="项目空间描述")
    status: Optional[ProjectStatus] = Field(None, description="项目状态")


class ProjectSpaceResponse(ProjectSpaceBase):
    id: int
    status: ProjectStatus
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    member_count: Optional[int] = Field(None, description="成员数量")
    task_count: Optional[int] = Field(None, description="任务数量")

    class Config:
        from_attributes = True


# 项目成员相关Schema
class ProjectMemberBase(BaseModel):
    user_id: int = Field(..., description="用户ID")
    role: str = Field(..., description="成员角色", max_length=50)


class ProjectMemberCreate(ProjectMemberBase):
    pass


class ProjectMemberUpdate(BaseModel):
    role: Optional[str] = Field(None, description="成员角色", max_length=50)
    is_active: Optional[bool] = Field(None, description="是否活跃")


class ProjectMemberResponse(ProjectMemberBase):
    id: int
    project_id: int
    joined_at: datetime
    is_active: bool
    user_name: Optional[str] = Field(None, description="用户姓名")
    user_email: Optional[str] = Field(None, description="用户邮箱")

    class Config:
        from_attributes = True


# 项目任务相关Schema
class ProjectTaskBase(BaseModel):
    title: str = Field(..., description="任务标题", max_length=200)
    description: Optional[str] = Field(None, description="任务描述")
    assigned_to: Optional[int] = Field(None, description="指派给的用户ID")
    priority: TaskPriority = Field(TaskPriority.MEDIUM, description="任务优先级")
    due_date: Optional[datetime] = Field(None, description="截止日期")


class ProjectTaskCreate(ProjectTaskBase):
    pass


class ProjectTaskUpdate(BaseModel):
    title: Optional[str] = Field(None, description="任务标题", max_length=200)
    description: Optional[str] = Field(None, description="任务描述")
    assigned_to: Optional[int] = Field(None, description="指派给的用户ID")
    status: Optional[TaskStatus] = Field(None, description="任务状态")
    priority: Optional[TaskPriority] = Field(None, description="任务优先级")
    due_date: Optional[datetime] = Field(None, description="截止日期")


class ProjectTaskResponse(ProjectTaskBase):
    id: int
    project_id: int
    created_by: int
    status: TaskStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    assignee_name: Optional[str] = Field(None, description="指派用户姓名")
    creator_name: Optional[str] = Field(None, description="创建者姓名")

    class Config:
        from_attributes = True


# 数据共享相关Schema
class DataShareBase(BaseModel):
    target_project_id: int = Field(..., description="目标项目空间ID")
    resource_type: str = Field(..., description="资源类型", max_length=50)
    resource_id: int = Field(..., description="资源ID")
    resource_name: str = Field(..., description="资源名称", max_length=200)
    request_reason: Optional[str] = Field(None, description="申请原因")


class DataShareCreate(DataShareBase):
    pass


class DataShareUpdate(BaseModel):
    status: Optional[str] = Field(None, description="申请状态")
    review_comment: Optional[str] = Field(None, description="审核意见")


class DataShareResponse(DataShareBase):
    id: int
    project_id: int
    status: str
    requested_by: int
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    created_at: datetime
    requester_name: Optional[str] = Field(None, description="申请人姓名")
    reviewer_name: Optional[str] = Field(None, description="审核人姓名")
    project_name: Optional[str] = Field(None, description="申请方项目名称")
    target_project_name: Optional[str] = Field(None, description="目标项目名称")

    class Config:
        from_attributes = True


# 统计信息Schema
class ProjectStatistics(BaseModel):
    project_id: int
    task_count: int
    member_count: int
    share_count: int


# 列表响应Schema
class ProjectSpaceListResponse(BaseModel):
    items: List[ProjectSpaceResponse]
    total: int
    count: int


class ProjectMemberListResponse(BaseModel):
    items: List[ProjectMemberResponse]
    total: int
    count: int


class ProjectTaskListResponse(BaseModel):
    items: List[ProjectTaskResponse]
    total: int
    count: int


class DataShareListResponse(BaseModel):
    items: List[DataShareResponse]
    total: int
    count: int
