"""SQLAlchemy 2.0：Engine、SessionLocal、Base 与表初始化。"""
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import Pool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("database.pool")

DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI

POOL_SIZE = getattr(settings, "DB_POOL_SIZE", 10)
MAX_OVERFLOW = getattr(settings, "DB_MAX_OVERFLOW", 20)
POOL_TIMEOUT = getattr(settings, "DB_POOL_TIMEOUT", 30)
POOL_RECYCLE = getattr(settings, "DB_POOL_RECYCLE", 3600)

engine = create_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    connect_args={},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """ORM 模型基类。"""
    pass


@event.listens_for(Pool, "connect")
def receive_connect(dbapi_conn, connection_record):
    """连接入池时可在此设会话级参数。"""
    logger.debug("数据库连接已建立")


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """连接被取出时触发，便于打调试日志。"""
    logger.debug("连接已从池中获取")


def check_db_connection() -> bool:
    """SELECT 1 探活。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("数据库连接健康检查通过")
        return True
    except Exception as e:
        logger.error(f"数据库连接健康检查失败: {e}")
        return False


def get_pool_status() -> dict:
    """连接池占用概况，供监控用。"""
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
    """非 FastAPI 场景用的 with 会话（commit/rollback/close）。"""
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


def init_db_tables():
    """create_all；并尝试给 data_pending 补 status 列；最后写种子 superuser。"""
    try:
        from app.models.orm.closing_form import PendingForm  # noqa: F401
        from app.models.orm.file_resource import FileResource  # noqa: F401
        from app.models.orm.quotation_task import QuotationTask  # noqa: F401
        from app.models.orm.knowledge import KnowledgeInstance  # noqa: F401
        from app.models.orm.platform import (  # noqa: F401
            User, UserLoginHistory, UserPreferences, UserSubscription,
            Role, Permission, user_role_table, role_permission_table,
            ProjectSpace, ProjectMember, ProjectTask, DataShare,
            PlatformAuditLog, MigrationLog, MigrationBackup,
        )

        Base.metadata.create_all(bind=engine)

        try:
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name='data_pending' AND column_name='status'"
                )).fetchone()

                if not result:
                    logger.info("[info] 发现 data_pending 表缺少 status 列，正在添加...")
                    conn.execute(text(
                        "ALTER TABLE data_pending ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending'"
                    ))
                    conn.commit()
                    logger.info("[success] 成功向 data_pending 表添加 status 列")
        except Exception as mig_e:
            logger.error(f"[warning] data_pending 表迁移失败（如果表还未创建可忽略此错误）: {mig_e}")

        try:
            with engine.connect() as conn:
                for col in ("image_url_1", "image_url_2"):
                    result = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='data_pending' AND column_name=:col"
                    ), {"col": col}).fetchone()
                    if not result:
                        logger.info(f"[info] 发现 data_pending 表缺少 {col} 列，正在添加...")
                        conn.execute(text(
                            f"ALTER TABLE data_pending ADD COLUMN {col} VARCHAR(512)"
                        ))
                        conn.commit()
                        logger.info(f"[success] 成功向 data_pending 表添加 {col} 列")
        except Exception as mig_e:
            logger.error(f"[warning] data_pending image_url 列迁移失败: {mig_e}")

        try:
            with engine.connect() as conn:
                owner_ip_column = conn.execute(text(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name='quotation_tasks' AND column_name='owner_ip'"
                )).fetchone()
                if not owner_ip_column:
                    logger.info("[info] 发现 quotation_tasks 表缺少 owner_ip 列，正在添加...")
                    conn.execute(text("ALTER TABLE quotation_tasks ADD COLUMN owner_ip VARCHAR(64)"))
                    conn.commit()
                    logger.info("[success] 成功向 quotation_tasks 表添加 owner_ip 列")

                display_name_column = conn.execute(text(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name='quotation_tasks' AND column_name='display_name'"
                )).fetchone()
                if not display_name_column:
                    logger.info("[info] 发现 quotation_tasks 表缺少 display_name 列，正在添加...")
                    conn.execute(text("ALTER TABLE quotation_tasks ADD COLUMN display_name VARCHAR(256)"))
                    conn.execute(text(
                        "UPDATE quotation_tasks "
                        "SET display_name = COALESCE(NULLIF(uploaded_file_name, ''), task_id) "
                        "WHERE display_name IS NULL"
                    ))
                    conn.execute(text("ALTER TABLE quotation_tasks ALTER COLUMN display_name SET NOT NULL"))
                    conn.commit()
                    logger.info("[success] 成功向 quotation_tasks 表添加 display_name 列")

                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_quotation_tasks_owner_ip "
                    "ON quotation_tasks (owner_ip)"
                ))
                conn.commit()

                awaiting_col = conn.execute(text(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name='quotation_tasks' AND column_name='awaiting_approval_at'"
                )).fetchone()
                if not awaiting_col:
                    logger.info("[info] 发现 quotation_tasks 表缺少 awaiting_approval_at 列，正在添加...")
                    conn.execute(text(
                        "ALTER TABLE quotation_tasks ADD COLUMN awaiting_approval_at TIMESTAMP NULL"
                    ))
                    conn.commit()
                    logger.info("[success] 成功向 quotation_tasks 表添加 awaiting_approval_at 列")
        except Exception as mig_e:
            logger.error(f"[warning] quotation_tasks.owner_ip/display_name 迁移失败（如果表还未创建可忽略此错误）: {mig_e}")

        table_names = [table.name for table in Base.metadata.sorted_tables]
        logger.info(f"[success] 数据库表初始化完成，共 {len(table_names)} 个表: {', '.join(table_names)}")

    except Exception as e:
        logger.error(f"[error] 数据库表初始化失败: {e}", exc_info=True)

    _seed_superuser()


def _seed_superuser():
    """按配置写入 superuser 账号（未配置则跳过）。"""
    try:
        from app.models.orm.platform.user import User, UserRole
        from app.core.security import hash_password

        username: Optional[str] = settings.BOOTSTRAP_SUPERUSER_USERNAME
        email: Optional[str] = settings.BOOTSTRAP_SUPERUSER_EMAIL
        password: Optional[str] = settings.BOOTSTRAP_SUPERUSER_PASSWORD

        if not username or not email or not password:
            logger.info("[info] 未配置 BOOTSTRAP_SUPERUSER_*，跳过 superuser 种子写入")
            return

        db = SessionLocal()
        try:
            exists = db.query(User).filter(User.username == username).first()
            if not exists:
                su = User(
                    username=username,
                    email=email,
                    password=hash_password(password),
                    role=UserRole.superuser,
                    is_active=True,
                )
                db.add(su)
                db.commit()
                logger.info(f"[success] superuser 账号已创建 ({username} / {email})")
            else:
                logger.info(f"[info] superuser 账号已存在，跳过种子写入: {username}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[error] superuser 种子写入失败: {e}", exc_info=True)


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

