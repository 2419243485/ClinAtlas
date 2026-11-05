"""父子块扩展器：命中子块后向上查找父块，把完整上下文传给 LLM。

检索时用小子块（256 tokens）保证精准度，
传给 LLM 时换成对应父块（1024 tokens）保证上下文完整性。
"""

from __future__ import annotations

from qdrant_client import QdrantClient

from ..utils.logging import setup_logging
from ..utils.settings import get_settings
from .searcher import RetrievedChunk

logger = setup_logging("clinatlas.retrieval.expander")


def _get_sync_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant.url)


def expand_to_parents(
    child_chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """
    把子块列表替换为对应的父块。

    处理步骤：
    1. 收集所有命中子块的 parent_id（去重）
    2. 批量从父块 Collection 拉取完整文本
    3. 继承子块的 relevance_score，按分数排序返回

    无 parent_id 的子块（原子块，表格/列表）直接当父块使用。
    """
    if not child_chunks:
        return []

    settings = get_settings()
    client = _get_sync_client()

    # 分两类：有父块和无父块（原子块）
    has_parent: list[RetrievedChunk] = []
    atomic: list[RetrievedChunk] = []
    for chunk in child_chunks:
        if chunk.parent_id:
            has_parent.append(chunk)
        else:
            atomic.append(chunk)

    # 收集唯一 parent_id，保留最高子块分数
    parent_id_to_score: dict[str, float] = {}
    for chunk in has_parent:
        pid = chunk.parent_id
        current = parent_id_to_score.get(pid, -1.0)
        if chunk.relevance_score > current:
            parent_id_to_score[pid] = chunk.relevance_score

    result: list[RetrievedChunk] = list(atomic)

    if parent_id_to_score:
        # 批量拉取父块
        parent_records = client.retrieve(
            collection_name=settings.qdrant.collection_parent,
            ids=list(parent_id_to_score.keys()),
            with_payload=True,
            with_vectors=False,
        )

        for rec in parent_records:
            payload = rec.payload or {}
            pid = str(rec.id)
            result.append(RetrievedChunk(
                chunk_id=pid,
                doc_id=payload.get("doc_id", ""),
                tenant_id=payload.get("tenant_id", ""),
                parent_id=None,
                text=payload.get("text", ""),
                page_number=payload.get("page_number"),
                block_type=payload.get("block_type", "paragraph"),
                relevance_score=parent_id_to_score.get(pid, 0.5),
                metadata={k: v for k, v in payload.items()
                          if k not in ("doc_id", "tenant_id", "text",
                                       "page_number", "block_type")},
            ))

    # 去重（同一父块只保留一次），按分数降序
    seen: set[str] = set()
    deduped: list[RetrievedChunk] = []
    for chunk in sorted(result, key=lambda c: c.relevance_score, reverse=True):
        if chunk.chunk_id not in seen:
            deduped.append(chunk)
            seen.add(chunk.chunk_id)

    logger.info(
        "父子块扩展完成",
        extra={"child_input": len(child_chunks), "parent_output": len(deduped)},
    )
    return deduped
