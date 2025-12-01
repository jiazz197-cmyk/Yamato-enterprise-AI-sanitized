from pydantic import BaseModel


class PermissionCreate(BaseModel):
    name: str
    description: str = ""


class PermissionRead(BaseModel):
    id: int
    name: str
    description: str


class PermissionUpdate(BaseModel):
    name: str = ""
    description: str = ""
