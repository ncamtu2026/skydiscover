"""Tests for KnowledgeBaseConfig integration with Config."""

from skydiscover.config import Config, KnowledgeBaseConfig


class TestKnowledgeBaseConfig:
    def test_default_knowledge_base_disabled(self):
        cfg = Config()
        assert isinstance(cfg.knowledge_base, KnowledgeBaseConfig)
        assert cfg.knowledge_base.enabled is False
        assert cfg.knowledge_base.source_path is None
        assert cfg.knowledge_base.max_matches == 5
        assert cfg.knowledge_base.retrieval_method == "text_overlap"

    def test_config_round_trip_preserves_knowledge_base(self):
        raw = {
            "knowledge_base": {
                "enabled": True,
                "source_path": "./kb.jsonl",
                "max_matches": 3,
                "retrieval_method": "text_overlap",
                "include_solution_snippets": False,
                "embedding_model": "test-model",
            }
        }

        cfg = Config.from_dict(raw)
        assert cfg.knowledge_base.enabled is True
        assert cfg.knowledge_base.source_path == "./kb.jsonl"
        assert cfg.knowledge_base.max_matches == 3
        assert cfg.knowledge_base.include_solution_snippets is False
        assert cfg.knowledge_base.embedding_model == "test-model"

        serialized = cfg.to_dict()
        assert serialized["knowledge_base"]["enabled"] is True
        assert serialized["knowledge_base"]["source_path"] == "./kb.jsonl"
        assert serialized["knowledge_base"]["max_matches"] == 3
        assert serialized["knowledge_base"]["include_solution_snippets"] is False
        assert serialized["knowledge_base"]["embedding_model"] == "test-model"
