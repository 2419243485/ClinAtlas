"""Reranker 精排器：用 bge-reranker-v2-m3 对候选结果精排。

Rerank 模型比向量检索更准确，但推理成本高，因此只对融合后的 top-20 精排到 top-10。
"""

from __future__ import annotations

from functools import lru_cache

from ..utils.logging import setup_logging
from ..utils.settings import get_settings
from .searcher import RetrievedChunk

logger = setup_logging("clinatlas.retrieval.reranker")


@lru_cache(maxsize=1)
def _load_reranker():
    """加载 bge-reranker-v2-m3 模型，进程内单例复用。"""
    from FlagEmbedding import FlagReranker

    settings = get_settings()
    try:
        model = FlagReranker(
            settings.reranker.model_path,
            use_fp16=True if settings.reranker.device == "cuda" else False,
            device=settings.reranker.device,
        )
    except Exception:
        logger.info(
            "本地 Reranker 模型不存在，改用在线下载",
            extra={"model": settings.reranker.model_name},
        )
        model = FlagReranker(
            settings.reranker.model_name,
            use_fp16=True if settings.reranker.device == "cuda" else False,
            device=settings.reranker.device,
        )
    logger.info(
        "Reranker 模型加载完成",
        extra={"model": settings.reranker.model_name, "device": settings.reranker.device},
    )
    return model


def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    top_k: int = 10,
    score_threshold: float = 0.3,
) -> list[RetrievedChunk]:
    """
    对候选结果精排，返回 top_k 个分数最高且超过阈值的块。

    输入 candidates 通常是 RRF 融合后的 top-20，
    输出是最相关的 top-10，过滤掉低相关性的噪声。
    """
    if not candidates:
        return []

    model = _load_reranker()

    # 构造 (query, passage) 对
    pairs = [[query, chunk.text] for chunk in candidates]

    # 返回相关性分数，范围约 [-10, 10]，正数表示相关
    scores = model.compute_score(pairs, normalize=True)

    # 单个 query 时 compute_score 返回标量，多个时返回列表
    if not isinstance(scores, list):
        scores = [scores]

    ranked = sorted(
        zip(candidates, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    result = []
    for chunk, score in ranked[:top_k]:
        if score >= score_threshold:
            chunk.relevance_score = round(float(score), 4)
            result.append(chunk)

    logger.info(
        "Rerank 完成",
        extra={
            "input": len(candidates),
            "output": len(result),
            "threshold": score_threshold,
        },
    )
    return result
