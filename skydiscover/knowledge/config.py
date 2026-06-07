from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class KnowledgeEvolveConfig:
    """
    Standalone configuration for the KnowledgeEvolve RAG module.

    Contains only the module's own params (embedding, ChromaDB, retrieval,
    sampling, output). Integration flags (enabled, use_in_parent, etc.) live
    in the search algorithm's own config (e.g. AdaEvolveDatabaseConfig).
    """

    # --- Embedding backend ---
    embedding_backend: str = "gemini"               # "gemini" | "huggingface" | "openai"
    gemini_embedding_model: str = "models/text-embedding-004"
    huggingface_embedding_model: str = "BAAI/bge-small-en-v1.5"
    huggingface_device: str = "cpu"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_api_key: Optional[str] = None   # if set, takes priority over OPENAI_API_KEY env var
    openai_embedding_api_base: Optional[str] = None  # None = OpenAI default

    # --- ChromaDB ---
    chroma_persist_dir: str = "./chroma_db"
    collection_name: str = "knowledge_base"

    # --- Per-level retrieval params ---
    # L1 = paradigm (most exploratory)
    # L2 = parent + explore (moderate)
    # L3 = parent + exploit (most specific)
    top_k: Dict[str, int] = field(
        default_factory=lambda: {"L1": 20, "L2": 10, "L3": 5}
    )
    softmax_temperature: Dict[str, float] = field(
        default_factory=lambda: {"L1": 5.0, "L2": 1.5, "L3": 0.5}
    )
    query_llm_temperature: Dict[str, float] = field(
        default_factory=lambda: {"L1": 1.2, "L2": 0.9, "L3": 0.3}
    )

    # --- Sampling ---
    n_weighted_samples: int = 6
    n_random_samples: int = 1

    # --- Output ---
    output_mode: str = "raw_text"                   # "raw_text" | "digest"
    max_tokens_per_sample: Optional[int] = None     # None = no truncation

    # --- Fields to index / query ---
    content_fields: List[str] = field(
        default_factory=lambda: [
            "summary",
            "motivation_questions",
            "all_solutions",
            "all_results",
            "contributions",
        ]
    )
