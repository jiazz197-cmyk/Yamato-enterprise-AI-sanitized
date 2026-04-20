"""FastAPI 依赖（数据库会话、RAG 实例等）。"""
from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.logging import get_logger

logger = get_logger("dependencies")


def get_db() -> Generator[Session, None, None]:
    """请求级 Session：正常结束 commit；HTTPException 与其它异常 rollback；finally 关闭连接。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except HTTPException as e:
        db.rollback()
        logger.warning(f"数据库操作触发HTTP异常,已回滚事务: {e.status_code}: {e.detail}")
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"数据库操作异常,已回滚事务: {e}", exc_info=True)
        raise
    finally:
        db.close()


def get_rag_instance(request: Request):
    """从 app.state.rag 取 RAG；未初始化则为 None。"""
    return getattr(request.app.state, 'rag', None)
