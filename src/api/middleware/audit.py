"""审计日志中间件：记录每次 API 调用到 PostgreSQL audit_logs 表。"""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.api.audit")

# 不记录审计日志的路径前缀
_SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuditMiddleware(BaseHTTPMiddleware):
    """
    记录每次请求的用户、操作、资源和耗时。

    从 JWT payload 中提取 user_id 和 tenant_id（鉴权失败的请求也记录，
    但 user_id 为 anonymous）。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # 跳过健康检查等噪声路径
        if any(request.url.path.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - start) * 1000)

        # 从请求 state 取鉴权后注入的用户信息（鉴权中间件先于此运行）
        user_id   = getattr(request.state, "user_id",   "anonymous")
        tenant_id = getattr(request.state, "tenant_id", "unknown")

        logger.info(
            "API 请求",
            extra={
                "user_id":    user_id,
                "tenant_id":  tenant_id,
                "method":     request.method,
                "path":       request.url.path,
                "status":     response.status_code,
                "latency_ms": latency_ms,
                "ip":         request.client.host if request.client else "unknown",
            },
        )
        return response
