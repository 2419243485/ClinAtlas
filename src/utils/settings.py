"""配置加载：从 settings.yaml 读取，供全项目共享。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 加载项目根目录的 .env（LLM 密钥等不提交的配置），已存在的环境变量优先
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class DatabaseConfig(BaseModel):
    url: str
    pool_size: int = 10
    max_overflow: int = 20


class QdrantConfig(BaseModel):
    url: str
    collection_child: str
    collection_parent: str
    vector_size: int


class RedisConfig(BaseModel):
    url: str
    cache_ttl: int = 1800


class MinioConfig(BaseModel):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False


class EmbeddingConfig(BaseModel):
    model_name: str
    model_path: str
    batch_size: int = 64
    device: str = "cpu"
    normalize: bool = True


class RerankerConfig(BaseModel):
    model_name: str
    model_path: str
    device: str = "cpu"


class ChunkingConfig(BaseModel):
    child_chunk_size: int = 256
    child_chunk_overlap: int = 50
    parent_chunk_size: int = 1024
    parent_chunk_overlap: int = 100
    atomic_types: list[str] = Field(default_factory=lambda: ["table", "list", "code_block"])


class OcrConfig(BaseModel):
    enabled: bool = True
    lang: str = "ch"
    use_gpu: bool = False


class CeleryConfig(BaseModel):
    broker_url: str
    result_backend: str
    worker_concurrency: int = 4
    task_serializer: str = "json"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"


class LlmConfig(BaseModel):
    """LLM 接口配置，含密钥，从环境变量（.env）读取，不写入 settings.yaml。"""
    base_url: str = Field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))
    api_key: str = Field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))


class Settings(BaseModel):
    app: dict[str, Any]
    database: DatabaseConfig
    qdrant: QdrantConfig
    redis: RedisConfig
    minio: MinioConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    chunking: ChunkingConfig
    ocr: OcrConfig
    celery: CeleryConfig
    logging: LoggingConfig
    llm: LlmConfig = Field(default_factory=LlmConfig)


def _resolve_config_path() -> Path:
    """从环境变量或默认路径定位配置文件。"""
    env_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    return env_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载并缓存配置，整个进程生命周期复用同一份。"""
    config_path = _resolve_config_path()
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings(**raw)
