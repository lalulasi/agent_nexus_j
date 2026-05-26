"""嵌入服务工厂：始终使用本地 fastembed 模型（ONNX，无需 PyTorch 或外部 API）。

- config.embedding_model 为空 → 默认 BAAI/bge-small-zh-v1.5
- config.embedding_model 已设置 → 从 HuggingFace 下载对应 ONNX 模型并缓存本地
"""
from __future__ import annotations

from api.app.infrastructure.database.models import LLMConfig
from api.app.infrastructure.embedding.local_service import DEFAULT_MODEL, LocalEmbeddingService


def make_embedding_service(config: LLMConfig) -> LocalEmbeddingService:
    model_name = (config.embedding_model or "").strip() or DEFAULT_MODEL
    return LocalEmbeddingService(model_name=model_name)
