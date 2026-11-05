"""统一日志配置：JSON 格式，便于医院环境接入日志聚合系统。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from .settings import get_settings


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式器，输出字段固定，便于 ELK/Loki 采集。"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exc"] = self.formatException(record.exc_info)
        # 业务自定义字段（extra 注入）
        for key in ("doc_id", "tenant_id", "chunk_id", "latency_ms", "stage"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(name: str = "clinatlas") -> logging.Logger:
    """初始化并返回指定名称的 logger。"""
    settings = get_settings()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(settings.logging.level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
