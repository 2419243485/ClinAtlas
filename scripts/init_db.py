"""
数据库初始化脚本
- 建表（如果不存在）
- 创建默认租户
- 创建管理员账号
- 创建各科室测试用户
"""
import sys
import asyncio
import bcrypt
import asyncpg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.settings import get_settings

# ── DDL：与 src/api/main.py 保持一致 ──────────────────────────
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name       VARCHAR(255) NOT NULL,
        code       VARCHAR(64)  UNIQUE NOT NULL,
        created_at TIMESTAMPTZ  DEFAULT NOW()
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
]


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def _connect() -> asyncpg.Connection:
    settings = get_settings()
    dsn = settings.database.url.replace("+asyncpg", "")
    return await asyncpg.connect(dsn)


async def create_tables(conn: asyncpg.Connection) -> None:
    """建表（幂等，已存在则跳过）。"""
    for stmt in _DDL:
        await conn.execute(stmt)
    print("✓ 表结构已就绪")


async def init_database() -> None:
    conn = await _connect()
    try:
        await create_tables(conn)

        # 租户
        tenant_id = await conn.fetchval(
            "SELECT id FROM tenants WHERE code = $1", "default"
        )
        if not tenant_id:
            tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name, code) VALUES ($1, $2) RETURNING id",
                "默认医院", "default",
            )
            print(f"✓ 创建租户: 默认医院  id={tenant_id}")
        else:
            print(f"✓ 租户已存在  id={tenant_id}")

        # 管理员
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM users WHERE username = $1)", "admin"
        )
        if not exists:
            uid = await conn.fetchval(
                "INSERT INTO users (tenant_id, username, password_hash, role, department) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                tenant_id, "admin", _hash("admin123"), "admin", "信息科",
            )
            print(f"✓ 创建管理员: admin / admin123  id={uid}")
        else:
            print("✓ 管理员已存在")

        # 科室测试用户
        test_users = [
            ("doctor_internal",  "doc123",   "doctor", "内科"),
            ("doctor_surgery",   "doc123",   "doctor", "外科"),
            ("doctor_endocrine", "doc123",   "doctor", "内分泌科"),
            ("doctor_cardio",    "doc123",   "doctor", "心血管科"),
            ("nurse_icu",        "nurse123", "doctor", "ICU"),
            ("doctor_emergency", "doc123",   "doctor", "急诊科"),
            ("pharmacist",       "pharm123", "doctor", "药剂科"),
            ("nurse_general",    "nurse123", "doctor", "护理部"),
        ]
        for username, password, role, dept in test_users:
            ex = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM users WHERE username = $1)", username
            )
            if not ex:
                await conn.execute(
                    "INSERT INTO users (tenant_id, username, password_hash, role, department) "
                    "VALUES ($1,$2,$3,$4,$5)",
                    tenant_id, username, _hash(password), role, dept,
                )

        print()
        print("=" * 58)
        print("  数据库初始化完成")
        print("=" * 58)
        print("  管理员账号:  admin  /  admin123")
        print()
        print(f"  {'用户名':<22} {'密码':<10} 科室")
        print(f"  {'-'*50}")
        for u, p, _, d in test_users:
            print(f"  {u:<22} {p:<10} {d}")
        print("=" * 58)

    finally:
        await conn.close()


async def reset_database() -> None:
    conn = await _connect()
    try:
        for t in ["audit_logs", "search_feedback", "document_versions",
                  "documents", "users", "tenants"]:
            try:
                await conn.execute(f"TRUNCATE TABLE {t} CASCADE")
                print(f"  清空: {t}")
            except Exception:
                pass
    finally:
        await conn.close()
    await init_database()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ClinAtlas 数据库管理")
    parser.add_argument("action", choices=["init", "reset"],
                        help="init=初始化  reset=清空并重建")
    args = parser.parse_args()

    if args.action == "init":
        asyncio.run(init_database())
    elif args.action == "reset":
        confirm = input("确认清空全部数据并重建？(yes/no): ")
        if confirm.lower() == "yes":
            asyncio.run(reset_database())
        else:
            print("已取消")
