"""Qdrant 索引写入器：把带 embedding 的父子块批量写入向量库。

Collection 初始化时自动检测是否存在，不存在则创建，
保证首次部署和重建索引都能正常运行。
"""

from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from ..models.pipeline import Chunk
from ..utils.logging import setup_logging
from ..utils.settings import get_settings

logger = setup_logging("clinatlas.indexer")

# 每批写入点数，避免单次请求过大
_UPSERT_BATCH_SIZE = 128


@lru_cache(maxsize=1)
def _get_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant.url)


def _ensure_collections() -> None:
    """检查 Collection 是否存在，不存在则创建。"""
    settings = get_settings()
    client = _get_client()
    existing = {c.name for c in client.get_collections().collections}

    for name in (settings.qdrant.collection_child, settings.qdrant.collection_parent):
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.qdrant.vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("创建 Qdrant Collection", extra={"collection": name})


def _chunk_to_point(chunk: Chunk) -> PointStruct:
    """把 Chunk 转换为 Qdrant PointStruct。"""
    payload = {
        "doc_id":       chunk.doc_id,
        "tenant_id":    chunk.tenant_id,
        "parent_id":    chunk.parent_id,
        "chunk_index":  chunk.chunk_index,
        "is_parent":    chunk.is_parent,
        "block_type":   chunk.block_type.value,
        "text":         chunk.text,
        **chunk.metadata,
    }
    if chunk.page_number is not None:
        payload["page_number"] = chunk.page_number

    return PointStruct(
        id=chunk.chunk_id,
        vector=chunk.embedding,
        payload=payload,
    )


def _upsert_batch(collection: str, points: list[PointStruct]) -> None:
    client = _get_client()
    for i in range(0, len(points), _UPSERT_BATCH_SIZE):
        batch = points[i : i + _UPSERT_BATCH_SIZE]
        client.upsert(collection_name=collection, points=batch, wait=True)


def index_chunks(
    parent_chunks: list[Chunk],
    child_chunks: list[Chunk],
    doc_id: str,
) -> None:
    """
    把父块和子块批量写入对应 Collection。

    调用前 chunks 必须已完成向量化（含 embedding 字段）。
    父块和子块写入不同 Collection，便于父子块扩展时批量拉取父块。
    """
    settings = get_settings()
    _ensure_collections()

    parent_points = [_chunk_to_point(c) for c in parent_chunks if c.embedding]
    child_points  = [_chunk_to_point(c) for c in child_chunks if c.embedding]

    if parent_points:
        _upsert_batch(settings.qdrant.collection_parent, parent_points)
        logger.info(
            "父块写入完成",
            extra={"doc_id": doc_id, "count": len(parent_points)},
        )

    if child_points:
        _upsert_batch(settings.qdrant.collection_child, child_points)
        logger.info(
            "子块写入完成",
            extra={"doc_id": doc_id, "count": len(child_points)},
        )


def delete_doc_chunks(doc_id: str) -> None:
    """删除指定文档的所有 chunk（归档文档时调用）。"""
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    settings = get_settings()
    client = _get_client()
    doc_filter = Filter(
        must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
    )
    for name in (settings.qdrant.collection_child, settings.qdrant.collection_parent):
        client.delete(collection_name=name, points_selector=doc_filter)

    logger.info("文档向量索引已删除", extra={"doc_id": doc_id})
