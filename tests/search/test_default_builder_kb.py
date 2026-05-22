"""Tests for default prompt builder knowledge example rendering."""

from skydiscover.config import Config
from skydiscover.context_builder.default import DefaultContextBuilder


def test_default_builder_includes_knowledge_examples():
    cfg = Config()
    cfg.context_builder.system_message = "Solve the target problem."
    cfg.knowledge_base.include_solution_snippets = True

    builder = DefaultContextBuilder(cfg)
    prompt = builder.build_prompt(
        current_program=None,
        context={
            "knowledge_examples": [
                {
                    "id": "kb-1",
                    "task": "Optimize graph traversal",
                    "decomposition": "Break the graph into layers and use BFS.",
                    "solution": "def traverse(graph): ...",
                    "source": "paper-x",
                    "metadata": {},
                }
            ],
            "knowledge_query": "graph optimization",
        },
    )

    assert "Related Tasks and Prior Solutions" in prompt["user"]
    assert "Optimize graph traversal" in prompt["user"]
    assert "```python" in prompt["user"]
    assert "paper-x" in prompt["user"]
