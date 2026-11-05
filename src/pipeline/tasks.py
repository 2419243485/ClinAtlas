"""Celery 任务定义：把离线流水线各步骤串成可异步执行的任务链。

任务状态通过 PostgreSQL documents 表的 status 字段同步，
失败时写入 error_message，支持手动触发重试。
"""

from __future__ import annotations

import shutil
import traceback
import uuid
from pathlib import Path

from celery import Celery
from sqlalchemy import create_engine, text

from .chunker import chunk_document
from .embedder import embed_chunks
from .indexer import delete_doc_chunks, index_chunks
from .parsers import parse_document
from ..utils.logging import setup_logging
from ..utils.settings import get_settings

logger = setup_logging("clinatlas.tasks")
settings = get_settings()

app = Celery(
    "clinatlas",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
)
app.conf.update(
    task_serializer=settings.celery.task_serializer,
    result_serializer="json",
    accept_content=["json"],
    worker_concurrency=settings.celery.worker_concurrency,
    task_acks_late=True,           # 任务完成后再 ack，防止 worker 崩溃时丢任务
    task_reject_on_worker_lost=True,
)

# 同步 SQLAlchemy engine，仅用于任务内状态更新（不走异步框架）
_engine = create_engine(
    settings.database.url.replace("+asyncpg", ""),  # 任务内用同步驱动
    pool_pre_ping=True,
)


def _update_status(doc_id: str, status: str, error: str | None = None) -> bool:
    """更新文档状态，返回是否命中记录（记录已被新版本替换删除时为 False）。"""
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE documents SET status = :status, "
                "error_message = :error, "
                "indexed_at = CASE WHEN :status = 'ready' THEN NOW() ELSE indexed_at END "
                "WHERE id = :doc_id"
            ),
            {"status": status, "error": error, "doc_id": doc_id},
        )
        return result.rowcount > 0


def _purge_superseded(doc_id: str) -> None:
    """物理删除与当前文档内容完全相同（同租户、同科室、同 checksum）且更早上传的旧版本。

    删除范围：Qdrant 向量、documents / document_versions 记录、本地文件目录。
    在新文档索引完成后调用，替换期间旧版本仍可检索。
    """
    with _engine.connect() as conn:
        olds = conn.execute(
            text(
                "SELECT o.id, o.file_path FROM documents o "
                "JOIN documents cur ON cur.id = :doc_id "
                "WHERE cur.checksum <> '' "
                "AND o.tenant_id = cur.tenant_id "
                "AND o.checksum = cur.checksum "
                "AND o.department IS NOT DISTINCT FROM cur.department "
                "AND o.id <> cur.id AND o.uploaded_at < cur.uploaded_at"
            ),
            {"doc_id": doc_id},
        ).fetchall()

    for old in olds:
        old_id = str(old.id)
        # 先删向量再删记录：中途失败时记录仍在，下次上传同一文件会再次清理
        delete_doc_chunks(old_id)
        with _engine.begin() as conn:
            conn.execute(text("DELETE FROM document_versions WHERE document_id = :id"), {"id": old_id})
            conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": old_id})

        # 只删除该文档自己的目录 uploads/<tenant_id>/<doc_id>/，路径不符合约定时保留文件
        doc_dir = Path(old.file_path).parent
        if doc_dir.name == old_id:
            shutil.rmtree(doc_dir, ignore_errors=True)
        else:
            logger.warning(
                "旧版本文件路径不符合约定，未删除本地文件",
                extra={"doc_id": old_id, "file_path": old.file_path},
            )
        logger.info("已删除内容相同的旧版本", extra={"doc_id": doc_id, "old_doc_id": old_id})


@app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,   # 失败后 30 秒重试
    name="clinatlas.pipeline.process_document",
)
def process_document(
    self,
    doc_id: str,
    file_path: str,
    tenant_id: str,
    metadata: dict | None = None,
) -> dict:
    """
    文档处理主任务：解析 → 分块 → 向量化 → 写入索引。

    参数：
        doc_id:     数据库中的文档 UUID
        file_path:  本地临时文件路径（已从 MinIO 下载）
        tenant_id:  所属租户 ID
        metadata:   额外元数据（科室、文档类型等）
    """
    if not _update_status(doc_id, "processing"):
        logger.info("文档记录不存在（已被内容相同的新版本替换），跳过处理", extra={"doc_id": doc_id})
        return {"doc_id": doc_id, "status": "deleted"}
    logger.info("任务开始", extra={"doc_id": doc_id, "stage": "start"})

    try:
        path = Path(file_path)

        # Step 1：解析文档
        logger.info("文档解析中", extra={"doc_id": doc_id, "stage": "parse"})
        parsed = parse_document(path, doc_id)

        # 补充外部传入的元数据（科室、版本等）
        if metadata:
            parsed.raw_metadata.update(metadata)

        # Step 2：结构感知分块
        logger.info("分块中", extra={"doc_id": doc_id, "stage": "chunk"})
        parent_chunks, child_chunks = chunk_document(parsed, tenant_id)

        if not child_chunks:
            raise ValueError("文档分块后子块数量为 0，文档可能为空或格式异常")

        # Step 3：父块向量化
        logger.info("父块向量化中", extra={"doc_id": doc_id, "stage": "embed_parent"})
        parent_chunks = embed_chunks(parent_chunks)

        # Step 4：子块向量化
        logger.info("子块向量化中", extra={"doc_id": doc_id, "stage": "embed_child"})
        child_chunks = embed_chunks(child_chunks)

        # Step 5：写入 Qdrant
        logger.info("写入向量库中", extra={"doc_id": doc_id, "stage": "index"})
        index_chunks(parent_chunks, child_chunks, doc_id)

        if not _update_status(doc_id, "ready"):
            # 处理期间已被内容相同的新版本替换删除，清掉刚写入的向量
            delete_doc_chunks(doc_id)
            logger.info("文档已被新版本替换，清理本次写入的向量", extra={"doc_id": doc_id})
            return {"doc_id": doc_id, "status": "deleted"}

        # 删除内容相同的旧版本；失败不影响新文档可用，也不触发整个任务重试
        try:
            _purge_superseded(doc_id)
        except Exception as purge_exc:
            logger.error(
                "删除旧版本失败",
                extra={"doc_id": doc_id, "error": str(purge_exc)},
            )

        logger.info(
            "任务完成",
            extra={
                "doc_id": doc_id,
                "stage": "done",
                "parents": len(parent_chunks),
                "children": len(child_chunks),
            },
        )
        return {
            "doc_id": doc_id,
            "status": "ready",
            "parent_count": len(parent_chunks),
            "child_count": len(child_chunks),
        }

    except Exception as exc:
        err_msg = traceback.format_exc()
        logger.error(
            "任务失败",
            extra={"doc_id": doc_id, "stage": "error", "error": str(exc)},
        )
        # 未超过最大重试次数时自动重试
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _update_status(doc_id, "failed", error=err_msg[:2000])
            raise


@app.task(name="clinatlas.pipeline.reindex_document")
def reindex_document(doc_id: str, file_path: str, tenant_id: str) -> dict:
    """重建索引：先删除旧索引，再重新处理。管理员手动触发。"""
    logger.info("重建索引", extra={"doc_id": doc_id})
    delete_doc_chunks(doc_id)

    # 从数据库读取文档元数据，避免重建后向量缺少科室、版本等字段
    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT filename, department, source_type, version FROM documents WHERE id = :id"),
            {"id": doc_id},
        ).fetchone()
    metadata = None
    if row:
        metadata = {
            "department":  row.department or "",
            "source_type": row.source_type or "",
            "version":     row.version or "",
            "filename":    row.filename,
        }

    # 直接调用处理函数，而不是通过 Celery 任务
    return process_document(doc_id, file_path, tenant_id, metadata=metadata)
