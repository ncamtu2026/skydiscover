"""GraphEvolve policy — the multi-tier decision layer over the ExperienceGraph.

This module is intentionally *pure*: it depends only on ``math``/``random`` and
plain data structures, never on the graph or the LLM.  That keeps every policy
rule unit-testable in isolation.  The controller/database feed it
:class:`DirectionStats` (built from the graph leaves) and read/write the
:class:`PolicyState` sidecar.

Tiers (see analysis/architecture_analysis/advance_graph_evolve.md):
  Tier 1   choose_action      circuit-breaker (sigmoid) + 2-arm bandit
  Tier 2a  choose_direction   UCB1-Normal over solution_strategy directions
           sample_powerlaw    power-law parent / context sampling within a direction
  Tier 2b  sample_quality_subset  quality-weighted candidate sampling for crossover
  Tier 2c  choose_space_target    2-arm bandit (new problem_view vs new solution_strategy)

Conventions:
  - Score statistics (mu/var/best) are derived on the fly from the leaves under a
    direction, so they stay correct when the graph is restructured (SPLIT).
  - Only the bandit weights and per-direction pull counts are persisted state.
  - A direction with ``pull_count == 0`` is "cold": UCB = +inf, so it is always
    tried at least once (natural cold-start, no optimistic init needed).
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

# Action types (Tier 1)
EXPLOIT = "exploit"
CROSSOVER = "crossover"
SPACE_EXPLORE = "space_explore"

# Space-explore targets (Tier 2c)
NEW_FORM = "new_form"  # new problem_view (a different framing)
NEW_DIR = "new_dir"    # new solution_strategy under the global-best problem_view


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class DirectionStats:
    """A read-only view of one ``solution_strategy`` direction.

    ``scores`` are the proxy scores of the leaves currently under the node and
    ``leaf_ids`` their solution ids (parallel lists).  All summary statistics are
    derived from ``scores`` so they survive graph restructuring.
    """

    node_id: str
    scores: List[float] = field(default_factory=list)
    leaf_ids: List[str] = field(default_factory=list)

    @property
    def n_leaves(self) -> int:
        return len(self.scores)

    @property
    def mu(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def var(self) -> float:
        if len(self.scores) < 2:
            return 0.0
        return statistics.pvariance(self.scores)

    @property
    def best(self) -> float:
        return max(self.scores) if self.scores else float("-inf")


@dataclass
class PolicyState:
    """Persistent sidecar state for the policy (serialised next to the graph)."""

    # Tier 1 — action bandit (w_crossover is the fixed anchor)
    w_exploit: float = 1.0
    w_crossover: float = 1.0
    # Tier 2c — space-explore bandit (w_new_dir is the fixed anchor)
    w_new_form: float = 1.0
    w_new_dir: float = 1.0
    # Tier 2a — per-direction pull counts, keyed by node_id
    pull_count: Dict[str, int] = field(default_factory=dict)
    # Tier 1 — circuit breaker (global stagnation signal)
    G_global: float = 0.0
    best_global: float = float("-inf")
    # iteration clock used by UCB
    t: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "w_exploit": self.w_exploit,
            "w_crossover": self.w_crossover,
            "w_new_form": self.w_new_form,
            "w_new_dir": self.w_new_dir,
            "pull_count": dict(self.pull_count),
            "G_global": self.G_global,
            "best_global": self.best_global,
            "t": self.t,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PolicyState":
        state = cls()
        for key in ("w_exploit", "w_crossover", "w_new_form", "w_new_dir", "G_global", "t"):
            if key in d and d[key] is not None:
                setattr(state, key, d[key])
        if d.get("best_global") is not None:
            state.best_global = float(d["best_global"])
        if isinstance(d.get("pull_count"), dict):
            state.pull_count = {k: int(v) for k, v in d["pull_count"].items()}
        return state


class GraphEvolvePolicy:
    """Pure decision logic; mutates only the supplied :class:`PolicyState`."""

    def __init__(
        self,
        config: Any,
        state: Optional[PolicyState] = None,
        rng: Optional[random.Random] = None,
    ):
        self.cfg = config
        self.state = state or PolicyState()
        self.rng = rng or random.Random()

    # -- config helpers ---------------------------------------------------
    def _c(self, name: str, default: float) -> float:
        return getattr(self.cfg, name, default)

    # ====================================================================
    # Tier 1 — action selection
    # ====================================================================
    def p_space(self) -> float:
        """Soft circuit breaker: rises as the global stagnation signal falls."""
        lam = self._c("sigmoid_lambda", 100.0)
        tau = self._c("tau_stag", 0.01)
        return _sigmoid(lam * (tau - self.state.G_global))

    def choose_action(self, has_directions: bool) -> str:
        if not has_directions:
            return EXPLOIT
        if self.rng.random() < self.p_space():
            return SPACE_EXPLORE
        total = self.state.w_exploit + self.state.w_crossover
        p_exploit = self.state.w_exploit / total if total > 0 else 0.5
        return EXPLOIT if self.rng.random() < p_exploit else CROSSOVER

    # ====================================================================
    # Tier 2a — direction (UCB1-Normal) + power-law parent / context
    # ====================================================================
    def choose_direction(self, directions: Sequence[DirectionStats]) -> Optional[str]:
        if not directions:
            return None
        cold = [d for d in directions if self.state.pull_count.get(d.node_id, 0) == 0]
        if cold:
            return self.rng.choice(cold).node_id

        t = max(self.state.t, 2)
        ln = math.log(t - 1) if t > 2 else math.log(2 - 1 + 1e-9)
        c = self._c("ucb_c", 1.0)

        def ucb(d: DirectionStats) -> float:
            n = self.state.pull_count.get(d.node_id, 1) or 1
            normal_term = math.sqrt(16.0 * max(d.var, 0.0) * ln / n)
            # small classic-UCB floor keeps exploration alive when variance is 0
            floor = c * math.sqrt(ln / n)
            return d.mu + normal_term + floor

        return max(directions, key=ucb).node_id

    def sample_powerlaw(
        self,
        scores: Sequence[float],
        exclude: Optional[Set[int]] = None,
        alpha: Optional[float] = None,
    ) -> Optional[int]:
        """Return an index sampled by rank-based power law (rank 1 = best score).

        alpha=0 -> uniform; alpha -> inf -> always the best.  Returns ``None`` if
        no eligible index remains.
        """
        exclude = exclude or set()
        idx = [i for i in range(len(scores)) if i not in exclude]
        if not idx:
            return None
        if len(idx) == 1:
            return idx[0]
        a = alpha if alpha is not None else self._c("powerlaw_alpha", 1.0)
        ranked = sorted(idx, key=lambda i: scores[i], reverse=True)
        weights = [(rank ** (-a)) for rank in range(1, len(ranked) + 1)]
        return self._weighted_choice(ranked, weights)

    def sample_context(
        self,
        scores: Sequence[float],
        m: int,
        exclude: Optional[Set[int]] = None,
    ) -> List[int]:
        """Sample up to ``m`` distinct indices by power law (without replacement)."""
        chosen: List[int] = []
        used: Set[int] = set(exclude or set())
        for _ in range(m):
            i = self.sample_powerlaw(scores, exclude=used)
            if i is None:
                break
            chosen.append(i)
            used.add(i)
        return chosen

    # ====================================================================
    # Tier 2b — quality-weighted candidate sampling for crossover
    # ====================================================================
    def sample_quality_subset(
        self,
        scores: Sequence[float],
        k: int,
        exclude: Optional[Set[int]] = None,
    ) -> List[int]:
        """Quality-weighted sample of up to ``k`` distinct indices (no embedding).

        Diversity is *not* enforced here — the LLM-verify loop in the controller
        is the sole arbiter of genuine mechanistic diversity.  This only biases
        sampling toward higher-quality directions while staying stochastic.
        """
        return self.sample_context(scores, k, exclude=exclude)

    # ====================================================================
    # Tier 2c — space-explore target bandit
    # ====================================================================
    def choose_space_target(self) -> str:
        total = self.state.w_new_form + self.state.w_new_dir
        p_form = self.state.w_new_form / total if total > 0 else 0.5
        return NEW_FORM if self.rng.random() < p_form else NEW_DIR

    # ====================================================================
    # Updates
    # ====================================================================
    def _bandit_update(self, w: float, improved: bool) -> float:
        alpha = self._c("bandit_alpha", 0.5)
        beta = self._c("bandit_beta", 0.5)
        w_max = self._c("w_max", 10.0)
        if improved:
            w = w + alpha
        else:
            w = max(1.0, beta * w)
        return min(w, w_max)

    def update_action_reward(self, action: str, improved: bool) -> None:
        """Update the Tier-1 bandit. Only the dynamic exploit arm changes;
        crossover is the fixed anchor (w_crossover = 1.0)."""
        if action == EXPLOIT:
            self.state.w_exploit = self._bandit_update(self.state.w_exploit, improved)

    def update_space_reward(self, target: str, improved: bool) -> None:
        """Update the Tier-2c bandit. Only the dynamic new_form arm changes;
        new_dir is the fixed anchor (w_new_dir = 1.0)."""
        if target == NEW_FORM:
            self.state.w_new_form = self._bandit_update(self.state.w_new_form, improved)

    def record_direction_pull(self, node_id: Optional[str]) -> None:
        if node_id:
            self.state.pull_count[node_id] = self.state.pull_count.get(node_id, 0) + 1

    def update_global(self, score: Optional[float]) -> None:
        """Update the global stagnation EMA and best-so-far from a new score."""
        if score is None:
            return
        rho = self._c("decay_rho", 0.9)
        if self.state.best_global == float("-inf"):
            self.state.best_global = score
            return
        denom = max(abs(self.state.best_global), 1e-9)
        delta = max((score - self.state.best_global) / denom, 0.0)
        self.state.G_global = rho * self.state.G_global + (1.0 - rho) * (delta * delta)
        if score > self.state.best_global:
            self.state.best_global = score

    def tick(self) -> None:
        self.state.t += 1

    # -- internal ---------------------------------------------------------
    def _weighted_choice(self, items: Sequence[int], weights: Sequence[float]) -> int:
        total = sum(weights)
        if total <= 0:
            return self.rng.choice(list(items))
        r = self.rng.random() * total
        upto = 0.0
        for item, w in zip(items, weights):
            upto += w
            if r <= upto:
                return item
        return items[-1]
