"""DOCX 解析器：利用 python-docx 提取段落、标题、表格和列表。"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ...models.pipeline import BlockType, DocumentBlock, ParsedDocument
from ...utils.logging import setup_logging

logger = setup_logging("clinatlas.parser.docx")

# Word 内置标题样式名前缀
_HEADING_STYLE_PREFIX = "heading"


def _get_heading_level(para: Paragraph) -> int | None:
    """从段落样式名推断标题层级，返回 1-6 或 None。"""
    style_name = para.style.name.lower()
    if style_name.startswith(_HEADING_STYLE_PREFIX):
        suffix = style_name.replace(_HEADING_STYLE_PREFIX, "").strip()
        try:
            return int(suffix)
        except ValueError:
            return 1
    return None


def _is_list_paragraph(para: Paragraph) -> bool:
    """判断段落是否属于列表项（有序或无序）。"""
    return para.style.name.lower().startswith("list") or \
        para._p.find(qn("w:numPr")) is not None


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _table_to_text(table) -> str:
    """将 docx Table 对象转为管道分隔的文本。"""
    lines = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_docx(file_path: Path, doc_id: str) -> ParsedDocument:
    """
    解析 DOCX 文件。

    按文档中元素的原始顺序遍历，保持标题→段落→表格的层级关系，
    列表项合并为一个 LIST 块，避免碎片化。
    """
    doc = Document(str(file_path))
    all_blocks: list[DocumentBlock] = []

    # 累积连续列表项，遇到非列表元素时统一输出
    pending_list_items: list[str] = []

    def flush_list() -> None:
        if not pending_list_items:
            return
        text = _clean_text("\n".join(pending_list_items))
        if text:
            all_blocks.append(DocumentBlock(
                block_type=BlockType.LIST,
                text=text,
            ))
        pending_list_items.clear()

    # 遍历文档 body 内所有顶层元素，保留原始顺序
    body = doc.element.body
    para_index = 0
    table_index = 0

    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            if para_index >= len(doc.paragraphs):
                continue
            para = doc.paragraphs[para_index]
            para_index += 1

            text = para.text.strip()
            if not text:
                flush_list()
                continue

            heading_level = _get_heading_level(para)
            if heading_level:
                flush_list()
                all_blocks.append(DocumentBlock(
                    block_type=BlockType.HEADING,
                    text=_clean_text(text),
                    heading_level=heading_level,
                ))
            elif _is_list_paragraph(para):
                pending_list_items.append(text)
            else:
                flush_list()
                all_blocks.append(DocumentBlock(
                    block_type=BlockType.PARAGRAPH,
                    text=_clean_text(text),
                ))

        elif tag == "tbl":
            flush_list()
            if table_index >= len(doc.tables):
                continue
            table = doc.tables[table_index]
            table_index += 1
            table_text = _table_to_text(table)
            if table_text.strip():
                all_blocks.append(DocumentBlock(
                    block_type=BlockType.TABLE,
                    text=table_text,
                ))

    flush_list()

    raw_metadata = {
        "author": doc.core_properties.author or "",
        "created": str(doc.core_properties.created or ""),
        "modified": str(doc.core_properties.modified or ""),
    }

    logger.info(
        "DOCX 解析完成",
        extra={"doc_id": doc_id, "blocks": len(all_blocks)},
    )
    return ParsedDocument(
        doc_id=doc_id,
        filename=file_path.name,
        language="unknown",
        page_count=0,           # DOCX 无页码概念
        blocks=all_blocks,
        raw_metadata=raw_metadata,
    )
