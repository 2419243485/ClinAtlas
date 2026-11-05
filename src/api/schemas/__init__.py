"""API 请求/响应 Schema 定义。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── 文档管理 ─────────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    CLINICAL_GUIDELINE  = "clinical_guideline"
    DRUG_MANUAL         = "drug_manual"
    DIAGNOSIS_STANDARD  = "diagnosis_standard"
    NURSING_PROTOCOL    = "nursing_protocol"
    RESEARCH_PAPER      = "research_paper"
    OTHER               = "other"


class DocumentUploadMeta(BaseModel):
    department:  str | None = None
    source_type: SourceType = SourceType.OTHER
    version:     str        = "1.0"
    language:    str        = "auto"


class DocumentResponse(BaseModel):
    doc_id:      str
    filename:    str
    status:      str
    department:  str | None
    source_type: str
    version:     str
    upload_by:   str
    uploaded_at: str
    indexed_at:  str | None


class DocumentListResponse(BaseModel):
    total:  int
    page:   int
    size:   int
    items:  list[DocumentResponse]


# ── 检索 ──────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query:             str         = Field(..., min_length=1, max_length=1000)
    department_filter: list[str] | None = None
    source_types:      list[str] | None = None
    top_k:             int         = Field(default=5, ge=1, le=20)


class SourceInfo(BaseModel):
    index:      int
    filename:   str
    department: str
    version:    str
    page:       int | None
    relevance:  float


class SearchResponse(BaseModel):
    query_id:   str
    query:      str
    sources:    list[SourceInfo]
    latency_ms: int


class FeedbackRequest(BaseModel):
    query_id:   str
    rating:     int = Field(..., ge=1, le=5)
    comment:    str | None = None


# ── 鉴权 ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int           # 秒


class UserInfo(BaseModel):
    user_id:    str
    username:   str
    role:       str
    tenant_id:  str
    department: str | None
