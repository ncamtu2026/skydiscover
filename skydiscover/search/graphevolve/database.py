"""GraphEvolveDatabase — a flat program store backed by an ExperienceGraph.

There are **no islands**: the ExperienceGraph *is* the population structure and
this database is a thin store plus a set of read helpers the policy uses
(listing ``solution_strategy`` directions, the leaves under them, the global-best
``problem_view``, etc.).  The :class:`PolicyState` sidecar lives here and is
persisted next to the graph.  All scoring goes through
:func:`compute_proxy_score` so leaf scores and derived direction statistics share
one unit.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from skydiscover.config import DatabaseConfig
from skydiscover.experience_graph.nodes import GraphNode
from skydiscover.search.base_database import Program, ProgramDatabase
from skydiscover.search.graphevolve.policy import DirectionStats, PolicyState
from skydiscover.utils.metrics import compute_proxy_score

logger = logging.getLogger(__name__)

_POLICY_STATE_FILENAME = "graphevolve_policy.json"


class GraphEvolveDatabase(ProgramDatabase):
    """Flat program store + ExperienceGraph view helpers + PolicyState."""

    def __init__(self, name: str, config: DatabaseConfig, **kwargs: Any):
        super().__init__(name, config, **kwargs)

        # Metric direction (reused by compute_proxy_score, same as AdaEvolve).
        self.higher_is_better: Dict[str, bool] = getattr(config, "higher_is_better", {}) or {}
        self.fitness_key: Optional[str] = getattr(config, "fitness_key", None)
        self.pareto_objectives: List[str] = getattr(config, "pareto_objectives", []) or []

        # Attached by the controller (needs output_dir + an LLM pool to build).
        self.experience_graph = None
        self.policy_state: PolicyState = PolicyState()
        self._policy_state_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Runtime wiring (called by the controller)
    # ------------------------------------------------------------------
    def attach_experience_graph(self, experience_graph: Any, output_dir: Optional[str]) -> None:
        """Attach the controller-owned ExperienceGraph and load policy state."""
        self.experience_graph = experience_graph
        if output_dir:
            self._policy_state_path = os.path.join(output_dir, _POLICY_STATE_FILENAME)
            self._load_policy_state()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------
    def add(self, program: Program, iteration: Optional[int] = None, **kwargs: Any) -> str:
        """Store a program and update best tracking. Graph insertion is async and
        is performed by the controller after evaluation."""
        self.programs[program.id] = program
        if iteration is not None:
            self.last_iteration = iteration
        self._update_best_program(program)
        return program.id

    def sample(
        self,
        num_context_programs: Optional[int] = 4,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Program], Dict[str, List[Program]]]:
        """Thin default to satisfy the interface — the real selection lives in the
        policy, driven by the controller.  Returns the best program as parent."""
        best = self.get_best_program()
        parent_dict: Dict[str, Program] = {"": best} if best else {}
        return parent_dict, {"": []}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def proxy_score(self, program: Optional[Program]) -> float:
        if program is None or not program.metrics:
            return float("-inf")
        return compute_proxy_score(
            program.metrics,
            fitness_key=self.fitness_key,
            pareto_objectives=self.pareto_objectives,
            higher_is_better=self.higher_is_better,
        )

    # ------------------------------------------------------------------
    # Graph read helpers
    # ------------------------------------------------------------------
    def _root(self) -> Optional[GraphNode]:
        return getattr(self.experience_graph, "root", None) if self.experience_graph else None

    def list_direction_nodes(self) -> List[GraphNode]:
        """All ``solution_strategy`` internal nodes (the UCB arms)."""
        root = self._root()
        if root is None:
            return []
        out: List[GraphNode] = []

        def _dfs(node: GraphNode) -> None:
            if node.node_type == "internal" and node.field_name == "solution_strategy":
                out.append(node)
            for child in node.children:
                _dfs(child)

        _dfs(root)
        return out

    def list_problem_view_nodes(self) -> List[GraphNode]:
        root = self._root()
        if root is None:
            return []
        return [c for c in root.children if c.node_type == "internal"]

    @staticmethod
    def leaves_under(node: GraphNode) -> List[GraphNode]:
        out: List[GraphNode] = []

        def _dfs(n: GraphNode) -> None:
            if n.node_type == "leaf":
                out.append(n)
            for child in n.children:
                _dfs(child)

        _dfs(node)
        return out

    def representative_leaf(self, node: GraphNode) -> Optional[GraphNode]:
        leaves = [lf for lf in self.leaves_under(node) if lf.score is not None]
        if not leaves:
            return None
        return max(leaves, key=lambda lf: lf.score)

    def program_of(self, leaf: Optional[GraphNode]) -> Optional[Program]:
        if leaf is None or not leaf.solution_id:
            return None
        return self.programs.get(leaf.solution_id)

    def build_direction_stats(self) -> List[DirectionStats]:
        """A :class:`DirectionStats` per direction, scores derived from leaves."""
        stats: List[DirectionStats] = []
        for node in self.list_direction_nodes():
            scores: List[float] = []
            leaf_ids: List[str] = []
            for leaf in self.leaves_under(node):
                if leaf.score is None or not leaf.solution_id:
                    continue
                scores.append(float(leaf.score))
                leaf_ids.append(leaf.solution_id)
            if scores:
                stats.append(DirectionStats(node_id=node.id, scores=scores, leaf_ids=leaf_ids))
        return stats

    def direction_node(self, node_id: str) -> Optional[GraphNode]:
        for node in self.list_direction_nodes():
            if node.id == node_id:
                return node
        return None

    def problem_view_of_direction(self, ss_node_id: str) -> Optional[GraphNode]:
        """Return the ``problem_view`` parent of a ``solution_strategy`` node.

        The tree is exactly problem_view -> solution_strategy -> leaf, so a
        direction node is always a direct child of a problem_view node.
        """
        for pv in self.list_problem_view_nodes():
            for child in pv.children:
                if child.id == ss_node_id:
                    return pv
        return None

    def global_best_problem_view(self) -> Optional[GraphNode]:
        """Return the ``problem_view`` node that contains the global-best leaf."""
        root = self._root()
        if root is None:
            return None
        best_pv: Optional[GraphNode] = None
        best_score = float("-inf")
        for pv in self.list_problem_view_nodes():
            for leaf in self.leaves_under(pv):
                if leaf.score is not None and leaf.score > best_score:
                    best_score = leaf.score
                    best_pv = pv
        return best_pv

    # -- placement verification (Tier 2c) --------------------------------
    def problem_view_ids(self) -> Set[str]:
        return {n.id for n in self.list_problem_view_nodes()}

    def solution_strategy_ids(self) -> Set[str]:
        return {n.id for n in self.list_direction_nodes()}

    def _leaf_ancestors(self, solution_id: str) -> Tuple[Optional[GraphNode], Optional[GraphNode]]:
        """Return (problem_view_node, solution_strategy_node) above the leaf whose
        ``solution_id`` matches (the graph leaf id is a separate uuid)."""
        root = self._root()
        if root is None:
            return None, None

        def _dfs(node: GraphNode, pv: Optional[GraphNode], ss: Optional[GraphNode]):
            if node.node_type == "leaf" and node.solution_id == solution_id:
                return pv, ss
            for child in node.children:
                npv, nss = pv, ss
                if child.node_type == "internal":
                    if child.field_name == "problem_view":
                        npv, nss = child, None
                    elif child.field_name == "solution_strategy":
                        nss = child
                res = _dfs(child, npv, nss)
                if res is not None:
                    return res
            return None

        return _dfs(root, None, None) or (None, None)

    def verify_space_placement(
        self,
        leaf_id: str,
        pre_problem_view_ids: Set[str],
        pre_solution_strategy_ids: Set[str],
    ) -> Tuple[bool, bool]:
        """Did this insert create a genuinely new branch?

        Returns ``(created_new_form, created_new_dir)`` by comparing the leaf's
        ancestors against the sets of node ids captured *before* the insert.
        """
        pv, ss = self._leaf_ancestors(leaf_id)
        created_new_form = bool(pv is not None and pv.id not in pre_problem_view_ids)
        created_new_dir = bool(
            not created_new_form and ss is not None and ss.id not in pre_solution_strategy_ids
        )
        return created_new_form, created_new_dir

    # ------------------------------------------------------------------
    # PolicyState persistence
    # ------------------------------------------------------------------
    def save_policy_state(self) -> None:
        if not self._policy_state_path:
            return
        try:
            tmp = self._policy_state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.policy_state.to_dict(), f, indent=2)
            os.replace(tmp, self._policy_state_path)
        except Exception as e:
            logger.warning(f"Failed to save GraphEvolve policy state: {e}")

    def _load_policy_state(self) -> None:
        if not self._policy_state_path or not os.path.exists(self._policy_state_path):
            return
        try:
            with open(self._policy_state_path) as f:
                self.policy_state = PolicyState.from_dict(json.load(f))
            logger.info(f"Loaded GraphEvolve policy state from {self._policy_state_path}")
        except Exception as e:
            logger.warning(f"Failed to load GraphEvolve policy state: {e}")
