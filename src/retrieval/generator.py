"""Context 组装与 LLM 生成器：把父块拼成 prompt，流式输出 LLM 回答。

LLM 接入层设计为可替换：优先用本地 vLLM/Ollama，也支持兼容 OpenAI 协议的私有 API。
生成时通过 SSE（Server-Sent Events）流式返回，前端边生成边展示。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

import httpx

from ..utils.logging import setup_logging
from ..utils.settings import get_settings
from .searcher import RetrievedChunk

logger = setup_logging("clinatlas.retrieval.generator")

# 每个 context 片段传给 LLM 的最大 token 数（约留 20% 给 LLM 回答）
_MAX_CONTEXT_TOKENS = 6000

# 医学知识助手系统提示
_SYSTEM_PROMPT = """你是一位医学知识助手，仅基于医院内部知识库回答问题。

规则：
1. 只使用下方参考资料中的内容作答，不引用训练数据中的知识
2. 每条结论后标注来源编号，格式：[来源N]
3. 如果参考资料中没有足够信息，回复："当前知识库中未找到与该问题相关的内容，建议咨询主治医生。"
4. 不作出诊断结论，只提供知识参考
5. 回答使用与用户提问相同的语言
6. 直接输出最终答案，不要输出思考过程、分析步骤、内部推理或任何形式的 thinking process
7. 禁止输出任何英文的思考过程描述（如 "Here's a thinking process"、"Let me analyze" 等）
8. 立即给出答案，不要前置任何分析说明"""


@dataclass
class ContextSource:
    index: int
    text: str
    filename: str
    department: str
    version: str
    page: int | None
    relevance_score: float


@dataclass
class AssembledContext:
    sources: list[ContextSource]
    total_tokens: int
    prompt: str


def _count_tokens(text: str) -> int:
    """近似 token 计数，与 chunker 保持相同估算方式。"""
    chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
    other_chars = len(text) - chinese_chars
    return chinese_chars + other_chars // 4


def assemble_context(
    parent_chunks: list[RetrievedChunk],
    query: str,
) -> AssembledContext:
    """
    把父块列表组装成供 LLM 使用的 prompt。

    按相关度从高到低填充，总 token 数不超过 _MAX_CONTEXT_TOKENS。
    每个片段附带来源元数据，供 LLM 生成引用标注。
    """
    sources: list[ContextSource] = []
    total_tokens = 0

    for i, chunk in enumerate(parent_chunks):
        chunk_tokens = _count_tokens(chunk.text)
        if total_tokens + chunk_tokens > _MAX_CONTEXT_TOKENS:
            break

        sources.append(ContextSource(
            index=i + 1,
            text=chunk.text,
            filename=chunk.metadata.get("filename", "未知文档"),
            department=chunk.metadata.get("department", ""),
            version=chunk.metadata.get("version", ""),
            page=chunk.page_number,
            relevance_score=chunk.relevance_score,
        ))
        total_tokens += chunk_tokens

    # 组装参考资料文本块
    ref_parts: list[str] = []
    for src in sources:
        page_info = f" 第{src.page}页" if src.page else ""
        ref_parts.append(
            f"[来源{src.index}] {src.filename}{page_info}\n{src.text}"
        )
    references = "\n\n---\n\n".join(ref_parts)

    prompt = f"参考资料：\n\n{references}\n\n用户问题：{query}"

    logger.info(
        "Context 组装完成",
        extra={
            "sources": len(sources),
            "total_tokens": total_tokens,
            "query_len": len(query),
        },
    )
    return AssembledContext(sources=sources, total_tokens=total_tokens, prompt=prompt)


async def stream_answer(
    context: AssembledContext,
    llm_base_url: str | None = None,
    model: str = "RunYi-3.6-27B",  # 使用润一医疗大模型（推理增强版）
    temperature: float = 0.1,     # 医学场景偏保守，低温度减少幻觉
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """
    调用兼容 OpenAI Chat Completions 协议的 LLM，流式返回回答。

    支持 vLLM、Ollama（/v1 兼容路由）、以及任何 OpenAI 兼容私有 API。
    使用方：async for token in stream_answer(context): ...
    """
    settings = get_settings()
    base_url = llm_base_url or settings.llm.base_url
    api_key = settings.llm.api_key
    if not base_url:
        raise RuntimeError("未配置 LLM 接口地址，请在项目根目录 .env 中设置 LLM_BASE_URL")

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": context.prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    import os
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    target_url = f"{base_url}/chat/completions"
    logger.info(f"准备调用 LLM API: {target_url}, model={payload['model']}")
    logger.info(f"Prompt: {payload['messages'][0]['content'][:500]}")  # 调试：输出 prompt 开头部分

    async with httpx.AsyncClient(timeout=120.0, proxy=proxy) as client:
        async with client.stream(
            "POST",
            target_url,
            json=payload,
            headers=headers,
        ) as response:
            status = response.status_code
            logger.info(f"LLM API 响应状态: {status}")

            if status != 200:
                body = await response.aread()
                logger.error(f"LLM API 错误响应: {body.decode()[:500]}")
                response.raise_for_status()

            # 状态码正常，开始流式读取
            line_count = 0

            async for line in response.aiter_lines():
                line_count += 1
                if line_count <= 3:
                    logger.info(f"LLM 响应行 {line_count}: {line[:200]}")

                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    logger.info(f"LLM 流式响应完成，共 {line_count} 行")
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    # 推理模型的思考过程放在 reasoning_content 字段，只输出最终回答 content
                    content = delta.get("content")
                    if content:
                        yield content

                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.warning(f"解析 LLM 响应失败: {e}, data: {data[:200]}")
                    continue
