"""向量嵌入管理。

这里统一封装了 embedding 模型的加载与调用，避免业务代码直接依赖底层实现。
"""

from __future__ import annotations

import torch
from langchain_huggingface import HuggingFaceEmbeddings

from app.core.settings import settings


class EmbeddingManager:
    """负责懒加载 embedding 模型，并提供统一的向量接口。"""

    def __init__(self, model_name: str, preferred_device: str) -> None:
        self.model_name = model_name
        self.preferred_device = preferred_device
        self._model: HuggingFaceEmbeddings | None = None

    @property
    def device(self) -> str:
        """优先用配置设备；如果 CUDA 不可用，则回退到 CPU。"""
        if self.preferred_device == "cuda" and not torch.cuda.is_available():
            return "cpu"
        return self.preferred_device

    @property
    def model(self) -> HuggingFaceEmbeddings:
        """模型首次访问时才真正加载，避免应用启动过重。"""
        if self._model is None:
            self._model = HuggingFaceEmbeddings(
                model_name=self.model_name,
                model_kwargs={"device": self.device},
                encode_kwargs={
                    "normalize_embeddings": True,
                    "batch_size": 32,
                },
            )
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.model.embed_query(text)


embedding_manager = EmbeddingManager(
    model_name=settings.embedding_model,
    preferred_device=settings.embedding_device,
)
