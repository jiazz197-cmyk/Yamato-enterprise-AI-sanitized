from typing import List

from pydantic import BaseModel


# 精简版用户
class UserSimple(BaseModel):
    id: int
    username: str


class RoleCreate(BaseModel):
    name: str
    description: str = ""


class RoleRead(BaseModel):
    id: int
    name: str
    description: str
    users: List[UserSimple] = []


class RoleUpdate(BaseModel):
    name: str = ""
    description: str = ""


class UserIds(BaseModel):
    user_ids: List[int]


class PermissionIds(BaseModel):
    permission_ids: List[int]


RoleRead.model_rebuild()
