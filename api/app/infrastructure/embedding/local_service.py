"""本地嵌入服务：基于 fastembed + ONNX，无需 PyTorch，首次启动自动下载模型。"""
from __future__ import annotations

import asyncio
from functools import lru_cache

from api.app.core.logger import logger

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_DIMS = 512


@lru_cache(maxsize=4)
def _load_model(model_name: str):
    from fastembed import TextEmbedding
    supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    if model_name not in supported:
        raise ValueError(
            f"嵌入模型 '{model_name}' 不在 fastembed 支持列表中。\n"
            f"请在设置中选择受支持的模型，推荐中文模型：\n"
            f"  • BAAI/bge-small-zh-v1.5（90 MB，默认）\n"
            f"  • jinaai/jina-embeddings-v2-base-zh（640 MB）\n"
            f"  • sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2（220 MB）"
        )
    logger.info(f"加载本地嵌入模型: {model_name}（首次使用时自动下载）")
    return TextEmbedding(model_name=model_name)


class LocalEmbeddingService:
    """使用 fastembed 在本地运行 ONNX 嵌入模型，不调用任何外部 API。"""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self.dimensions = DEFAULT_DIMS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()

        def _run() -> list[list[float]]:
            model = _load_model(self.model_name)
            return [emb.tolist() for emb in model.embed(texts)]

        return await loop.run_in_executor(None, _run)

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0]


async def preload_default_model() -> None:
    """在应用启动时预热默认本地模型（触发下载 + ONNX 编译）。"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _load_model, DEFAULT_MODEL)
    logger.info(f"本地嵌入模型已就绪: {DEFAULT_MODEL}")
