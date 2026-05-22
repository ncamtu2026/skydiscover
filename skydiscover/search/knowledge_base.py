"""Simple cross-task knowledge base for SkyDiscover."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from skydiscover.config import KnowledgeBaseConfig

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeBaseEntry:
    id: str
    task: str
    task_formalization_and_decomposition: str = ""
    solution: str = ""
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class KnowledgeBase:
    """A lightweight, file-backed retrieval store for prior task examples."""

    def __init__(self, config: KnowledgeBaseConfig):
        self.config = config
        self.entries: List[KnowledgeBaseEntry] = []
        if self.config.enabled and self.config.source_path:
            self.load(self.config.source_path)

    def load(self, source_path: str) -> None:
        """Load knowledge entries from a supported file or directory."""
        path = Path(source_path)
        if not path.exists():
            logger.warning("Knowledge base source path does not exist: %s", source_path)
            return

        entries: List[KnowledgeBaseEntry] = []
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix in {".json", ".jsonl"}:
                    entries.extend(self._load_file(child))
        else:
            entries.extend(self._load_file(path))

        self.entries = entries
        logger.info("Loaded %d knowledge base entries from %s", len(self.entries), source_path)

    def _load_file(self, path: Path) -> List[KnowledgeBaseEntry]:
        if path.suffix == ".jsonl":
            return self._load_jsonl(path)
        if path.suffix == ".json":
            return self._load_json(path)
        logger.warning("Unsupported knowledge base file type: %s", path)
        return []

    def _load_jsonl(self, path: Path) -> List[KnowledgeBaseEntry]:
        entries: List[KnowledgeBaseEntry] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entries.append(self._entry_from_dict(data, path))
                    except json.JSONDecodeError as exc:
                        logger.warning("Skipping invalid JSONL line in %s: %s", path, exc)
        except Exception as exc:
            logger.warning("Could not read knowledge base JSONL %s: %s", path, exc)
        return entries

    def _load_json(self, path: Path) -> List[KnowledgeBaseEntry]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Could not read knowledge base JSON %s: %s", path, exc)
            return []

        if isinstance(data, list):
            return [self._entry_from_dict(item, path) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [self._entry_from_dict(data, path)]
        logger.warning("Unexpected JSON shape for knowledge base file %s", path)
        return []

    def _entry_from_dict(self, data: Dict[str, Any], path: Path) -> KnowledgeBaseEntry:
        entry_id = str(data.get("id") or data.get("task") or f"entry_{len(self.entries)+1}")
        return KnowledgeBaseEntry(
            id=entry_id,
            task=str(data.get("task", "")),
            task_formalization_and_decomposition=str(
                data.get("task_formalization_and_decomposition", "")
            ),
            solution=str(data.get("solution", "")),
            source=str(data.get("source", "")) if data.get("source") is not None else None,
            metadata={k: v for k, v in data.items() if k not in {"id", "task", "task_formalization_and_decomposition", "solution", "source"}},
        )

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[KnowledgeBaseEntry]:
        if not query or not self.entries:
            return []

        top_k = top_k or self.config.max_matches
        query_tokens = self._tokenize(query)
        scored: List[tuple[float, KnowledgeBaseEntry]] = []
        for entry in self.entries:
            score = self._score_entry(entry, query_tokens)
            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for score, entry in scored[:top_k] if score > 0]

    def _tokenize(self, text: str) -> List[str]:
        return [tok.lower() for tok in re.findall(r"\w+", text)]

    def _score_entry(self, entry: KnowledgeBaseEntry, query_tokens: List[str]) -> float:
        if self.config.retrieval_method == "text_overlap":
            source_text = " ".join(
                [entry.task, entry.task_formalization_and_decomposition] +
                ([entry.solution] if self.config.include_solution_snippets else [])
            )
            entry_tokens = self._tokenize(source_text)
            if not entry_tokens:
                return 0.0
            query_counter = {tok: query_tokens.count(tok) for tok in set(query_tokens)}
            score = sum(min(query_counter.get(tok, 0), entry_tokens.count(tok)) for tok in set(query_tokens))
            return float(score) / max(1, len(set(entry_tokens)))

        return 0.0
