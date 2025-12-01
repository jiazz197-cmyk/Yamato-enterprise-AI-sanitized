from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FileBase(BaseModel):
    file_name: str
    unique_name: str
    minio_object_path: str
    uploader: Optional[str] = ""
    instance_id: Optional[int] = None


class FileCreate(FileBase):
    pass


class FileOut(FileBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
