"""
数据库连接与会话管理(生产级)

核心特性:
- SQLAlchemy 2.0+ 原生支持(DeclarativeBase)
- 连接池配置优化(pool_size, max_overflow, pool_timeout)
- 连接健康检查(pool_pre_ping + pool_recycle)
- 连接池状态监控函数

使用示例:
    from app.core.database import Base
    from app.core.dependencies import get_db
    
    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
    
    @router.get("/users")
    def list_users(db: Session = Depends(get_db)):
        return db.execute(select(User)).scalars().all()
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import Pool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("db")
logger = get_logger("db")

# ==================== Engine 配置 ====================

DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI

# 🔧 连接池配置(根据实际负载调整)
POOL_SIZE = getattr(settings, "DB_POOL_SIZE", 10)        # 常驻连接数
MAX_OVERFLOW = getattr(settings, "DB_MAX_OVERFLOW", 20)  # 最大溢出连接数
POOL_TIMEOUT = getattr(settings, "DB_POOL_TIMEOUT", 30)  # 获取连接超时(秒)
POOL_RECYCLE = getattr(settings, "DB_POOL_RECYCLE", 3600)  # 连接回收时间(秒)

# 构建 Engine(生产级配置)
engine = create_engine(
    DATABASE_URL,
    echo=settings.DEBUG,  # 开发环境打印 SQL
    future=True,  # 启用 SQLAlchemy 2.0 行为
    pool_pre_ping=True,  # 连接使用前检查有效性(防止 "MySQL has gone away")
    pool_size=POOL_SIZE,  # 连接池大小
    max_overflow=MAX_OVERFLOW,  # 溢出连接数
    pool_timeout=POOL_TIMEOUT,  # 获取连接超时
    pool_recycle=POOL_RECYCLE,  # 连接回收(防止长时间连接失效)
    # isolation_level="READ COMMITTED",  # 事务隔离级别(可选)
    connect_args={
        # PostgreSQL 特定参数(可选)
        # "application_name": "ai_data_tool",
        # "connect_timeout": 10,
    },
)

# Session 工厂(必须 future=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,  # 禁用自动 flush(显式控制)
    autocommit=False,  # 禁用自动提交(手动事务管理)
    future=True,  # SQLAlchemy 2.0 模式
    expire_on_commit=False,  # 提交后对象不过期(可选,根据需求)
)


# ==================== Declarative Base (2.0+) ====================

class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 声明式基类
    
    所有 ORM 模型需继承此类:
        class User(Base):
            __tablename__ = "users"
            id: Mapped[int] = mapped_column(primary_key=True)
    """
    pass


# ==================== 事件监听(可选) ====================

@event.listens_for(Pool, "connect")
def receive_connect(dbapi_conn, connection_record):
    """连接建立时的回调(可用于设置连接级参数)"""
    logger.debug("数据库连接已建立")
    # 示例:设置 PostgreSQL 连接参数
    # dbapi_conn.execute("SET timezone='UTC'")


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """连接从池中取出时的回调(用于监控)"""
    logger.debug("连接已从池中获取")


# ==================== 工具函数 ====================

def check_db_connection() -> bool:
    """
    检查数据库连接是否健康
    
    Returns:
        bool: 连接正常返回 True,异常返回 False
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("数据库连接健康检查通过")
        return True
    except Exception as e:
        logger.error(f"数据库连接健康检查失败: {e}")
        return False


def get_pool_status() -> dict:
    """
    获取连接池状态信息(用于监控)
    
    Returns:
        dict: 连接池状态
            - pool_size: 连接池大小
            - checked_in: 已归还连接数
            - checked_out: 已取出连接数
            - overflow: 溢出连接数
            - total: 总连接数
    """
    pool_obj = engine.pool
    return {
        "pool_size": pool_obj.size(),
        "checked_in": pool_obj.checkedin(),
        "checked_out": pool_obj.checkedout(),
        "overflow": pool_obj.overflow(),
        "total": pool_obj.size() + pool_obj.overflow(),
    }


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    数据库会话上下文管理器(用于非 FastAPI 场景)
    
    使用示例:
        with get_db_context() as db:
            user = db.query(User).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"数据库操作失败: {e}")
        raise
    finally:
        db.close()


def dispose_engine():
    """
    释放所有连接池资源(用于应用关闭时清理)
    
    应在 FastAPI lifespan 的 shutdown 阶段调用:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield
            dispose_engine()  # 清理数据库连接池
    """
    try:
        engine.dispose()
        logger.info("数据库连接池已释放")
    except Exception as e:
        logger.error(f"释放数据库连接池失败: {e}")

