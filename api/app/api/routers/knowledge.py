"""知识库路由：上传文档、列表、删除。"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.application.rag_pipeline import RAGPipeline
from api.app.domain.schemas import KnowledgeDocumentOut
from api.app.infrastructure.database.models import KnowledgeDocument, LLMConfig
from api.app.infrastructure.database.session import get_db
from api.app.infrastructure.files.processor import process_attachment
import base64

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

DB = Annotated[AsyncSession, Depends(get_db)]


async def _get_active_config(db: AsyncSession) -> LLMConfig:
    result = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=400, detail="尚未配置模型，请先保存模型配置。")
    return config


@router.get("/", response_model=list[KnowledgeDocumentOut])
async def list_documents(db: DB):
    result = await db.execute(
        select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
    )
    return result.scalars().all()


@router.post("/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile, db: DB):
    config = await _get_active_config(db)

    raw = await file.read()
    data_b64 = base64.b64encode(raw).decode()
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "unknown"

    processed = process_attachment(filename, mime_type, data_b64)
    extracted_text = processed.get("extracted_text", "")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="无法从该文件提取文本内容，请上传 PDF/DOCX/XLSX/TXT 文件。")

    pipeline = RAGPipeline(db, config)
    doc = await pipeline.ingest(filename, mime_type, extracted_text)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, db: DB):
    doc = await db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    await db.delete(doc)
