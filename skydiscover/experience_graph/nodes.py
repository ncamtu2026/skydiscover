from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GraphNode:
    """A node in the ExperienceGraph tree.

    Three layers of internal nodes (paradigm → formulation → mechanism)
    sit between the root and leaf nodes.  Leaves represent individual
    evaluated solutions.
    """

    id: str
    node_type: str            # "root" | "internal" | "leaf"
    label: str                # short LLM-generated label (1-4 words)
    description: Optional[str] = None  # description shown in tooltip
    field_name: Optional[str] = None   # "problem_view"|"solution_strategy" for internal
    children: List["GraphNode"] = field(default_factory=list)

    # Leaf-only fields
    solution_id: Optional[str] = None
    score: Optional[float] = None
    rationale_ref: Optional[str] = None        # truncated rationale for reference
    is_paradigm_breakthrough: bool = False

    # ── Serialization ──────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "node_type": self.node_type,
            "label": self.label,
            "description": self.description,
            "field_name": self.field_name,
            "children": [c.to_dict() for c in self.children],
            "solution_id": self.solution_id,
            "score": self.score,
            "rationale_ref": self.rationale_ref,
            "is_paradigm_breakthrough": self.is_paradigm_breakthrough,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GraphNode":
        node = cls(
            id=d["id"],
            node_type=d["node_type"],
            label=d["label"],
            description=d.get("description"),
            field_name=d.get("field_name"),
            solution_id=d.get("solution_id"),
            score=d.get("score"),
            rationale_ref=d.get("rationale_ref"),
            is_paradigm_breakthrough=d.get("is_paradigm_breakthrough", False),
        )
        node.children = [cls.from_dict(c) for c in d.get("children", [])]
        return node


# ── Tree helpers ────────────────────────────────────────────────────────────


def find_node(root: GraphNode, node_id: str) -> Optional[GraphNode]:
    """DFS search by id."""
    if root.id == node_id:
        return root
    for child in root.children:
        result = find_node(child, node_id)
        if result is not None:
            return result
    return None


def find_parent(root: GraphNode, target_id: str) -> Optional[GraphNode]:
    """DFS to find the parent of the node with target_id."""
    for child in root.children:
        if child.id == target_id:
            return root
        result = find_parent(child, target_id)
        if result is not None:
            return result
    return None


def render_for_insert(node: GraphNode, depth: int = 0) -> str:
    """Render the tree as indented text with node ids, for LLM_place prompt."""
    indent = "  " * depth
    pb_marker = " [PARADIGM]" if node.is_paradigm_breakthrough else ""

    if node.node_type == "root":
        line = f"[{node.id}] ROOT"
    elif node.node_type == "leaf":
        score_str = f"{node.score:.4f}" if node.score is not None else "N/A"
        desc_snippet = f" | {node.description[:80]}" if node.description else ""
        line = f"{indent}[{node.id}] (leaf) {node.label} | score={score_str}{pb_marker}{desc_snippet}"
    else:
        fn_tag = f"({node.field_name}) " if node.field_name else ""
        line = f"{indent}[{node.id}] {fn_tag}{node.label}"

    parts = [line]
    for child in node.children:
        parts.append(render_for_insert(child, depth + 1))
    return "\n".join(parts)


def count_nodes(root: GraphNode) -> tuple[int, int]:
    """Return (n_leaves, n_internal) counts for the whole tree."""
    leaves = 0
    internal = 0
    if root.node_type == "leaf":
        leaves = 1
    elif root.node_type == "internal":
        internal = 1
    for child in root.children:
        cl, ci = count_nodes(child)
        leaves += cl
        internal += ci
    return leaves, internal


def get_placement_path(root: GraphNode, leaf_id: str) -> List[str]:
    """Return [paradigm_label, formulation_label, mechanism_label] leading to leaf_id."""
    def _dfs(node: GraphNode, path: List[str]) -> Optional[List[str]]:
        if node.node_type == "leaf" and node.id == leaf_id:
            return path
        for child in node.children:
            new_path = path + ([child.label] if child.node_type == "internal" else [])
            result = _dfs(child, new_path)
            if result is not None:
                return result
        return None

    return _dfs(root, []) or []
