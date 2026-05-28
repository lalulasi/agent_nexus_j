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
    try:
        return TextEmbedding(model_name=model_name)
    except Exception as e:
        return _handle_corrupt_cache(e, model_name, TextEmbedding)


def _handle_corrupt_cache(e: Exception, model_name: str, TextEmbedding):
    """检测损坏的模型缓存，自动清理后重试下载。"""
    import re
    import shutil
    from pathlib import Path

    err = str(e)
    is_corrupt = "tokenizer.json" in err or "could not find" in err.lower()
    if not is_corrupt:
        raise e

    # fastembed 错误信息格式: "could not find tokenizer.json in <path>"
    # 直接从错误信息中解析缓存目录并删除
    match = re.search(r'\bin\s+(.+?)\s*$', err.strip())
    if match:
        bad_dir = Path(match.group(1).strip())
        if bad_dir.exists() and "models--" in bad_dir.name:
            logger.warning(f"检测到损坏的模型缓存，正在清理: {bad_dir}")
            shutil.rmtree(bad_dir, ignore_errors=True)
            logger.info("缓存已清理，重新下载模型...")
            return TextEmbedding(model_name=model_name)

    # 解析路径失败时，给出人工清理指引
    cache_hint = Path.home() / ".cache" / "fastembed"
    raise RuntimeError(
        f"模型缓存损坏且无法自动清理，请手动删除以下目录后重启：\n"
        f"  {cache_hint}\n"
        f"原始错误：{err}"
    ) from e


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
