from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text

from app.models.orm.platform.base import Base


class PlatformAuditLog(Base):
    __tablename__ = 'platform_audit_logs'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    action = Column(String(128), nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
