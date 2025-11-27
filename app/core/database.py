"""
数据库连接与会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# SQLAlchemy 连接串
DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI

# 创建 Engine，开启连接检测
engine = create_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    future=True,
)

# Session 工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Declarative 基类，模型需继承
Base = declarative_base()

