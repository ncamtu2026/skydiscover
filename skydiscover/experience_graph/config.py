from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExperienceGraphConfig:
    """
    Standalone configuration for the ExperienceGraph module.

    Integration flags (use_experience_graph) live in AdaEvolveDatabaseConfig.
    """

    # LLM call settings for LLM_place (classify solution into tree)
    place_temperature: float = 0.3
    place_max_tokens: int = 8000   # high to accommodate thinking models (glm-4.7 etc.)

    # LLM call settings for LLM_group_leaves (compress mechanism nodes)
    group_temperature: float = 0.3
    group_max_tokens: int = 4000   # high to accommodate thinking models

    # Compression threshold: mechanism nodes with more than this many leaves get
    # compressed via LLM_group_leaves when summarize() is called
    compress_threshold: int = 4

    # Max chars of rationale passed to LLM_place (to stay within prompt limits)
    rationale_max_chars: int = 2000

    # Max chars for the total tree rendering passed to LLM_place
    tree_render_max_chars: int = 8000

    # Save a full-tree snapshot every N iterations (also saved at first insert,
    # each summarize() call, and at shutdown)
    snapshot_interval: int = 50
