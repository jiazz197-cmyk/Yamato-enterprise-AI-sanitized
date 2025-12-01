from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from app.models.orm.platform.base import Base
from app.models.orm.platform.user_role import user_role_table


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    roles = relationship(
        "Role",
        secondary=user_role_table,
        back_populates="users"
    )
    name = Column(String(64), nullable=True)  # 姓名
    phone = Column(String(32), nullable=True)  # 手机号码
    department = Column(String(64), nullable=True)  # 部门
    avatar = Column(String(256), nullable=True)  # 头像URL或路径 


class UserLoginHistory(Base):
    __tablename__ = 'user_login_history'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    login_time = Column(DateTime, default=datetime.utcnow)
    ip = Column(String(64), nullable=True)
    device = Column(String(128), nullable=True)


class UserPreferences(Base):
    __tablename__ = 'user_preferences'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    email_notify = Column(Boolean, default=True)  # 邮件通知开关
    in_app_notify = Column(Boolean, default=True)  # 系统内通知开关
    theme = Column(String(16), default='system')  # 主题颜色: light/dark/system
    language = Column(String(16), default='zh-CN')  # 界面语言 


class UserSubscription(Base):
    __tablename__ = 'user_subscriptions'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    product_id = Column(Integer, nullable=False)  # 数据产品ID，实际可关联产品表
    subscribe_time = Column(DateTime, default=datetime.utcnow)
