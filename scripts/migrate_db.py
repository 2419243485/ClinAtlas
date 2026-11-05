"""
数据库表结构升级脚本
用于后续版本迁移，保留历史记录
"""
import asyncio
import asyncpg
from pathlib import Path
from datetime import datetime
from src.utils.settings import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Migration:
    """单个迁移定义"""

    def __init__(self, version: str, description: str, sql: str):
        self.version = version
        self.description = description
        self.sql = sql


# 迁移清单（按版本号顺序）
MIGRATIONS = [
    Migration(
        version="0.1.0",
        description="初始化表结构",
        sql="""
        -- 该版本的表结构已在 main.py 启动时自动创建
        -- 此处为占位记录
        """
    ),

    Migration(
        version="0.2.0",
        description="添加文档标签字段",
        sql="""
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS tags TEXT[];
        CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING GIN(tags);
        """
    ),

    Migration(
        version="0.3.0",
        description="添加用户最后登录时间",
        sql="""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;
        """
    ),

    Migration(
        version="0.4.0",
        description="添加检索历史评分字段",
        sql="""
        ALTER TABLE search_history ADD COLUMN IF NOT EXISTS rating INTEGER;
        ALTER TABLE search_history ADD COLUMN IF NOT EXISTS feedback_comment TEXT;
        """
    ),
]


async def create_migration_table(conn):
    """创建迁移记录表"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            version VARCHAR(20) NOT NULL UNIQUE,
            description TEXT,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


async def get_applied_versions(conn) -> set:
    """获取已应用的迁移版本"""
    rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY applied_at")
    return {row['version'] for row in rows}


async def apply_migration(conn, migration: Migration):
    """应用单个迁移"""
    logger.info(f"应用迁移 {migration.version}: {migration.description}")

    async with conn.transaction():
        # 执行迁移 SQL
        await conn.execute(migration.sql)

        # 记录迁移历史
        await conn.execute(
            """
            INSERT INTO schema_migrations (version, description)
            VALUES ($1, $2)
            """,
            migration.version,
            migration.description
        )

    logger.info(f"迁移 {migration.version} 完成")


async def migrate():
    """执行数据库迁移"""
    settings = get_settings()

    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
    )

    try:
        # 确保迁移表存在
        await create_migration_table(conn)

        # 获取已应用版本
        applied = await get_applied_versions(conn)
        logger.info(f"已应用的迁移版本: {sorted(applied)}")

        # 筛选待执行的迁移
        pending = [m for m in MIGRATIONS if m.version not in applied]

        if not pending:
            logger.info("没有待执行的迁移")
            print("\n数据库结构已是最新版本")
            return

        print(f"\n发现 {len(pending)} 个待执行的迁移:")
        for m in pending:
            print(f"  - {m.version}: {m.description}")

        confirm = input("\n确认执行迁移？(yes/no): ")
        if confirm.lower() != "yes":
            print("已取消")
            return

        # 逐个应用迁移
        for migration in pending:
            await apply_migration(conn, migration)

        print(f"\n成功应用 {len(pending)} 个迁移")

    except Exception as e:
        logger.error(f"迁移失败: {e}", exc_info=True)
        raise
    finally:
        await conn.close()


async def show_status():
    """显示迁移状态"""
    settings = get_settings()

    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
    )

    try:
        await create_migration_table(conn)
        applied = await get_applied_versions(conn)

        print("\n数据库迁移状态")
        print("="*60)

        for m in MIGRATIONS:
            status = "✓ 已应用" if m.version in applied else "✗ 待执行"
            print(f"{status}  {m.version:10s}  {m.description}")

        print("="*60)

    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ClinAtlas 数据库迁移工具")
    parser.add_argument(
        "action",
        choices=["migrate", "status"],
        help="操作: migrate=执行迁移 | status=查看状态"
    )

    args = parser.parse_args()

    if args.action == "migrate":
        asyncio.run(migrate())
    elif args.action == "status":
        asyncio.run(show_status())
