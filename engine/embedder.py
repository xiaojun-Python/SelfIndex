import torch
from langchain_huggingface import HuggingFaceEmbeddings

from app.core.settings import settings


class EmbeddingManager:
    def __init__(self, model_name: str, preferred_device: str) -> None:
        self.model_name = model_name
        self.preferred_device = preferred_device
        self._model = None

    @property
    def device(self) -> str:
        if self.preferred_device == "cuda" and not torch.cuda.is_available():
            return "cpu"
        return self.preferred_device

    @property
    def model(self) -> HuggingFaceEmbeddings:
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
