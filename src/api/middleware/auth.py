"""JWT 鉴权中间件：RS256 签名，无状态验证，注入 UserInfo 到请求上下文。"""

from __future__ import annotations

import os
import time
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..schemas import UserInfo
from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.api.auth")

_bearer = HTTPBearer(auto_error=True)

# JWT 配置从环境变量读取，不写入配置文件
_JWT_SECRET  = os.environ.get("JWT_SECRET", "change-this-in-production")
_JWT_ALGO    = os.environ.get("JWT_ALGORITHM", "HS256")
_ACCESS_TTL  = int(os.environ.get("JWT_ACCESS_TTL_SECONDS", "7200"))    # 2 小时
_REFRESH_TTL = int(os.environ.get("JWT_REFRESH_TTL_SECONDS", "604800"))  # 7 天


def create_access_token(user_id: str, username: str, role: str,
                         tenant_id: str, department: str | None) -> str:
    now = int(time.time())
    payload = {
        "sub":        user_id,
        "username":   username,
        "role":       role,
        "tenant_id":  tenant_id,
        "department": department,
        "iat":        now,
        "exp":        now + _ACCESS_TTL,
        "type":       "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def create_refresh_token(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub":  user_id,
        "iat":  now,
        "exp":  now + _REFRESH_TTL,
        "type": "refresh",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token 无效")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserInfo:
    """FastAPI Depends 注入，从 Authorization: Bearer <token> 解析用户信息。"""
    payload = _decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="需要 Access Token")
    return UserInfo(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
        tenant_id=payload["tenant_id"],
        department=payload.get("department"),
    )


def require_role(*roles: str):
    """工厂函数，生成指定角色的权限依赖。"""
    def _check(user: UserInfo = Depends(get_current_user)) -> UserInfo:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"该操作需要角色：{', '.join(roles)}")
        return user
    return _check
