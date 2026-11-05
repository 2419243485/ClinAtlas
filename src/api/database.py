"""数据库连接与建表 DDL。

引擎和会话工厂在这里集中管理，路由统一通过 Depends(get_db) 注入会话。
表结构与 scripts/init_db.py 保持一致。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..utils.settings import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database.url,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session


# ── 建表 DDL（启动时执行，CREATE IF NOT EXISTS 保证幂等）──────────────────
DDL_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name        VARCHAR(255) NOT NULL,
        code        VARCHAR(64)  UNIQUE NOT NULL,
        created_at  TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id     UUID REFERENCES tenants(id),
        username      VARCHAR(128) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role          VARCHAR(32)  NOT NULL,
        department    VARCHAR(128),
        created_at    TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID REFERENCES tenants(id),
        filename       VARCHAR(512) NOT NULL,
        file_path      TEXT NOT NULL,
        checksum       CHAR(64)     DEFAULT '',
        source_type    VARCHAR(64),
        department     VARCHAR(128),
        language       VARCHAR(16),
        version        VARCHAR(32)  DEFAULT '1.0',
        status         VARCHAR(32)  DEFAULT 'pending',
        upload_by      UUID REFERENCES users(id),
        uploaded_at    TIMESTAMPTZ  DEFAULT NOW(),
        indexed_at     TIMESTAMPTZ,
        error_message  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_versions (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id  UUID REFERENCES documents(id),
        version      VARCHAR(32),
        file_path    TEXT,
        replaced_at  TIMESTAMPTZ DEFAULT NOW(),
        replaced_by  UUID REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id           BIGSERIAL PRIMARY KEY,
        tenant_id    UUID REFERENCES tenants(id),
        user_id      UUID REFERENCES users(id),
        action       VARCHAR(64),
        resource_id  TEXT,
        query_text   TEXT,
        ip_address   INET,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_feedback (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id    UUID REFERENCES tenants(id),
        user_id      UUID REFERENCES users(id),
        query_text   TEXT,
        rating       SMALLINT CHECK (rating BETWEEN 1 AND 5),
        comment      TEXT,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_tenant_status ON documents(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_time  ON audit_logs(tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_search_feedback_tenant   ON search_feedback(tenant_id, created_at DESC)",
]


async def create_tables() -> None:
    """执行全部 DDL。"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        for stmt in DDL_STATEMENTS:
            await conn.execute(text(stmt))
