"""系统管理路由：健康检查、统计、审计日志查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.auth import UserInfo, require_role
from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.api.admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/health")
async def health_check():
    """健康检查，不鉴权，用于负载均衡探活。"""
    return {"status": "ok"}


@router.get("/stats")
async def system_stats(
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_role("admin")),
):
    """系统统计：文档数、检索量、各状态分布。"""
    stats = {}

    # 文档总数和状态分布
    doc_stats = (await db.execute(text(
        "SELECT status, COUNT(*) as cnt FROM documents "
        "WHERE tenant_id = :tid GROUP BY status"
    ), {"tid": user.tenant_id})).fetchall()
    stats["documents"] = {r.status: r.cnt for r in doc_stats}

    # 检索量（近 24 小时）
    search_count = (await db.execute(text(
        "SELECT COUNT(*) FROM audit_logs "
        "WHERE tenant_id = :tid AND action IN ('search', 'qa') "
        "AND created_at > NOW() - INTERVAL '24 hours'"
    ), {"tid": user.tenant_id})).scalar() or 0
    stats["searches_24h"] = search_count

    # 用户数
    user_count = (await db.execute(text(
        "SELECT COUNT(*) FROM users WHERE tenant_id = :tid"
    ), {"tid": user.tenant_id})).scalar() or 0
    stats["users"] = user_count

    return stats


@router.get("/audit-logs")
async def audit_logs(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    action: str | None = None,
    user_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_role("admin")),
):
    """查询审计日志，支持按操作类型和用户筛选。"""
    where = "WHERE tenant_id = :tid"
    params: dict = {"tid": user.tenant_id}

    if action:
        where += " AND action = :action"
        params["action"] = action
    if user_id:
        where += " AND user_id = :uid"
        params["uid"] = user_id

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    sql = f"""
        SELECT user_id, action, resource_id, query_text, ip_address, created_at
        FROM audit_logs {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = (await db.execute(text(sql), params)).fetchall()

    return {
        "page": page,
        "size": size,
        "items": [
            {
                "user_id":     str(r.user_id) if r.user_id else None,
                "action":      r.action,
                "resource_id": r.resource_id,
                "query":       r.query_text,
                "ip":          str(r.ip_address) if r.ip_address else None,
                "timestamp":   str(r.created_at),
            }
            for r in rows
        ],
    }
