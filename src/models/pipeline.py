"""离线处理流水线内部数据结构，不依赖 ORM，纯 Pydantic 模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SourceType(str, Enum):
    CLINICAL_GUIDELINE = "clinical_guideline"
    DRUG_MANUAL = "drug_manual"
    DIAGNOSIS_STANDARD = "diagnosis_standard"
    NURSING_PROTOCOL = "nursing_protocol"
    RESEARCH_PAPER = "research_paper"
    OTHER = "other"


class BlockType(str, Enum):
    """文档解析后的块类型，影响分块策略。"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    CODE_BLOCK = "code_block"
    CAPTION = "caption"


class DocumentBlock(BaseModel):
    """文档解析后的最小结构单元，分块器的输入。"""
    block_type: BlockType
    text: str
    heading_level: int | None = None   # 仅 HEADING 类型有效，1-6
    page_number: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """文档解析器的完整输出。"""
    doc_id: str
    filename: str
    language: str = "unknown"
    page_count: int = 0
    blocks: list[DocumentBlock]
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """分块后的文本单元，区分父子层级。"""
    chunk_id: str
    doc_id: str
    tenant_id: str
    parent_id: str | None = None       # None 表示自身是父块
    text: str
    chunk_index: int
    is_parent: bool = False
    page_number: int | None = None
    block_type: BlockType = BlockType.PARAGRAPH
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexedChunk(Chunk):
    """写入向量库后附带向量的 chunk。"""
    embedding: list[float]
