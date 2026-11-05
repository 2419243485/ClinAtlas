"""解析入口：按文件扩展名调度到对应解析器，对外只暴露 parse_document。"""

from __future__ import annotations

from pathlib import Path

from ...models.pipeline import ParsedDocument
from ...utils.logging import setup_logging
from .docx_parser import parse_docx
from .pdf_parser import parse_pdf

logger = setup_logging("clinatlas.parser")

# 扩展名 → 解析函数映射
_PARSERS = {
    ".pdf":  parse_pdf,
    ".docx": parse_docx,
    ".doc":  parse_docx,   # python-docx 兼容 .doc（部分格式）
}


def parse_document(file_path: Path, doc_id: str) -> ParsedDocument:
    """
    根据文件类型选择解析器，返回统一的 ParsedDocument。

    不支持的格式直接抛出 ValueError，让上层任务标记为 failed。
    """
    suffix = file_path.suffix.lower()
    parser = _PARSERS.get(suffix)

    if parser is None:
        supported = ", ".join(_PARSERS.keys())
        raise ValueError(
            f"不支持的文件格式 {suffix!r}，当前支持：{supported}"
        )

    logger.info(
        "开始解析文档",
        extra={"doc_id": doc_id, "file_name": file_path.name, "format": suffix},
    )
    return parser(file_path, doc_id)
