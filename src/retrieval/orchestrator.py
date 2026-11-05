"""在线检索编排入口：preprocess → hybrid_search → rerank → expand → generate。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..utils.logging import setup_logging
from .expander import expand_to_parents
from .generator import AssembledContext, assemble_context, stream_answer
from .preprocessor import preprocess_query
from .reranker import rerank
from .searcher import RetrievedChunk, hybrid_search

logger = setup_logging("clinatlas.retrieval")


@dataclass
class RetrievalResult:
    """一次完整检索的返回，包含来源信息和 LLM 回答流。"""
    context: AssembledContext
    answer_stream: object   # AsyncIterator[str]


async def retrieve_and_answer(
    query: str,
    tenant_id: str,
    department_filter: list[str] | None = None,
    source_types: list[str] | None = None,
    top_k: int = 50,
    rerank_top_k: int = 10,
    llm_base_url: str | None = None,
    model: str = "RunYi-3.6-27B",  # 使用润一医疗大模型（推理增强版）
) -> RetrievalResult:
    """
    完整在线检索链路：预处理 → 混合检索 → Rerank → 父子块扩展 → Context 组装。

    返回 AssembledContext（含来源列表）和 LLM 回答的异步流。
    调用方负责消费 answer_stream，通常通过 SSE 推送给前端。
    """
    # Step 1：Query 预处理
    processed = preprocess_query(query)

    # Step 2：混合检索（向量 + BM25 + RRF）
    fused = await hybrid_search(
        processed, tenant_id, department_filter, source_types, top_k
    )

    # Step 3：Rerank 精排
    reranked = rerank(processed.normalized, fused, top_k=rerank_top_k)

    # Step 4：父子块扩展，把子块替换为父块
    parents = expand_to_parents(reranked)

    # Step 5：组装 Context
    context = assemble_context(parents, processed.original)

    # Step 6：启动 LLM 流式生成（返回流对象，不在此消费）
    answer_stream = stream_answer(context, llm_base_url=llm_base_url, model=model)

    logger.info(
        "检索链路完成",
        extra={
            "fused": len(fused),
            "reranked": len(reranked),
            "parents": len(parents),
            "sources": len(context.sources),
        },
    )
    return RetrievalResult(context=context, answer_stream=answer_stream)
