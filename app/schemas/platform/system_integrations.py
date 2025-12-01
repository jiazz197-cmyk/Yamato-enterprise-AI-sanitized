from typing import Optional

from pydantic import BaseModel


class IntegrationCreate(BaseModel):
    name: str
    type: str
    config: dict
    status: Optional[str] = None

class IntegrationRead(BaseModel):
    id: int
    name: str
    type: str
    config: dict
    status: str

class IntegrationUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    config: Optional[dict] = None
    status: Optional[str] = None 