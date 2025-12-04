"""
FastAPI 依赖定义
"""
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.logging import get_logger

logger = get_logger("dependencies")


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话(FastAPI 依赖注入)
    
    特性:
    - 自动提交成功的事务
    - 异常时自动回滚
    - 确保连接资源释放
    - 记录异常日志
    
    使用方式:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            # SQLAlchemy 2.0 风格
            return db.execute(select(Item)).scalars().all()
        
        @router.post("/items")
        def create_item(item: ItemCreate, db: Session = Depends(get_db)):
            new_item = Item(**item.dict())
            db.add(new_item)
            db.commit()  # 手动提交(或依赖自动提交)
            db.refresh(new_item)
            return new_item
    
    ⚠️ 注意事项:
    1. 如果路由函数中显式调用了 db.commit(),则自动提交不会重复执行
    2. 如果需要更细粒度的事务控制,可以在路由中使用 db.begin()
    3. 异常会自动回滚,无需手动处理
    """
    db = SessionLocal()
    try:
        yield db
        # ✅ 请求成功时自动提交事务
        db.commit()
    except Exception as e:
        # ❌ 发生异常时回滚事务
        db.rollback()
        logger.error(f"数据库操作异常,已回滚事务: {e}", exc_info=True)
        raise  # 重新抛出异常,让 FastAPI 处理
    finally:
        # 🔒 确保会话关闭,释放连接回池
        db.close()


def get_rag_instance(request: Request):
    """
    获取 RAG 系统实例 (FastAPI 依赖注入)
    
    RAG 系统在应用启动时初始化并存储在 app.state.rag 中
    
    使用方式:
        @router.post("/db")
        def db(request: ChatRequest, rag_instance=Depends(get_rag_instance)):
            retriever = retriever_for_yamato.retriever(
                rag_system=rag_instance,
                collection_name=request.collection_name
            )
            return retriever.get_response(request.question)
    
    返回:
        RAG 系统实例，如果未初始化则返回 None
    """
    return getattr(request.app.state, 'rag', None)
