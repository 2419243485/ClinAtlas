"""FastAPI 主应用入口：组装路由、中间件、启动事件。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import create_tables, engine
from .middleware.audit import AuditMiddleware
from .routers import admin, auth, documents, search
from ..utils.logging import setup_logging

logger = setup_logging("clinatlas.api.main")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库表和 Qdrant Collection。"""
    logger.info("ClinAtlas API 启动中")

    # 初始化数据库表
    await create_tables()
    logger.info("数据库表已就绪")

    # 初始化 Qdrant Collection
    from ..pipeline.indexer import _ensure_collections
    _ensure_collections()
    logger.info("Qdrant Collection 已就绪")

    logger.info("ClinAtlas API 启动完成")
    yield
    logger.info("ClinAtlas API 关闭中")
    await engine.dispose()


app = FastAPI(
    title="ClinAtlas",
    description="医学知识库 RAG 服务 API",
    version="1.0.0",
    lifespan=_lifespan,
)

# 中间件（执行顺序与添加顺序相反：后添加的先执行）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# 路由注册
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=False)
