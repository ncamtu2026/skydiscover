"""Tests for the KnowledgeBase retrieval module."""

import json
from pathlib import Path

from skydiscover.config import KnowledgeBaseConfig
from skydiscover.search.knowledge_base import KnowledgeBase


def test_knowledge_base_loads_jsonl_and_retrieves(tmp_path: Path):
    source = tmp_path / "kb.jsonl"
    entries = [
        {
            "id": "task-1",
            "task": "Solve matrix multiplication efficiently",
            "task_formalization_and_decomposition": "Decompose into block matrix operations.",
            "solution": "def matmul(A, B): ...",
            "source": "paper-1",
        },
        {
            "id": "task-2",
            "task": "Optimize convolution loops",
            "task_formalization_and_decomposition": "Reorder loops and exploit locality.",
            "solution": "def conv2d(x, w): ...",
            "source": "paper-2",
        },
    ]
    source.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

    cfg = KnowledgeBaseConfig(enabled=True, source_path=str(source), max_matches=2)
    kb = KnowledgeBase(cfg)

    assert len(kb.entries) == 2
    results = kb.retrieve("matrix multiplication block", top_k=1)
    assert len(results) == 1
    assert results[0].id == "task-1"
    assert "matmul" in results[0].solution


def test_knowledge_base_loads_json_list(tmp_path: Path):
    source = tmp_path / "kb.json"
    data = [
        {
            "id": "task-a",
            "task": "Find shortest path",
            "task_formalization_and_decomposition": "Use Dijkstra or A* search.",
            "solution": "def shortest_path(graph, start, end): ...",
        }
    ]
    source.write_text(json.dumps(data), encoding="utf-8")

    cfg = KnowledgeBaseConfig(enabled=True, source_path=str(source), max_matches=3)
    kb = KnowledgeBase(cfg)

    assert len(kb.entries) == 1
    assert kb.entries[0].task == "Find shortest path"
    assert kb.entries[0].id == "task-a"
    assert kb.retrieve("shortest path")[0].id == "task-a"
