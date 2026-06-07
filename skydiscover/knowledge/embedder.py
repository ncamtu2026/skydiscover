from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, texts: List[str], task_type: str = "document") -> List[List[float]]:
        """
        Embed a list of texts.

        Args:
            texts: List of strings to embed.
            task_type: "document" for indexing, "query" for search queries.
                       Some models (e.g. Gemini) use different representations.

        Returns:
            List of embedding vectors.
        """


class GeminiEmbedder(BaseEmbedder):
    def __init__(self, model: str, api_key: str):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai is required for Gemini embedding. "
                "Install with: pip install google-generativeai"
            )
        genai.configure(api_key=api_key)
        self._genai = genai
        self.model = model

    def embed(self, texts: List[str], task_type: str = "document") -> List[List[float]]:
        genai_task = "RETRIEVAL_QUERY" if task_type == "query" else "RETRIEVAL_DOCUMENT"
        result = self._genai.embed_content(
            model=self.model,
            content=texts,
            task_type=genai_task,
        )
        # embed_content returns {"embedding": [...]} for single or list of embeddings
        embeddings = result["embedding"]
        # Normalize to list of lists
        if embeddings and isinstance(embeddings[0], float):
            return [embeddings]
        return [list(e) for e in embeddings]


class HuggingFaceEmbedder(BaseEmbedder):
    def __init__(self, model: str, device: str = "cpu"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for HuggingFace embedding. "
                "Install with: pip install sentence-transformers"
            )
        self._model = SentenceTransformer(model, device=device)

    def embed(self, texts: List[str], task_type: str = "document") -> List[List[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, model: str, api_key: str, api_base: str | None = None):
        try:
            import openai as _openai
        except ImportError:
            raise ImportError("openai is required. Install with: pip install openai")
        self._client = _openai.OpenAI(api_key=api_key, base_url=api_base)
        self.model = model

    def embed(self, texts: List[str], task_type: str = "document") -> List[List[float]]:
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


def create_embedder(config) -> BaseEmbedder:
    """Factory: create the appropriate embedder from a KnowledgeEvolveConfig."""
    if config.embedding_backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY or GOOGLE_API_KEY environment variable required "
                "for Gemini embedding."
            )
        return GeminiEmbedder(model=config.gemini_embedding_model, api_key=api_key)

    if config.embedding_backend == "huggingface":
        return HuggingFaceEmbedder(
            model=config.huggingface_embedding_model,
            device=config.huggingface_device,
        )

    if config.embedding_backend == "openai":
        api_key = (
            config.openai_embedding_api_key
            or os.environ.get("OPENAI_EMBEDDING_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "No API key for OpenAI embedding. Export OPENAI_EMBEDDING_KEY "
                "or set openai_embedding_api_key in config."
            )
        return OpenAIEmbedder(
            model=config.openai_embedding_model,
            api_key=api_key,
            api_base=config.openai_embedding_api_base,
        )

    raise ValueError(f"Unknown embedding backend: {config.embedding_backend!r}")
