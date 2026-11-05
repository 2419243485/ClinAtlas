"""文档管理路由：上传、列表、详情、归档、重新索引。

文件存储使用本地文件系统（data/uploads 目录），不依赖 MinIO，
适合医院单机本地化部署。
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..middleware.auth import UserInfo, get_current_user, require_role
from ..schemas import DocumentListResponse, DocumentResponse, SourceType
from ...pipeline.tasks import process_document, reindex_document
from ...utils.logging import setup_logging
from ...utils.settings import get_settings

logger = setup_logging("clinatlas.api.documents")
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
_MAX_FILE_SIZE = 100 * 1024 * 1024   # 100 MB


def _upload_root() -> Path:
    """本地上传根目录，从配置读取，默认 ./data/uploads。"""
    settings = get_settings()
    root = Path(getattr(settings, "upload_dir", "data/uploads")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _save_file(content: bytes, tenant_id: str, doc_id: str, filename: str) -> Path:
    """把文件写入 data/uploads/<tenant_id>/<doc_id>/<filename>，返回绝对路径。"""
    dest_dir = _upload_root() / tenant_id / doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(content)
    return dest


def _file_path(tenant_id: str, doc_id: str, filename: str) -> Path:
    """根据元数据拼出本地文件绝对路径（用于重建索引等场景）。"""
    return _upload_root() / tenant_id / doc_id / filename


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    department: str | None = Form(None),
    source_type: SourceType = Form(SourceType.OTHER),
    version: str = Form("1.0"),
    language: str = Form("auto"),
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """上传文档，保存到本地文件系统并触发异步处理任务。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的格式 {suffix!r}，允许：{', '.join(_ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 100MB 限制")

    target_department = department or user.department
    if user.role != "admin" and target_department != user.department:
        raise HTTPException(status_code=403, detail="只能上传到本科室")

    doc_id   = str(uuid.uuid4())
    checksum = hashlib.sha256(content).hexdigest()

    # 写入本地文件
    local_path = _save_file(content, user.tenant_id, doc_id, file.filename)
    file_path_str = str(local_path)

    # 写入数据库
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO documents "
        "(id, tenant_id, filename, file_path, checksum, source_type, department, "
        " language, version, status, upload_by) "
        "VALUES (:id, :tenant_id, :filename, :file_path, :checksum, :source_type, "
        "        :department, :language, :version, 'pending', :upload_by)"
    ), {
        "id":           doc_id,
        "tenant_id":    user.tenant_id,
        "filename":     file.filename,
        "file_path":    file_path_str,
        "checksum":     checksum,
        "source_type":  source_type.value,
        "department":   target_department,
        "language":     language,
        "version":      version,
        "upload_by":    user.user_id,
    })
    await db.commit()

    # 推送 Celery 任务（文件已在本地，直接传路径）
    process_document.delay(
        doc_id=doc_id,
        file_path=file_path_str,
        tenant_id=user.tenant_id,
        metadata={
            "department":  target_department,
            "source_type": source_type.value,
            "version":     version,
            "filename":    file.filename,
        },
    )

    logger.info("文档上传成功", extra={"doc_id": doc_id, "filename": file.filename})
    return DocumentResponse(
        doc_id=doc_id,
        filename=file.filename,
        status="pending",
        department=target_department,
        source_type=source_type.value,
        version=version,
        upload_by=user.user_id,
        uploaded_at="",
        indexed_at=None,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    size: int = 20,
    department: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    """分页查询文档列表，非管理员只看到本科室文档。"""
    from sqlalchemy import text

    base_where = "WHERE tenant_id = :tenant_id"
    params: dict = {"tenant_id": user.tenant_id}

    if user.role != "admin":
        base_where += " AND department = :department"
        params["department"] = user.department
    if department:
        base_where += " AND department = :department"
        params["department"] = department
    if status_filter:
        base_where += " AND status = :status"
        params["status"] = status_filter

    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM documents {base_where}"), params
    )).scalar() or 0

    params["limit"]  = size
    params["offset"] = (page - 1) * size
    rows = (await db.execute(
        text(f"SELECT * FROM documents {base_where} "
             "ORDER BY uploaded_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )).fetchall()

    items = [
        DocumentResponse(
            doc_id=str(r.id),
            filename=r.filename,
            status=r.status,
            department=r.department,
            source_type=r.source_type or "other",
            version=r.version,
            upload_by=str(r.upload_by),
            uploaded_at=str(r.uploaded_at),
            indexed_at=str(r.indexed_at) if r.indexed_at else None,
        )
        for r in rows
    ]
    return DocumentListResponse(total=total, page=page, size=size, items=items)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    from sqlalchemy import text
    row = (await db.execute(
        text("SELECT * FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": doc_id, "tenant_id": user.tenant_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocumentResponse(
        doc_id=str(row.id),
        filename=row.filename,
        status=row.status,
        department=row.department,
        source_type=row.source_type or "other",
        version=row.version,
        upload_by=str(row.upload_by),
        uploaded_at=str(row.uploaded_at),
        indexed_at=str(row.indexed_at) if row.indexed_at else None,
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_role("admin")),
):
    """归档文档：软删除，保留本地文件和版本历史，清除向量索引。"""
    from sqlalchemy import text
    from ...pipeline.indexer import delete_doc_chunks

    row = (await db.execute(
        text("SELECT id, file_path, version FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": doc_id, "tenant_id": user.tenant_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")

    await db.execute(text(
        "INSERT INTO document_versions (document_id, version, file_path, replaced_by) "
        "VALUES (:doc_id, :version, :file_path, :user_id)"
    ), {"doc_id": doc_id, "version": row.version, "file_path": row.file_path, "user_id": user.user_id})

    await db.execute(
        text("UPDATE documents SET status = 'archived' WHERE id = :id"), {"id": doc_id}
    )
    await db.commit()

    delete_doc_chunks(doc_id)
    logger.info("文档已归档", extra={"doc_id": doc_id, "user_id": user.user_id})


@router.post("/{doc_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_role("admin")),
):
    """重新索引文档（管理员手动触发）。"""
    from sqlalchemy import text

    row = (await db.execute(
        text("SELECT file_path FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": doc_id, "tenant_id": user.tenant_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")

    file_path = row.file_path
    if not Path(file_path).exists():
        raise HTTPException(status_code=409, detail="本地文件不存在，无法重新索引")

    reindex_document.delay(
        doc_id=doc_id,
        file_path=file_path,
        tenant_id=user.tenant_id,
    )
    logger.info("重新索引任务已提交", extra={"doc_id": doc_id})
    return {"doc_id": doc_id, "status": "reindexing"}
