"""鉴权路由：登录、刷新 Token。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.auth import (
    create_access_token,
    create_refresh_token,
    _decode_token,
    _ACCESS_TTL,
)
from ..schemas import LoginRequest, TokenResponse
from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.api.auth_router")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _verify_password(plain: str, hashed: str) -> bool:
    """使用 bcrypt 校验密码。"""
    import bcrypt
    return bcrypt.checkpw(plain.encode(), hashed.encode())


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户名密码登录，返回 Access Token 和 Refresh Token。"""
    row = (await db.execute(text(
        "SELECT id, password_hash, role, tenant_id, department "
        "FROM users WHERE username = :username"
    ), {"username": req.username})).fetchone()

    if not row or not _verify_password(req.password, row.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    access_token = create_access_token(
        user_id=str(row.id),
        username=req.username,
        role=row.role,
        tenant_id=str(row.tenant_id),
        department=row.department,
    )
    refresh_token = create_refresh_token(user_id=str(row.id))

    logger.info("用户登录成功", extra={"user_id": str(row.id), "username": req.username})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_ACCESS_TTL,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_token_str: str,
    db: AsyncSession = Depends(get_db),
):
    """用 Refresh Token 换新的 Access Token。"""
    payload = _decode_token(refresh_token_str)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="需要 Refresh Token")

    user_id = payload["sub"]
    row = (await db.execute(text(
        "SELECT id, username, role, tenant_id, department "
        "FROM users WHERE id = :id"
    ), {"id": user_id})).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="用户不存在")

    access_token = create_access_token(
        user_id=str(row.id),
        username=row.username,
        role=row.role,
        tenant_id=str(row.tenant_id),
        department=row.department,
    )
    new_refresh = create_refresh_token(user_id=str(row.id))

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=_ACCESS_TTL,
    )
