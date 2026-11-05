"""PDF 解析器：数字 PDF 用 PyMuPDF 直接提取，扫描 PDF 走 PaddleOCR。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF

from ...models.pipeline import BlockType, DocumentBlock, ParsedDocument
from ...utils.logging import setup_logging
from ...utils.settings import get_settings

logger = setup_logging("clinatlas.parser.pdf")

# 判断页面是否为扫描件：文字字符数低于此阈值则触发 OCR
_SCAN_TEXT_THRESHOLD = 50


def _is_scanned_page(page: fitz.Page) -> bool:
    text = page.get_text("text")
    return len(text.strip()) < _SCAN_TEXT_THRESHOLD


def _heading_level_from_font_size(size: float, body_size: float) -> int | None:
    """根据字号相对于正文字号推断标题层级。"""
    ratio = size / body_size if body_size > 0 else 1.0
    if ratio >= 1.8:
        return 1
    if ratio >= 1.4:
        return 2
    if ratio >= 1.15:
        return 3
    return None


def _estimate_body_font_size(page: fitz.Page) -> float:
    """取页面中出现频率最高的字号作为正文基准字号。"""
    size_counts: dict[float, int] = {}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sz = round(span["size"], 1)
                size_counts[sz] = size_counts.get(sz, 0) + len(span["text"])
    if not size_counts:
        return 10.0
    return max(size_counts, key=size_counts.get)


def _extract_blocks_from_page(page: fitz.Page) -> list[DocumentBlock]:
    """从单页 PDF 提取结构化块，识别标题、段落和表格。"""
    blocks: list[DocumentBlock] = []
    page_number = page.number + 1
    body_size = _estimate_body_font_size(page)

    raw_blocks = page.get_text("dict")["blocks"]
    for raw in raw_blocks:
        # 图片块，跳过（仅提取图注）
        if raw.get("type") == 1:
            continue

        lines_text: list[str] = []
        is_bold_dominant = False
        dominant_size = body_size

        sizes: list[float] = []
        bold_chars = 0
        total_chars = 0

        for line in raw.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not text:
                    continue
                line_parts.append(text)
                sizes.append(span["size"])
                flags = span.get("flags", 0)
                total_chars += len(text)
                if flags & 16:  # bold flag
                    bold_chars += len(text)
            if line_parts:
                lines_text.append(" ".join(line_parts))

        if not lines_text:
            continue

        full_text = "\n".join(lines_text).strip()
        if not full_text:
            continue

        if sizes:
            dominant_size = max(set(sizes), key=sizes.count)
        if total_chars > 0:
            is_bold_dominant = (bold_chars / total_chars) > 0.6

        heading_level = _heading_level_from_font_size(dominant_size, body_size)

        # 短文本 + 加粗或大字号 → 标题
        if heading_level and (is_bold_dominant or dominant_size > body_size * 1.1):
            blocks.append(DocumentBlock(
                block_type=BlockType.HEADING,
                text=full_text,
                heading_level=heading_level,
                page_number=page_number,
            ))
        else:
            blocks.append(DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text=full_text,
                page_number=page_number,
            ))

    # 提取表格（PyMuPDF 1.23+ 支持）
    try:
        for table in page.find_tables().tables:
            rows = table.extract()
            if not rows:
                continue
            lines = []
            for row in rows:
                cells = [str(cell or "").strip() for cell in row]
                lines.append(" | ".join(cells))
            table_text = "\n".join(lines)
            if table_text.strip():
                blocks.append(DocumentBlock(
                    block_type=BlockType.TABLE,
                    text=table_text,
                    page_number=page_number,
                ))
    except AttributeError:
        # PyMuPDF 版本不支持 find_tables，跳过
        pass

    return blocks


def _ocr_page(page: fitz.Page, ocr_lang: str = "ch") -> list[DocumentBlock]:
    """对扫描页面执行 OCR，返回段落块列表。"""
    try:
        from paddleocr import PaddleOCR  # 延迟导入，非 OCR 路径不加载
    except ImportError:
        logger.warning("PaddleOCR 未安装，扫描页面将被跳过", extra={"page": page.number + 1})
        return []

    settings = get_settings()
    ocr = PaddleOCR(use_angle_cls=True, lang=ocr_lang, use_gpu=settings.ocr.use_gpu, show_log=False)

    mat = fitz.Matrix(2.0, 2.0)  # 2x 分辨率，提升 OCR 准确率
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")

    result = ocr.ocr(img_bytes, cls=True)
    if not result or not result[0]:
        return []

    texts = [line[1][0] for line in result[0] if line[1][0].strip()]
    if not texts:
        return []

    return [DocumentBlock(
        block_type=BlockType.PARAGRAPH,
        text="\n".join(texts),
        page_number=page.number + 1,
        metadata={"ocr": True},
    )]


def _clean_text(text: str) -> str:
    """清洗文本：去多余空白、修复常见乱码模式。"""
    # 合并连续空白（保留换行用于段落识别）
    text = re.sub(r"[ \t]+", " ", text)
    # 去除页眉页脚常见分隔符
    text = re.sub(r"-{3,}|={3,}|_{3,}", "", text)
    # 去除行首行尾空白
    text = "\n".join(line.strip() for line in text.splitlines())
    # 合并三个以上连续空行为两个
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_pdf(file_path: Path, doc_id: str) -> ParsedDocument:
    """
    解析 PDF 文件，返回结构化的 ParsedDocument。

    数字 PDF 走 PyMuPDF 块提取；扫描页面自动降级为 PaddleOCR。
    """
    settings = get_settings()
    all_blocks: list[DocumentBlock] = []

    with fitz.open(str(file_path)) as doc:
        page_count = len(doc)
        language = doc.metadata.get("language", "unknown") or "unknown"
        raw_metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "creator": doc.metadata.get("creator", ""),
            "page_count": page_count,
        }

        for page in doc:
            if settings.ocr.enabled and _is_scanned_page(page):
                logger.info(
                    "页面为扫描件，启用 OCR",
                    extra={"doc_id": doc_id, "page": page.number + 1},
                )
                blocks = _ocr_page(page, ocr_lang=settings.ocr.lang)
            else:
                blocks = _extract_blocks_from_page(page)

            # 逐块清洗文本
            for b in blocks:
                b.text = _clean_text(b.text)

            all_blocks.extend(b for b in blocks if b.text)

    logger.info(
        "PDF 解析完成",
        extra={"doc_id": doc_id, "pages": page_count, "blocks": len(all_blocks)},
    )
    return ParsedDocument(
        doc_id=doc_id,
        filename=file_path.name,
        language=language,
        page_count=page_count,
        blocks=all_blocks,
        raw_metadata=raw_metadata,
    )
