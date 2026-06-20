"""
ExperienceGraph — records all evaluated solutions into a hierarchical
paradigm → formulation → mechanism → leaf tree, then provides a compact
summary for the paradigm breakthrough generator.

Usage:
    eg = ExperienceGraph(config, llm_pool, output_dir="./run_output")
    await eg.insert(solution_id, score, rationale, is_paradigm_breakthrough)
    summary = await eg.summarize()
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from skydiscover.experience_graph.config import ExperienceGraphConfig
from skydiscover.experience_graph.nodes import (
    GraphNode,
    count_nodes,
    find_node,
    find_parent,
    get_placement_path,
    render_for_insert,
)
from skydiscover.llm.llm_pool import LLMPool

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, tolerating markdown code fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fence: ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        return json.loads(m.group(1))
    # Last resort: find first {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    raise ValueError("no JSON object found in LLM response")

# ── System messages ─────────────────────────────────────────────────────────

_PLACE_SYSTEM = """\
You are maintaining a two-level solution tree for an optimization problem.
The tree has exactly two internal levels before leaves:
  Level 1 — problem_view:  how does this solution FRAME the problem? \
What mathematical/structural model does it reduce the problem to? \
(e.g. "Independent unicast per destination", "Shared multicast tree", "Flow decomposition")
  Level 2 — solution_strategy: given that problem framing, what is the high-level \
algorithmic strategy? \
(e.g. "Greedy shortest path", "Metric closure + MST", "LP relaxation")
  Leaf: a specific solution under that strategy.

Your task: decide where to place a new solution in the tree.
Output ONLY a valid JSON object — no markdown, no explanation, no extra text.
CRITICAL: The JSON object must start with "action": "<ACTION>" as the very first key.
Valid actions: ATTACH_TO, NEW_BRANCH_UNDER, SPLIT.

Each internal node needs a short "label" (1-4 words) AND a "description" (2 sentences):
- problem_view description: what mathematical model is being used, and why it is \
distinct from other framings in the tree.
- solution_strategy description: what algorithmic approach is applied to the framed \
problem, and what its key trade-off or assumption is.

Leaf description (3 sentences, stored as "leaf_description"):
  1. The specific algorithm or technique applied (name it precisely).
  2. A key implementation choice or design detail that distinguishes this from \
a vanilla version of the strategy.
  3. Any notable constraint handled or trade-off made in the implementation.

Reuse existing labels whenever the same concept applies.\
"""

_GROUP_SYSTEM = """\
You are grouping solutions that share the same mechanism in a solution tree.
Group solutions with the same core implementation approach; separate truly different approaches.
Be neutral — do NOT evaluate quality, potential, or rank solutions.
Output ONLY a valid JSON object — no markdown, no explanation, no extra text.\
"""

# ── JSON schemas ─────────────────────────────────────────────────────────────

_PLACE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "place_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ATTACH_TO", "NEW_BRANCH_UNDER", "SPLIT"],
                },
                "target_id": {"type": "string"},
                "new_path": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_name": {
                                "type": "string",
                                "enum": ["problem_view", "solution_strategy"],
                            },
                            "label": {"type": "string"},
                        },
                        "required": ["field_name", "label"],
                        "additionalProperties": False,
                    },
                },
                "target_leaf_id": {"type": "string"},
                "split_field_name": {
                    "type": "string",
                    "enum": ["problem_view", "solution_strategy", ""],
                },
                "new_label": {"type": "string"},
                "leaf_label": {"type": "string"},
            },
            "required": [
                "action",
                "target_id",
                "new_path",
                "target_leaf_id",
                "split_field_name",
                "new_label",
                "leaf_label",
            ],
            "additionalProperties": False,
        },
    },
}

_GROUP_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "leaf_groups",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "leaf_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["label", "leaf_ids"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        },
    },
}


class ExperienceGraph:
    """
    Records all evaluated solutions into a hierarchical tree and provides a
    compact summary for the paradigm breakthrough generator.

    This class is search-algorithm-agnostic. The caller (AdaEvolveController)
    is responsible for calling insert() after each evaluation and summarize()
    before each paradigm generation.
    """

    def __init__(
        self,
        config: ExperienceGraphConfig,
        llm_pool: LLMPool,
        output_dir: Optional[str] = None,
    ):
        self.config = config
        self.llm_pool = llm_pool
        self.output_dir = output_dir

        self.root = GraphNode(id=str(uuid.uuid4()), node_type="root", label="ROOT")
        self._total_leaves: int = 0
        self._total_internal: int = 0
        self._insert_count: int = 0   # tracks iterations for snapshot_interval

        # Paths for persistence
        self._state_path: Optional[str] = None
        self._events_path: Optional[str] = None
        self._snapshots_dir: Optional[str] = None
        if output_dir:
            self._state_path = os.path.join(output_dir, "experience_graph.json")
            self._events_path = os.path.join(output_dir, "experience_graph_events.jsonl")
            self._snapshots_dir = os.path.join(output_dir, "experience_graph_snapshots")
            os.makedirs(self._snapshots_dir, exist_ok=True)
            self._try_load()

    # ── Public API ────────────────────────────────────────────────────────────

    async def insert(
        self,
        solution_id: str,
        score: float,
        rationale: str,
        is_paradigm_breakthrough: bool = False,
        iteration: int = 0,
        parent_id: Optional[str] = None,
        placement_hint: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a new solution into the tree.

        Calls LLM_place to decide the placement, then mutates the tree and
        persists the event.

        ``placement_hint`` is an optional bias for LLM_place used by
        policy-driven callers (e.g. GraphEvolve space-explore).  When set to
        ``"new_form"`` / ``"new_dir"`` it asks LLM_place to prefer creating a
        brand-new branch (new ``problem_view`` / new ``solution_strategy``)
        rather than attaching to an existing one.  Default ``None`` keeps the
        original behaviour unchanged.

        ``extra`` is an optional dict merged into the persisted insert event
        (e.g. GraphEvolve's ``policy_action`` / ``space_target``), so search
        algorithms can record per-iteration metadata for visualisation without
        changing the tree schema.  Default ``None`` keeps events unchanged.
        """
        t0 = time.time()

        # Truncate rationale for the LLM prompt
        if len(rationale) > self.config.rationale_max_chars:
            rationale = rationale[: self.config.rationale_max_chars] + "\n... (truncated)"

        # Render current tree for the LLM
        tree_text = render_for_insert(self.root)
        if len(tree_text) > self.config.tree_render_max_chars:
            tree_text = tree_text[: self.config.tree_render_max_chars] + "\n... (truncated)"

        decision = await self._llm_place(rationale, tree_text, placement_hint=placement_hint)
        leaf_id = self._apply_decision(
            decision, solution_id, score, rationale, is_paradigm_breakthrough
        )

        elapsed_ms = int((time.time() - t0) * 1000)

        # Build placement path for logging / event
        placement_path = get_placement_path(self.root, leaf_id) if leaf_id else []
        action = decision.get("action", "UNKNOWN")
        leaf_label = decision.get("leaf_label", solution_id[:8])
        path_str = " → ".join(placement_path) if placement_path else "(root)"
        pb_marker = " [PARADIGM]" if is_paradigm_breakthrough else ""
        score_str = f"{score:.4f}" if score is not None else "N/A"

        logger.info(
            f"ExperienceGraph [{action}] \"{leaf_label}\" score={score_str}{pb_marker}"
            f" → {path_str}"
        )

        # Persist event
        event = {
            "event_type": "insert",
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "solution_id": solution_id,
            "parent_id": parent_id,
            "score": score,
            "is_paradigm_breakthrough": is_paradigm_breakthrough,
            "action": action,
            "leaf_label": leaf_label,
            "placement_path": placement_path,
            "total_leaves": self._total_leaves,
            "total_internal": self._total_internal,
            "llm_place_time_ms": elapsed_ms,
        }
        if extra:
            event.update(extra)
        self._log_event(event)

        self.save()

        self._insert_count += 1
        is_first = self._insert_count == 1
        is_interval = (
            self.config.snapshot_interval > 0
            and self._insert_count % self.config.snapshot_interval == 0
        )
        if is_first or is_interval:
            trigger = "first" if is_first else "interval"
            self._save_snapshot(iteration=iteration, trigger=trigger)

    async def summarize(self, iteration: int = 0) -> str:
        """Render the tree as compact text.

        solution_strategy nodes with more than compress_threshold leaves are compressed
        via LLM_group_leaves. Returns an empty string if the tree has no leaves.
        """
        if self._total_leaves == 0:
            return ""

        t0 = time.time()
        lines: List[str] = ["EXPLORATION SUMMARY (experience memory)", ""]
        n_compressed = 0

        for paradigm_node in self.root.children:
            n_comp = await self._render_summary_node(paradigm_node, lines, depth=0)
            n_compressed += n_comp

        summary = "\n".join(lines)
        elapsed_ms = int((time.time() - t0) * 1000)

        n_paradigms = len(self.root.children)
        logger.info(
            f"ExperienceGraph: summarized ({self._total_leaves} leaves, "
            f"{n_paradigms} paradigm branches, {n_compressed} compressed)"
        )

        self._log_event({
            "event_type": "summarize",
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "n_leaves": self._total_leaves,
            "n_paradigm_branches": n_paradigms,
            "n_compressed": n_compressed,
            "summary_char_length": len(summary),
            "llm_group_time_ms": elapsed_ms,
        })

        self._save_snapshot(iteration=iteration, trigger="summarize")

        return summary

    def save_shutdown(self, iteration: int = 0) -> None:
        """Save final snapshot at end of run."""
        self.save()
        self._save_snapshot(iteration=iteration, trigger="shutdown")

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _placement_hint_text(self, placement_hint: Optional[str]) -> str:
        """Render an optional bias instruction for LLM_place.

        Used by policy-driven callers that intend a solution to open a brand-new
        branch.  Returns an empty string when no hint is given (default).
        """
        if placement_hint == "new_form":
            return (
                "\n\nPLACEMENT INTENT: This solution was generated specifically to introduce a "
                "NEW problem_view (a genuinely different way of framing the problem). Strongly "
                "prefer NEW_BRANCH_UNDER with target_id = ROOT and new_path of 2 entries "
                "(problem_view, solution_strategy). Only fall back to ATTACH_TO if the framing is "
                "truly identical to an existing problem_view."
            )
        if placement_hint == "new_dir":
            return (
                "\n\nPLACEMENT INTENT: This solution was generated specifically to introduce a "
                "NEW solution_strategy under an existing problem_view. Strongly prefer "
                "NEW_BRANCH_UNDER with target_id = the matching problem_view node and new_path of "
                "1 entry (solution_strategy). Only fall back to ATTACH_TO if the strategy is truly "
                "identical to an existing one."
            )
        if placement_hint == "attach":
            return (
                "\n\nPLACEMENT INTENT: This solution was generated by refining or synthesising "
                "existing approaches — it is NOT intended to introduce a new problem framing. "
                "Strongly prefer ATTACH_TO (same problem_view AND solution_strategy as an existing "
                "branch) or SPLIT if the implementation reveals a meaningful sub-strategy distinction "
                "that warrants a new solution_strategy node. "
                "Use NEW_BRANCH_UNDER ONLY if the problem framing is genuinely and completely novel "
                "compared to every existing problem_view in the tree."
            )
        return ""

    async def _llm_place(
        self, rationale: str, tree_text: str, placement_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Call LLM_place to decide where to insert the new solution."""
        is_empty = self._total_leaves == 0

        if is_empty:
            user_content = (
                "## Current Solution Tree\n\n"
                f"{tree_text}\n\n"
                "## New Solution\n\n"
                f"Rationale / changes: {rationale}\n\n"
                "## Task\n\n"
                "The tree is empty. Create the first branch under ROOT using NEW_BRANCH_UNDER.\n"
                "new_path must contain exactly 2 entries:\n"
                "  1. {\"field_name\": \"problem_view\", \"label\": \"...\", \"description\": \"2 sentences\"}\n"
                "  2. {\"field_name\": \"solution_strategy\", \"label\": \"...\", \"description\": \"2 sentences\"}\n"
                "Also include \"leaf_label\" (1-4 words) and \"leaf_description\" (3 sentences: "
                "specific algorithm, key implementation detail, notable constraint/trade-off).\n"
                "Set target_leaf_id, split_field_name, new_label, new_label_description to empty strings."
            )
        else:
            user_content = (
                "## Current Solution Tree\n\n"
                f"{tree_text}\n\n"
                "## New Solution\n\n"
                f"Rationale / changes: {rationale}\n\n"
                "## Task\n\n"
                "Decide where to place this solution. Choose exactly ONE action:\n\n"
                "- ATTACH_TO (target_id): same problem_view AND same solution_strategy as an existing branch.\n"
                "  target_id = the solution_strategy internal node.\n"
                "  Set new_path=[], target_leaf_id='', split_field_name='', new_label='', new_label_description=''.\n\n"
                "- NEW_BRANCH_UNDER (target_id, new_path): diverges at some level.\n"
                "  target_id = last matching node (ROOT if entirely new problem_view).\n"
                "  new_path = list of {field_name, label, description} for levels to CREATE.\n"
                "  If new problem_view: new_path has 2 entries (problem_view, solution_strategy).\n"
                "  If same problem_view but new strategy: target_id = problem_view node, new_path has 1 entry.\n"
                "  Set target_leaf_id='', split_field_name='', new_label='', new_label_description=''.\n\n"
                "- SPLIT (target_leaf_id, split_field_name, new_label, new_label_description): \n"
                "  two leaves reveal a solution_strategy distinction not yet in the tree.\n"
                "  Creates a new solution_strategy node wrapping both leaves.\n"
                "  split_field_name must be \"solution_strategy\".\n"
                "  Set target_id='', new_path=[].\n\n"
                "For ALL actions include:\n"
                "  \"leaf_label\" (1-4 words)\n"
                "  \"leaf_description\" (3 sentences: specific algorithm used | key implementation detail "
                "that distinguishes this from vanilla version of the strategy | notable constraint or trade-off)\n\n"
                "RULES:\n"
                "1. Reuse existing labels whenever the same concept applies. Never create synonymous labels.\n"
                "2. Labels SHORT (1-4 words). Judge by algorithmic idea, NOT surface code similarity.\n"
                "3. Two solutions with the same problem_view + strategy but different implementations → ATTACH_TO."
            )
            user_content += self._placement_hint_text(placement_hint)

        raw_text = ""
        try:
            result = await self.llm_pool.generate(
                system_message=_PLACE_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
                temperature=self.config.place_temperature,
                max_tokens=self.config.place_max_tokens,
                reasoning_effort=None,
            )
            raw_text = result.text or ""
            parsed = _extract_json(raw_text)
            action = parsed.get("action", "")
            if isinstance(action, str):
                parsed["action"] = action.upper()

            # Infer missing action from other fields rather than falling back
            if parsed["action"] not in ("ATTACH_TO", "NEW_BRANCH_UNDER", "SPLIT"):
                if parsed.get("new_path"):
                    parsed["action"] = "NEW_BRANCH_UNDER"
                    logger.warning(
                        f"ExperienceGraph: LLM_place missing/unknown action '{action}', "
                        f"inferred NEW_BRANCH_UNDER from new_path. Raw: {raw_text}"
                    )
                elif parsed.get("target_leaf_id"):
                    parsed["action"] = "SPLIT"
                    logger.warning(
                        f"ExperienceGraph: LLM_place missing/unknown action '{action}', "
                        f"inferred SPLIT from target_leaf_id. Raw: {raw_text}"
                    )
                elif parsed.get("target_id") and parsed["target_id"] != self.root.id:
                    parsed["action"] = "ATTACH_TO"
                    logger.warning(
                        f"ExperienceGraph: LLM_place missing/unknown action '{action}', "
                        f"inferred ATTACH_TO from target_id. Raw: {raw_text}"
                    )

            if parsed["action"] in ("ATTACH_TO", "NEW_BRANCH_UNDER", "SPLIT"):
                return parsed
            logger.warning(
                f"ExperienceGraph: LLM_place could not infer action. Raw: {raw_text}"
            )
        except Exception as e:
            logger.warning(
                f"ExperienceGraph: LLM_place failed ({type(e).__name__}: {e}). "
                f"Raw: {raw_text}"
            )

        logger.warning("ExperienceGraph: LLM_place parse failed, using fallback NEW_BRANCH_UNDER root")
        return {
            "action": "NEW_BRANCH_UNDER",
            "target_id": self.root.id,
            "new_path": [
                {"field_name": "problem_view", "label": "Unknown", "description": ""},
                {"field_name": "solution_strategy", "label": "Unknown", "description": ""},
            ],
            "target_leaf_id": "",
            "split_field_name": "",
            "new_label": "",
            "new_label_description": "",
            "leaf_label": "solution",
            "leaf_description": "",
        }

    async def _llm_group_leaves(
        self, leaves: List[GraphNode], mechanism_label: str
    ) -> List[Dict[str, Any]]:
        """Call LLM_group_leaves to compress leaves under a mechanism node."""
        leaf_lines = "\n".join(
            f"[{leaf.id}] {leaf.label} | score={leaf.score:.4f}"
            if leaf.score is not None
            else f"[{leaf.id}] {leaf.label} | score=N/A"
            for leaf in leaves
        )
        user_content = (
            f"## Solutions under mechanism: {mechanism_label}\n\n"
            f"{leaf_lines}\n\n"
            "## Task\n\n"
            "Group solutions that share the same core implementation approach.\n"
            "- Same idea with minor implementation differences → same group.\n"
            "- Different core ideas → separate groups.\n"
            "- Assign each group a short neutral label (1-4 words).\n"
            "STRICT: Do NOT evaluate quality, rank, or judge potential. Only group and label."
        )

        raw_text = ""
        try:
            result = await self.llm_pool.generate(
                system_message=_GROUP_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
                temperature=self.config.group_temperature,
                max_tokens=self.config.group_max_tokens,
                reasoning_effort=None,
            )
            raw_text = result.text or ""
            parsed = _extract_json(raw_text)
            groups = parsed.get("groups", [])
            if groups and all("label" in g and "leaf_ids" in g for g in groups):
                return groups
        except Exception as e:
            logger.warning(
                f"ExperienceGraph: LLM_group_leaves failed for mechanism "
                f"\"{mechanism_label}\" ({type(e).__name__}: {e}). Raw: {raw_text[:400]}"
            )

        logger.warning(
            f"ExperienceGraph: LLM_group_leaves failed for mechanism \"{mechanism_label}\","
            " using one-group-per-leaf"
        )
        return [{"label": leaf.label, "leaf_ids": [leaf.id]} for leaf in leaves]

    # ── Tree manipulation ─────────────────────────────────────────────────────

    def _apply_decision(
        self,
        decision: Dict[str, Any],
        solution_id: str,
        score: float,
        rationale: str,
        is_paradigm_breakthrough: bool,
    ) -> str:
        """Apply LLM_place decision to the tree. Returns the new leaf's id."""
        action = decision.get("action", "NEW_BRANCH_UNDER")
        leaf_label = decision.get("leaf_label") or solution_id[:12]
        leaf_description = decision.get("leaf_description") or None

        leaf = GraphNode(
            id=str(uuid.uuid4()),
            node_type="leaf",
            label=leaf_label,
            description=leaf_description,
            solution_id=solution_id,
            score=score,
            rationale_ref=rationale[:1500],
            is_paradigm_breakthrough=is_paradigm_breakthrough,
        )

        if action == "ATTACH_TO":
            target_id = decision.get("target_id", "")
            target = find_node(self.root, target_id) if target_id else None
            if target is None:
                logger.warning(
                    f"ExperienceGraph: ATTACH_TO target '{target_id}' not found, "
                    "falling back to NEW_BRANCH_UNDER root"
                )
                target = self.root
                self._ensure_two_level_path(target, leaf)
            else:
                target.children.append(leaf)

        elif action == "NEW_BRANCH_UNDER":
            target_id = decision.get("target_id", self.root.id)
            target = find_node(self.root, target_id) or self.root
            new_path = decision.get("new_path") or []
            if not new_path:
                self._ensure_two_level_path(target, leaf)
            else:
                node = target
                _levels = ["problem_view", "solution_strategy"]
                for i, step in enumerate(new_path):
                    if isinstance(step, dict):
                        fn = step.get("field_name", _levels[min(i, len(_levels) - 1)])
                        lbl = step.get("label", "Unknown") or "Unknown"
                        desc = step.get("description") or None
                    else:
                        fn = _levels[min(i, len(_levels) - 1)]
                        lbl = str(step) if step else "Unknown"
                        desc = None
                    inter = GraphNode(
                        id=str(uuid.uuid4()),
                        node_type="internal",
                        field_name=fn,
                        label=lbl,
                        description=desc,
                    )
                    node.children.append(inter)
                    node = inter
                    self._total_internal += 1
                node.children.append(leaf)

        elif action == "SPLIT":
            target_leaf_id = decision.get("target_leaf_id", "")
            old_leaf = find_node(self.root, target_leaf_id) if target_leaf_id else None
            if old_leaf is None or old_leaf.node_type != "leaf":
                logger.warning(
                    f"ExperienceGraph: SPLIT target leaf '{target_leaf_id}' not found, "
                    "falling back to ATTACH_TO root"
                )
                self._ensure_two_level_path(self.root, leaf)
            else:
                parent = find_parent(self.root, target_leaf_id)
                if parent is None:
                    parent = self.root
                split_fn = decision.get("split_field_name") or "solution_strategy"
                new_label = decision.get("new_label") or "split"
                new_label_description = decision.get("new_label_description") or None
                inter = GraphNode(
                    id=str(uuid.uuid4()),
                    node_type="internal",
                    field_name=split_fn,
                    label=new_label,
                    description=new_label_description,
                )
                parent.children = [c for c in parent.children if c.id != target_leaf_id]
                inter.children = [old_leaf, leaf]
                parent.children.append(inter)
                self._total_internal += 1
        else:
            self._ensure_two_level_path(self.root, leaf)

        self._total_leaves += 1
        return leaf.id

    def _ensure_two_level_path(self, parent: GraphNode, leaf: GraphNode) -> None:
        """Fallback: attach leaf under two Unknown internal nodes."""
        levels = [
            ("problem_view", "Unknown"),
            ("solution_strategy", "Unknown"),
        ]
        node = parent
        for fn, lbl in levels:
            existing = next(
                (c for c in node.children if c.node_type == "internal" and c.label == lbl),
                None,
            )
            if existing:
                node = existing
            else:
                inter = GraphNode(
                    id=str(uuid.uuid4()),
                    node_type="internal",
                    field_name=fn,
                    label=lbl,
                )
                node.children.append(inter)
                node = inter
                self._total_internal += 1
        node.children.append(leaf)

    # ── Summarize internals ───────────────────────────────────────────────────

    async def _render_summary_node(
        self, node: GraphNode, lines: List[str], depth: int
    ) -> int:
        """Recursively render a node. Returns number of compressed mechanism nodes."""
        indent = "   " * depth
        n_compressed = 0

        if node.node_type == "leaf":
            score_str = f"{node.score:.4g}" if node.score is not None else "N/A"
            pb_marker = "  [PARADIGM]" if node.is_paradigm_breakthrough else ""
            lines.append(f"{indent}- {node.label}  {score_str}{pb_marker}")
            return 0

        # Internal node header
        if depth == 0:
            lines.append(f"{indent}▸ [{node.field_name or 'problem_view'}] {node.label}")
        else:
            lines.append(f"{indent}  [{node.field_name or 'solution_strategy'}] {node.label}")

        leaf_children = [c for c in node.children if c.node_type == "leaf"]
        non_leaf_children = [c for c in node.children if c.node_type != "leaf"]

        if (
            node.field_name == "solution_strategy"
            and len(leaf_children) > self.config.compress_threshold
        ):
            # Compress via LLM
            groups = await self._llm_group_leaves(leaf_children, node.label)
            self._render_compressed_groups(groups, leaf_children, lines, depth + 1)
            n_compressed += 1
            for child in non_leaf_children:
                n_compressed += await self._render_summary_node(child, lines, depth + 1)
        else:
            for child in node.children:
                n_compressed += await self._render_summary_node(child, lines, depth + 1)

        return n_compressed

    @staticmethod
    def _render_compressed_groups(
        groups: List[Dict[str, Any]],
        leaves: List[GraphNode],
        lines: List[str],
        depth: int,
    ) -> None:
        """Render compressed leaf groups: label + (N | lo–hi | median)."""
        indent = "   " * depth
        leaf_by_id = {leaf.id: leaf for leaf in leaves}

        for group in groups:
            glabel = group.get("label", "group")
            leaf_ids = group.get("leaf_ids", [])
            group_leaves = [leaf_by_id[lid] for lid in leaf_ids if lid in leaf_by_id]
            scores = sorted(
                leaf.score for leaf in group_leaves if leaf.score is not None
            )
            pb_count = sum(1 for leaf in group_leaves if leaf.is_paradigm_breakthrough)
            pb_marker = f"  [{pb_count} PARADIGM]" if pb_count else ""
            n = len(scores)
            if n == 0:
                lines.append(f"{indent}- {glabel}  (no scores){pb_marker}")
            elif n == 1:
                lines.append(f"{indent}- {glabel}  {scores[0]:.4g}{pb_marker}")
            else:
                lo, hi = scores[0], scores[-1]
                med = statistics.median(scores)
                lines.append(
                    f"{indent}- {glabel}  "
                    f"({n} samples | {lo:.4g}–{hi:.4g} | median {med:.4g}){pb_marker}"
                )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Overwrite experience_graph.json with current tree state."""
        if not self._state_path:
            return
        try:
            data = {
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "total_leaves": self._total_leaves,
                "total_internal": self._total_internal,
                "insert_count": self._insert_count,
                "tree": self.root.to_dict(),
            }
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning(f"ExperienceGraph: save failed: {e}")

    def _save_snapshot(self, iteration: int, trigger: str) -> None:
        """Save a full-tree snapshot for replay/visualization."""
        if not self._snapshots_dir:
            return
        try:
            fname = f"snapshot_{iteration:06d}_{trigger}.json"
            path = os.path.join(self._snapshots_dir, fname)
            data = {
                "version": 1,
                "iteration": iteration,
                "timestamp": datetime.now().isoformat(),
                "total_leaves": self._total_leaves,
                "total_internal": self._total_internal,
                "trigger": trigger,
                "tree": self.root.to_dict(),
            }
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"ExperienceGraph: _save_snapshot failed: {e}")

    def _log_event(self, event: Dict[str, Any]) -> None:
        """Append a JSON event to the events JSONL file."""
        if not self._events_path:
            return
        try:
            with open(self._events_path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.warning(f"ExperienceGraph: _log_event failed: {e}")

    def _try_load(self) -> None:
        """Load tree from checkpoint if it exists. Silently skips on error."""
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path) as f:
                data = json.load(f)
            self.root = GraphNode.from_dict(data["tree"])
            self._total_leaves = data.get("total_leaves", 0)
            self._total_internal = data.get("total_internal", 0)
            self._insert_count = data.get("insert_count", 0)
            logger.info(
                f"ExperienceGraph: loaded tree from checkpoint "
                f"({self._total_leaves} leaves, {self._total_internal} internal nodes)"
            )
        except Exception as e:
            logger.warning(f"ExperienceGraph: failed to load checkpoint ({e}), starting fresh")
            self.root = GraphNode(id=str(uuid.uuid4()), node_type="root", label="ROOT")
            self._total_leaves = 0
            self._total_internal = 0
            self._insert_count = 0
