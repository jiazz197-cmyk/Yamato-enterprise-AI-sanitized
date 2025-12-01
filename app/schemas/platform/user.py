from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr


# 精简版角色
class RoleSimple(BaseModel):
    id: int
    name: str


class UserCreate(BaseModel):
    username: str
    name: Optional[str] = None  # 姓名
    email: EmailStr
    phone: Optional[str] = None  # 手机号码
    department: Optional[str] = None  # 部门
    avatar: Optional[str] = None  # 头像
    password: str
    role_ids: Optional[List[int]] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None  # 姓名
    email: Optional[EmailStr] = None
    phone: Optional[str] = None  # 手机号码
    department: Optional[str] = None  # 部门
    avatar: Optional[str] = None  # 头像
    password: Optional[str] = None
    role_ids: Optional[List[int]] = None


class UserRead(BaseModel):
    id: int
    username: str
    name: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    department: Optional[str] = None
    avatar: Optional[str] = None
    is_active: Optional[bool] = True
    roles: List[RoleSimple] = []


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


# 用户偏好设置
class UserPreferences(BaseModel):
    id: int
    user_id: int
    email_notify: bool = True
    in_app_notify: bool = True
    theme: str = 'system'  # light/dark/system
    language: str = 'zh-CN'


# 用户登录历史
class UserLoginHistory(BaseModel):
    id: int
    user_id: int
    login_time: datetime
    ip: Optional[str] = None
    device: Optional[str] = None

    class Config:
        from_attributes = True


# 用户订阅数据产品
class UserSubscription(BaseModel):
    id: int
    user_id: int
    product_id: int
    subscribe_time: Optional[str] = None
