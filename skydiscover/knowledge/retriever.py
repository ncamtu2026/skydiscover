"""
Retriever: query generation → ChromaDB search → score-weighted sampling.
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any, Dict, List, Optional

import numpy as np

from skydiscover.knowledge.config import KnowledgeEvolveConfig
from skydiscover.knowledge.embedder import BaseEmbedder
from skydiscover.llm.llm_pool import LLMPool

logger = logging.getLogger(__name__)

_LEVEL_DESCRIPTIONS: Dict[str, str] = {
    "L1": (
        "paradigm-level — find fundamentally different algorithmic approaches. "
        "Avoid directions similar to previously tried ideas."
    ),
    "L2": (
        "exploration — find diverse techniques loosely related to the current approach. "
        "Broad coverage is more important than precision."
    ),
    "L3": (
        "exploitation — find targeted optimizations specifically for the current solution. "
        "Precision matters; prefer techniques that directly improve the bottleneck."
    ),
}

_QUERY_SYSTEM = """\
You are a research assistant helping an AI optimization system find relevant academic papers.
Generate search queries for each knowledge field based on the provided context.
Return ONLY a valid JSON object. No explanation, no markdown fences.
"""

_QUERY_USER = """\
## Optimization task
{task_description}

Current best score: {current_best_score}
Search level: {level} — {level_description}
{evaluator_section}
{parent_section}
{failed_section}

## Instructions
Generate one focused search query per field. Adjust specificity to match search level {level}.
- summary: papers whose overall topic is relevant
- motivation_questions: papers addressing the same research challenges
- all_solutions: papers with relevant solution techniques
- all_results: papers with comparable empirical results or benchmarks
- contributions: papers with relevant algorithmic or theoretical contributions

Return JSON only:
{{"summary": "...", "motivation_questions": "...", "all_solutions": "...", "all_results": "...", "contributions": "..."}}
"""

class Retriever:
    """Handles query generation, ChromaDB search, and sampling."""

    def __init__(self, config: KnowledgeEvolveConfig, embedder: BaseEmbedder, llm_pool: LLMPool):
        self.config = config
        self.embedder = embedder
        self.llm_pool = llm_pool
        self._collection = None
        self.last_queries: Dict[str, str] = {}
        self.last_field_results: Dict[str, List[Dict[str, Any]]] = {}
        self.last_random_samples: List[Dict[str, Any]] = []

    def _get_collection(self):
        if self._collection is None:
            try:
                import chromadb
            except ImportError:
                raise ImportError("chromadb is required. Install with: pip install chromadb")
            client = chromadb.PersistentClient(path=str(self.config.chroma_persist_dir))
            self._collection = client.get_or_create_collection(
                name=self.config.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def _generate_queries(
        self,
        task_description: str,
        current_best_score: float,
        evaluator_feedback: Optional[str],
        level: str,
        parent_code: Optional[str],
        parent_metrics: Optional[Dict[str, Any]],
        failed_paradigms: Optional[List[str]],
    ) -> Dict[str, str]:
        """One LLM call → field-specific search queries."""
        evaluator_section = ""
        if evaluator_feedback:
            evaluator_section = f"\nEvaluator feedback:\n{evaluator_feedback[:400]}"

        parent_section = ""
        if parent_code and level in ("L2", "L3"):
            parent_section = f"\nCurrent solution preview:\n```\n{parent_code[:400]}\n```"
            if parent_metrics and level == "L3":
                metrics_str = ", ".join(
                    f"{k}: {v}" for k, v in list(parent_metrics.items())[:5]
                )
                parent_section += f"\nMetrics: {metrics_str}"

        failed_section = ""
        if failed_paradigms and level == "L1":
            failed_section = "\nPreviously tried (avoid similar):\n" + "\n".join(
                f"- {p}" for p in failed_paradigms[-5:]
            )

        user_msg = _QUERY_USER.format(
            task_description=task_description[:600],
            current_best_score=current_best_score,
            level=level,
            level_description=_LEVEL_DESCRIPTIONS[level],
            evaluator_section=evaluator_section,
            parent_section=parent_section,
            failed_section=failed_section,
        )

        temperature = self.config.query_llm_temperature[level]

        try:
            response = await self.llm_pool.generate(
                system_message=_QUERY_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                temperature=temperature,
                max_tokens=1200,
                reasoning_effort=None,  # disable thinking tokens; output is short JSON
            )
            raw = response.text or "{}"
            # Strip markdown fences if model wraps JSON in ```
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw.strip())
            queries = json.loads(raw)
            for f in self.config.content_fields:
                if f not in queries or not queries[f]:
                    queries[f] = task_description[:200]
            return queries
        except Exception as e:
            logger.warning(f"Query generation failed ({e}), falling back to task description.")
            return {f: task_description[:200] for f in self.config.content_fields}

    def _search_field(
        self, query_embedding: List[float], field_type: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """Search ChromaDB for one field, returns list of result dicts."""
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []

        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                where={"field_type": field_type},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.warning(f"ChromaDB query failed for field {field_type!r}: {e}")
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        return [
            {
                "id": doc_id,
                "document": doc,
                "metadata": meta,
                "distance": dist,  # cosine distance = 1 - similarity
            }
            for doc_id, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    def _random_sample(self, exclude_ids: set) -> Optional[Dict[str, Any]]:
        """Pick one random document from the collection, skipping excluded IDs."""
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return None

        try:
            offset = random.randint(0, max(0, count - 1))
            results = collection.get(
                limit=1,
                offset=offset,
                include=["documents", "metadatas"],
            )
            if not results["ids"]:
                return None
            doc_id = results["ids"][0]
            if doc_id in exclude_ids:
                return None
            return {
                "id": doc_id,
                "document": results["documents"][0],
                "metadata": results["metadatas"][0],
                "distance": 0.5,  # neutral placeholder; no real score for random
            }
        except Exception as e:
            logger.warning(f"Random sample failed: {e}")
            return None

    @staticmethod
    def _softmax_sample(
        candidates: List[Dict[str, Any]], n: int, temperature: float
    ) -> List[Dict[str, Any]]:
        """Sample n items without replacement, weighted by softmax of similarity scores."""
        if not candidates:
            return []
        n = min(n, len(candidates))

        distances = np.array([c["distance"] for c in candidates], dtype=float)
        similarities = 1.0 - distances
        scaled = similarities / max(temperature, 1e-8)
        scaled -= scaled.max()  # numerical stability
        weights = np.exp(scaled)
        weights /= weights.sum()

        indices = np.random.choice(len(candidates), size=n, replace=False, p=weights)
        return [candidates[int(i)] for i in indices]

    async def retrieve(
        self,
        task_description: str,
        current_best_score: float,
        evaluator_feedback: Optional[str],
        level: str,
        parent_code: Optional[str],
        parent_metrics: Optional[Dict[str, Any]],
        failed_paradigms: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """
        Full pipeline: generate queries → search all fields → dedup → sample.

        Returns:
            List of up to (n_weighted_samples + n_random_samples) result dicts,
            each with keys: id, document, metadata, distance.
        """
        collection = self._get_collection()
        if collection.count() == 0:
            logger.debug("ChromaDB collection is empty, skipping retrieval.")
            return []

        top_k = self.config.top_k[level]
        softmax_temp = self.config.softmax_temperature[level]

        queries = await self._generate_queries(
            task_description=task_description,
            current_best_score=current_best_score,
            evaluator_feedback=evaluator_feedback,
            level=level,
            parent_code=parent_code,
            parent_metrics=parent_metrics,
            failed_paradigms=failed_paradigms,
        )
        self.last_queries = queries

        # Search each field and merge, deduplicating by doc ID
        all_candidates: List[Dict[str, Any]] = []
        seen_ids: set = set()
        self.last_field_results = {}

        for field_name in self.config.content_fields:
            query_text = queries.get(field_name) or task_description[:200]
            query_emb = self.embedder.embed([query_text], task_type="query")[0]
            field_hits = self._search_field(query_emb, field_name, top_k)
            self.last_field_results[field_name] = field_hits
            for result in field_hits:
                if result["id"] not in seen_ids:
                    seen_ids.add(result["id"])
                    all_candidates.append(result)

        if not all_candidates:
            return []

        # Score-weighted sampling
        sampled = self._softmax_sample(all_candidates, self.config.n_weighted_samples, softmax_temp)
        sampled_ids = {s["id"] for s in sampled}

        # Random exploration sample
        self.last_random_samples = []
        for _ in range(self.config.n_random_samples):
            rnd = self._random_sample(exclude_ids=sampled_ids)
            if rnd:
                sampled.append(rnd)
                sampled_ids.add(rnd["id"])
                self.last_random_samples.append(rnd)

        return sampled
