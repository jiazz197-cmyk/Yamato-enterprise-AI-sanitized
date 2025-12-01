from typing import Optional, List

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: int
    user_id: int
    action: str
    detail: Optional[str] = None
    created_at: str

class AuditLogListResponse(BaseModel):
    items: List[AuditLogRead]
    total: int
    count: int
