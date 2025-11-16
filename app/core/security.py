import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException, status
from fastapi import Security
from fastapi.security.api_key import APIKeyHeader
from passlib.context import CryptContext

from app.core.config import settings

API_KEY_NAME = "X-API-KEY"  # Common practice for API key header name
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(api_key_header_value: str = Security(api_key_header)):
    """Dependency to validate the API key."""
    if api_key_header_value == settings.INTERNAL_API_KEY:
        return api_key_header_value
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials or invalid API Key"
        )


# Example of how to use it in an endpoint:
# from fastapi import Depends
# @router.get("/secure-data", dependencies=[Depends(get_api_key)])
# async def get_secure_data():
#     return {"message": "This is secure data"}

# 配置密码上下文，明确指定使用 bcrypt 算法
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # 设置加密轮数
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        # 记录错误并返回 False
        print(f"Password verification error: {str(e)}")
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())  # 生成唯一的jti
    to_encode.update({"exp": expire, "jti": jti})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt, jti


def create_refresh_token(data: dict):
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
