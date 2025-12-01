# dependencies.py
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.orm.platform.user import User


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    通过 Authorization Bearer token 获取当前用户（JWT方式）
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header.split(" ")[1]
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token无效")
    except Exception:
        raise HTTPException(status_code=401, detail="Token无效")
    user = db.query(User).filter_by(id=int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def require_roles(*role_names):
    def role_checker(
            current_user: User = Depends(get_current_user)
    ):
        user_roles = {role.name for role in current_user.roles}
        if not any(role in user_roles for role in role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问"
            )
        return current_user

    return role_checker


def get_rag_instance(request: Request):
    """获取全局RAG实例"""
    return getattr(request.app.state, 'rag', None)
