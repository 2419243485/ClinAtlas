"""向量化器：用 bge-m3 对子块和父块批量生成 embedding。

模型优先从本地路径加载，支持离线环境；首次加载后进程内复用，
避免每个任务重复加载模型（bge-m3 约 567M 参数，冷启动约 3 秒）。
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from ..models.pipeline import Chunk
from ..utils.logging import setup_logging
from ..utils.settings import get_settings

logger = setup_logging("clinatlas.embedder")


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """加载 bge-m3 模型，进程内只加载一次。"""
    settings = get_settings()
    model_path = settings.embedding.model_path
    # 优先用本地路径，不存在则按 model_name 从 HuggingFace 下载
    try:
        model = SentenceTransformer(
            model_path,
            device=settings.embedding.device,
        )
    except Exception:
        logger.info("本地模型路径不存在，改用在线下载", extra={"model": settings.embedding.model_name})
        model = SentenceTransformer(
            settings.embedding.model_name,
            device=settings.embedding.device,
        )
    logger.info(
        "Embedding 模型加载完成",
        extra={"model": settings.embedding.model_name, "device": settings.embedding.device},
    )
    return model


def embed_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """
    对 chunk 列表批量向量化，返回带 embedding 字段的副本。

    输入 chunks 的 text 字段不能为空。返回顺序与输入一致。
    """
    if not chunks:
        return []

    settings = get_settings()
    model = _load_model()

    texts = [c.text for c in chunks]
    logger.info(
        "开始批量向量化",
        extra={"chunk_count": len(texts), "batch_size": settings.embedding.batch_size},
    )

    embeddings = model.encode(
        texts,
        batch_size=settings.embedding.batch_size,
        normalize_embeddings=settings.embedding.normalize,
        show_progress_bar=False,
        convert_to_numpy=True,
    )

    # 把向量附加到 chunk 上（新建对象，不污染输入）
    result: list[Chunk] = []
    for chunk, emb in zip(chunks, embeddings):
        result.append(chunk.model_copy(update={"embedding": emb.tolist()}))
    return result
