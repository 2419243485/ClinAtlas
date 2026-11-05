"""检索路由：标准检索、问答（SSE 流式）、检索历史、反馈。"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.auth import UserInfo, get_current_user
from ..schemas import FeedbackRequest, SearchRequest, SearchResponse, SourceInfo
from ...retrieval import retrieve_and_answer
from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.api.search")
router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """
    标准检索接口：返回段落列表和来源，不生成 LLM 回答。

    适用场景：用户只需要检索结果而非问答，或前端自己组装展示。
    """
    start = time.monotonic()
    query_id = str(uuid.uuid4())

    # 非管理员只能检索本科室文档
    department_filter = req.department_filter
    if user.role != "admin":
        department_filter = [user.department] if user.department else None

    result = await retrieve_and_answer(
        query=req.query,
        tenant_id=user.tenant_id,
        department_filter=department_filter,
        source_types=req.source_types,
        top_k=50,
        rerank_top_k=req.top_k,
    )

    latency_ms = int((time.monotonic() - start) * 1000)

    sources = [
        SourceInfo(
            index=src.index,
            filename=src.filename,
            department=src.department,
            version=src.version,
            page=src.page,
            relevance=src.relevance_score,
        )
        for src in result.context.sources
    ]

    # 记录检索历史（异步写，不阻塞响应）
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO audit_logs (tenant_id, user_id, action, query_text, created_at) "
        "VALUES (:tenant_id, :user_id, 'search', :query, NOW())"
    ), {"tenant_id": user.tenant_id, "user_id": user.user_id, "query": req.query})
    await db.commit()

    logger.info(
        "检索完成",
        extra={
            "query_id": query_id,
            "user_id": user.user_id,
            "sources": len(sources),
            "latency_ms": latency_ms,
        },
    )
    return SearchResponse(
        query_id=query_id,
        query=req.query,
        sources=sources,
        latency_ms=latency_ms,
    )


@router.post("/qa")
async def question_answer(
    req: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """
    问答接口：SSE 流式返回 LLM 生成的回答。

    响应格式（sources 和 answer 的 data 为 JSON，避免 token 中的换行破坏 SSE 帧）：
    - event: sources → 来源信息列表
    - event: answer  → 回答 token 字符串
    - event: done    → 生成结束标记
    """
    department_filter = req.department_filter
    if user.role != "admin":
        department_filter = [user.department] if user.department else None

    result = await retrieve_and_answer(
        query=req.query,
        tenant_id=user.tenant_id,
        department_filter=department_filter,
        source_types=req.source_types,
        top_k=50,
        rerank_top_k=req.top_k,
    )

    async def _stream():
        import json

        # 先推送来源信息
        sources = [
            {
                "index":      src.index,
                "filename":   src.filename,
                "department": src.department,
                "version":    src.version,
                "page":       src.page,
                "relevance":  src.relevance_score,
                "text":       src.text,
            }
            for src in result.context.sources
        ]
        yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"

        # 流式推送 LLM 回答
        async for token in result.answer_stream:
            yield f"event: answer\ndata: {json.dumps(token, ensure_ascii=False)}\n\n"

        # 结束标记
        yield "event: done\ndata: [DONE]\n\n"

    # 记录检索历史
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO audit_logs (tenant_id, user_id, action, query_text, created_at) "
        "VALUES (:tenant_id, :user_id, 'qa', :query, NOW())"
    ), {"tenant_id": user.tenant_id, "user_id": user.user_id, "query": req.query})
    await db.commit()

    logger.info("问答流式生成启动", extra={"user_id": user.user_id, "query": req.query})
    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/history")
async def search_history(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """查询当前用户的检索历史。"""
    from sqlalchemy import text

    offset = (page - 1) * size
    sql = """
        SELECT query_text, action, created_at
        FROM audit_logs
        WHERE tenant_id = :tenant_id AND user_id = :user_id
          AND action IN ('search', 'qa')
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = (await db.execute(text(sql), {
        "tenant_id": user.tenant_id,
        "user_id":   user.user_id,
        "limit":     size,
        "offset":    offset,
    })).fetchall()

    items = [
        {"query": r.query_text, "action": r.action, "timestamp": str(r.created_at)}
        for r in rows
    ]
    return {"page": page, "size": size, "items": items}


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """提交检索反馈，用于后续优化检索效果。"""
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO search_feedback (tenant_id, user_id, query_text, rating, comment, created_at) "
        "VALUES (:tenant_id, :user_id, :query_id, :rating, :comment, NOW())"
    ), {
        "tenant_id": user.tenant_id,
        "user_id":   user.user_id,
        "query_id":  req.query_id,
        "rating":    req.rating,
        "comment":   req.comment,
    })
    await db.commit()
    logger.info("反馈已记录", extra={"query_id": req.query_id, "rating": req.rating})
