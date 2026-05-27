"""RAG 管道：文档摄取（ingest）和检索（query）。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.infrastructure.database.models import KnowledgeChunk, KnowledgeDocument, LLMConfig
from api.app.infrastructure.embedding.service import make_embedding_service

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
TOP_K = 5


def _split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


class RAGPipeline:
    def __init__(self, db: AsyncSession, config: LLMConfig) -> None:
        self.db = db
        self.embed_svc = make_embedding_service(config)

    async def ingest(
        self,
        filename: str,
        mime_type: str,
        text: str,
        namespace: str = "global",  # 创新点3预留：托管记忆层命名空间隔离，当前忽略
    ) -> KnowledgeDocument:
        """将文档切片后嵌入并存入知识库，返回 KnowledgeDocument。"""
        chunks = _split_text(text)
        if not chunks:
            raise ValueError("文档内容为空，无法摄取")

        doc = KnowledgeDocument(
            filename=filename,
            mime_type=mime_type,
            chunk_count=len(chunks),
        )
        self.db.add(doc)
        await self.db.flush()  # 获取 doc.id

        # 批量嵌入（一次请求）
        embeddings = await self.embed_svc.embed(chunks)

        for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            self.db.add(KnowledgeChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
            ))

        await self.db.flush()
        logger.info(f"已摄取文档 '{filename}'，共 {len(chunks)} 个切片")
        return doc

    async def query(
        self,
        question: str,
        top_k: int = TOP_K,
        namespace: str = "global",  # 创新点3预留：未来按命名空间过滤 KnowledgeDocument，当前忽略
    ) -> list[dict]:
        """
        将问题嵌入后按余弦相似度检索最相关的切片。
        返回 list[{"filename": str, "content": str, "score": float}]。
        """
        q_vec = await self.embed_svc.embed_one(question)

        # pgvector <=> 是余弦距离（越小越相似）
        result = await self.db.execute(
            select(
                KnowledgeChunk,
                KnowledgeChunk.embedding.cosine_distance(q_vec).label("distance"),
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .add_columns(KnowledgeDocument.filename)
            .order_by("distance")
            .limit(top_k)
        )
        rows = result.all()
        return [
            {
                "filename": row.filename,
                "content": row.KnowledgeChunk.content,
                "score": round(1 - float(row.distance), 4),
            }
            for row in rows
        ]
