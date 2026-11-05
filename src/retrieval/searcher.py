"""混合检索器：向量检索 + BM25 关键词检索，RRF 融合排序。

向量检索和 BM25 并行执行，利用两者互补性：
- 向量检索：语义相似，应对术语变体和多语言
- BM25：精确匹配医学术语、药品名、ICD 编码
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue

from ..pipeline.embedder import embed_chunks
from ..models.pipeline import Chunk, BlockType
from ..utils.logging import setup_logging
from ..utils.settings import get_settings
from .preprocessor import ProcessedQuery

logger = setup_logging("clinatlas.retrieval.searcher")


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    tenant_id: str
    parent_id: str | None
    text: str
    page_number: int | None
    block_type: str
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


def _build_filter(
    tenant_id: str,
    department_filter: list[str] | None = None,
    source_types: list[str] | None = None,
) -> Filter:
    """构建 Qdrant payload 过滤条件，租户隔离是必选条件。"""
    must = [FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]

    if department_filter:
        must.append(FieldCondition(
            key="department",
            match=MatchAny(any=department_filter),
        ))
    if source_types:
        must.append(FieldCondition(
            key="source_type",
            match=MatchAny(any=source_types),
        ))

    return Filter(must=must)


def _embed_query(query_text: str) -> list[float]:
    """把单条 query 文本转为向量（复用 embedder 的模型实例）。"""
    # 构造一个临时 Chunk 占位，利用 embed_chunks 的批量接口
    dummy = Chunk(
        chunk_id="__query__",
        doc_id="__query__",
        tenant_id="__query__",
        text=query_text,
        chunk_index=0,
        block_type=BlockType.PARAGRAPH,
    )
    result = embed_chunks([dummy])
    return result[0].embedding


async def _vector_search(
    client: AsyncQdrantClient,
    query_vectors: list[list[float]],
    payload_filter: Filter,
    top_k: int,
    collection: str,
) -> list[RetrievedChunk]:
    """对多个 query 向量分别检索，取结果并集（去重保留最高分）。"""
    best: dict[str, RetrievedChunk] = {}

    tasks = [
        client.search(
            collection_name=collection,
            query_vector=vec,
            query_filter=payload_filter,
            limit=top_k,
            with_payload=True,
        )
        for vec in query_vectors
    ]
    results = await asyncio.gather(*tasks)

    for hits in results:
        for hit in hits:
            payload = hit.payload or {}
            cid = hit.id
            if cid not in best or hit.score > best[cid].relevance_score:
                best[cid] = RetrievedChunk(
                    chunk_id=str(cid),
                    doc_id=payload.get("doc_id", ""),
                    tenant_id=payload.get("tenant_id", ""),
                    parent_id=payload.get("parent_id"),
                    text=payload.get("text", ""),
                    page_number=payload.get("page_number"),
                    block_type=payload.get("block_type", "paragraph"),
                    relevance_score=hit.score,
                    metadata={k: v for k, v in payload.items()
                              if k not in ("doc_id", "tenant_id", "parent_id",
                                           "text", "page_number", "block_type")},
                )

    return sorted(best.values(), key=lambda c: c.relevance_score, reverse=True)


def _bm25_search(
    query: ProcessedQuery,
    payload_filter: Filter,
    top_k: int,
) -> list[RetrievedChunk]:
    """
    BM25 关键词检索。

    Qdrant 原生支持 full-text payload 过滤，利用 text 字段做关键词匹配。
    多个关键词取并集，按命中词数近似排序。
    """
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        FieldCondition, Filter, MatchText, ScrollRequest
    )

    settings = get_settings()
    sync_client = QdrantClient(url=settings.qdrant.url)

    # 把 normalized query 和 expanded_terms 合并为关键词集合
    keywords = [query.normalized] + query.expanded_terms

    seen: dict[str, RetrievedChunk] = {}
    for kw in keywords[:6]:   # 最多用 6 个关键词，避免查询膨胀
        kw_filter = Filter(
            must=payload_filter.must + [
                FieldCondition(key="text", match=MatchText(text=kw))
            ]
        )
        records, _ = sync_client.scroll(
            collection_name=settings.qdrant.collection_child,
            scroll_filter=kw_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        for rec in records:
            payload = rec.payload or {}
            cid = str(rec.id)
            if cid not in seen:
                # BM25 无精确分数，用 0.5 作为初始基准分
                seen[cid] = RetrievedChunk(
                    chunk_id=cid,
                    doc_id=payload.get("doc_id", ""),
                    tenant_id=payload.get("tenant_id", ""),
                    parent_id=payload.get("parent_id"),
                    text=payload.get("text", ""),
                    page_number=payload.get("page_number"),
                    block_type=payload.get("block_type", "paragraph"),
                    relevance_score=0.5,
                    metadata={},
                )
            else:
                # 被多个关键词命中，提升分数
                seen[cid].relevance_score += 0.1

    return sorted(seen.values(), key=lambda c: c.relevance_score, reverse=True)[:top_k]


def _rrf_fusion(
    vector_hits: list[RetrievedChunk],
    bm25_hits: list[RetrievedChunk],
    top_k: int = 20,
    k: int = 60,
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> list[RetrievedChunk]:
    """
    Reciprocal Rank Fusion 融合两路检索结果。

    RRF 公式：score(d) = Σ weight / (k + rank(d))
    k=60 是经验常数，平滑低排名文档的影响。
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for rank, chunk in enumerate(vector_hits):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + \
            vector_weight / (k + rank + 1)
        chunk_map[chunk.chunk_id] = chunk

    for rank, chunk in enumerate(bm25_hits):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + \
            bm25_weight / (k + rank + 1)
        if chunk.chunk_id not in chunk_map:
            chunk_map[chunk.chunk_id] = chunk

    sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]

    result = []
    for cid in sorted_ids:
        chunk = chunk_map[cid]
        chunk.relevance_score = round(scores[cid], 6)
        result.append(chunk)
    return result


async def hybrid_search(
    query: ProcessedQuery,
    tenant_id: str,
    department_filter: list[str] | None = None,
    source_types: list[str] | None = None,
    top_k: int = 50,
) -> list[RetrievedChunk]:
    """
    混合检索主入口，返回 RRF 融合后的 top_k 个子块。

    向量检索异步并行执行多个 query 变体；BM25 同步执行后合并。
    """
    settings = get_settings()
    payload_filter = _build_filter(tenant_id, department_filter, source_types)

    # 对所有 multi-query 变体批量向量化
    all_query_texts = query.multi_queries
    query_vectors = [_embed_query(q) for q in all_query_texts]

    async_client = AsyncQdrantClient(url=settings.qdrant.url)

    # 向量检索和 BM25 并行（BM25 用 asyncio.to_thread 避免阻塞事件循环）
    vector_hits, bm25_hits = await asyncio.gather(
        _vector_search(
            async_client, query_vectors, payload_filter, top_k,
            settings.qdrant.collection_child,
        ),
        asyncio.to_thread(
            _bm25_search, query, payload_filter, top_k
        ),
    )

    fused = _rrf_fusion(vector_hits, bm25_hits, top_k=20)

    logger.info(
        "混合检索完成",
        extra={
            "vector_hits": len(vector_hits),
            "bm25_hits": len(bm25_hits),
            "fused": len(fused),
        },
    )
    return fused
