"""结构感知分块器：按文档层级切分，同时生成父块和子块两级索引。

核心思路：
1. 以标题层级为边界把 blocks 分组，形成语义段落
2. 每个语义段落先切成父块（1024 tokens）
3. 每个父块再切成子块（256 tokens），子块之间保留 overlap
4. 表格和列表作为不可拆分单元，整块保留
"""

from __future__ import annotations

import uuid
from itertools import islice
from typing import Iterator

from ..models.pipeline import BlockType, Chunk, DocumentBlock, ParsedDocument
from ..utils.logging import setup_logging
from ..utils.settings import get_settings

logger = setup_logging("clinatlas.chunker")


def _token_count(text: str) -> int:
    """近似 token 计数：中文按字符数，英文按 4 字符约 1 token 的经验值。"""
    chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
    other_chars = len(text) - chinese_chars
    # 中文 1 字符约 1 token；英文 4 字符约 1 token
    return chinese_chars + other_chars // 4


def _split_by_tokens(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """
    按近似 token 数滑动窗口切分文本。

    切分点优先选择句子边界（句号、换行），避免在词中间截断。
    """
    if _token_count(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks: list[str] = []
    # 用句号、问号、感叹号、换行作为候选切分点
    sentences = _split_sentences(text)

    current = ""
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = _token_count(sentence)
        if current_tokens + sent_tokens > chunk_size and current:
            chunks.append(current.strip())
            # overlap：保留当前块尾部，与新块拼接
            if overlap > 0:
                tail = _take_tail_tokens(current, overlap)
                current = tail + sentence
                current_tokens = _token_count(current)
            else:
                current = sentence
                current_tokens = sent_tokens
        else:
            current = (current + sentence).strip()
            current_tokens += sent_tokens

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _split_sentences(text: str) -> list[str]:
    """按中英文标点切分句子，保留标点。"""
    import re
    # 中英文句号、问号、感叹号、换行作为分隔
    parts = re.split(r"(?<=[。！？\.\!\?\n])", text)
    return [p for p in parts if p.strip()]


def _take_tail_tokens(text: str, n_tokens: int) -> str:
    """从文本尾部截取约 n_tokens 的内容，从句子边界开始。"""
    sentences = _split_sentences(text)
    tail = ""
    for sent in reversed(sentences):
        candidate = sent + tail
        if _token_count(candidate) > n_tokens:
            break
        tail = candidate
    return tail


def _group_by_section(
    blocks: list[DocumentBlock],
) -> Iterator[list[DocumentBlock]]:
    """
    以标题块为边界把 blocks 分组。

    第一个标题之前的内容归为前导组，之后每个标题开始一个新组。
    没有标题的文档整体作为一组。
    """
    current_group: list[DocumentBlock] = []

    for block in blocks:
        if block.block_type == BlockType.HEADING and current_group:
            yield current_group
            current_group = [block]
        else:
            current_group.append(block)

    if current_group:
        yield current_group


def _section_to_text(blocks: list[DocumentBlock]) -> str:
    """把一个 section 内的 blocks 拼成文本，保留标题行。"""
    parts: list[str] = []
    for b in blocks:
        if b.text.strip():
            parts.append(b.text.strip())
    return "\n\n".join(parts)


def _process_atomic_block(
    block: DocumentBlock,
    doc_id: str,
    tenant_id: str,
    parent_index: int,
    doc_metadata: dict[str, str],
) -> tuple[Chunk, list[Chunk]]:
    """处理不可拆分块（表格、列表）：作为父块，不再切子块。"""
    parent = Chunk(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        tenant_id=tenant_id,
        parent_id=None,
        text=block.text,
        chunk_index=parent_index,
        is_parent=True,
        page_number=block.page_number,
        block_type=block.block_type,
        metadata={"atomic": True, **doc_metadata, **block.metadata},
    )
    # 原子块同时作为自己的子块，保证检索时能命中
    child = Chunk(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        tenant_id=tenant_id,
        parent_id=parent.chunk_id,
        text=block.text,
        chunk_index=0,
        is_parent=False,
        page_number=block.page_number,
        block_type=block.block_type,
        metadata={"atomic": True, **doc_metadata, **block.metadata},
    )
    return parent, [child]


def chunk_document(
    parsed: ParsedDocument,
    tenant_id: str,
) -> tuple[list[Chunk], list[Chunk]]:
    """
    把解析后的文档切分成父子块。

    返回：(parent_chunks, child_chunks)
    - parent_chunks：用于存储完整上下文，命中后传给 LLM
    - child_chunks：用于向量检索，关联到父块
    """
    settings = get_settings()
    atomic_types = set(settings.chunking.atomic_types)

    # 提取文档级元信息，传递给每个 chunk
    doc_metadata = {
        "filename": parsed.filename,
        "department": parsed.raw_metadata.get("department", ""),
        "version": parsed.raw_metadata.get("version", ""),
        "source_type": parsed.raw_metadata.get("source_type", ""),
    }

    parents: list[Chunk] = []
    children: list[Chunk] = []
    parent_index = 0

    for section in _group_by_section(parsed.blocks):
        # 先把 section 内的不可拆分块单独处理
        atomic_blocks = [b for b in section if b.block_type.value in atomic_types]
        text_blocks = [b for b in section if b.block_type.value not in atomic_types]

        section_text = _section_to_text(text_blocks)
        if not section_text.strip() and not atomic_blocks:
            continue

        # 1. 切父块
        if section_text.strip():
            parent_texts = _split_by_tokens(
                section_text,
                settings.chunking.parent_chunk_size,
                settings.chunking.parent_chunk_overlap,
            )
        else:
            parent_texts = []

        # 2. 每个父块切子块
        for ptext in parent_texts:
            parent = Chunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=parsed.doc_id,
                tenant_id=tenant_id,
                parent_id=None,
                text=ptext,
                chunk_index=parent_index,
                is_parent=True,
                page_number=section[0].page_number if section else None,
                block_type=BlockType.PARAGRAPH,
                metadata=doc_metadata.copy(),
            )
            parents.append(parent)

            child_texts = _split_by_tokens(
                ptext,
                settings.chunking.child_chunk_size,
                settings.chunking.child_chunk_overlap,
            )
            for cidx, ctext in enumerate(child_texts):
                children.append(Chunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=parsed.doc_id,
                    tenant_id=tenant_id,
                    parent_id=parent.chunk_id,
                    text=ctext,
                    chunk_index=cidx,
                    is_parent=False,
                    page_number=parent.page_number,
                    block_type=BlockType.PARAGRAPH,
                    metadata=doc_metadata.copy(),
                ))
            parent_index += 1

        # 3. 不可拆分块各自独立成父子块
        for ablock in atomic_blocks:
            parent, child_list = _process_atomic_block(
                ablock, parsed.doc_id, tenant_id, parent_index, doc_metadata
            )
            parents.append(parent)
            children.extend(child_list)
            parent_index += 1

    logger.info(
        "分块完成",
        extra={
            "doc_id": parsed.doc_id,
            "parents": len(parents),
            "children": len(children),
        },
    )
    return parents, children
