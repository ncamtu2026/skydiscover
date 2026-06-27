"""AdaGraphDatabase — AdaEvolve's adaptive machinery with the ExperienceGraph as
the population substrate.

The trick that keeps almost all of :class:`AdaEvolveDatabase` reusable: a
``problem_view`` (PV) node maps 1:1 to an adapter *dimension* AND to a slot in
``self.archives``.  So ``island_idx == adapter dimension == PV slot``, and the
inherited sampling (``_sample_from_archive``), UCB stats, archive eviction and
paradigm bookkeeping all work unchanged — we only override how programs are
*routed* into PVs (via ``LLM_place`` on the graph), how PVs are *created*
(dynamically, with a grace period), and the per-iteration PV *selection*
(``end_iteration``: grace first, then UCB).

Two storage layers, by design:
  - per-PV ``UnifiedArchive``  → the live population (sampled from, evicts elite),
  - the ``ExperienceGraph``    → full knowledge memory (every leaf kept, drives
    paradigm summaries + visualization).
Archive eviction never removes a graph leaf.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from typing import Any, Dict, List, Optional, Tuple

from skydiscover.search.adaevolve.adaptation import AdaptiveState, MultiDimensionalAdapter
from skydiscover.search.adaevolve.archive import (
    ArchiveConfig,
    UnifiedArchive,
    create_diversity_strategy,
)
from skydiscover.search.adaevolve.database import AdaEvolveDatabase
from skydiscover.search.base_database import Program

logger = logging.getLogger(__name__)


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class AdaGraphDatabase(AdaEvolveDatabase):
    """AdaEvolve database whose islands are ExperienceGraph problem_view nodes."""

    def __init__(self, name: str, config: Any):
        super().__init__(name, config)

        # Discard AdaEvolve's pre-created fixed islands: PVs are formed on the fly
        # as the graph grows problem_view branches.  Keep everything else super
        # set up (config knobs, paradigm_tracker, _diversity_strategy_type, caches).
        self.archives = []
        self.adapter = MultiDimensionalAdapter(decay=self.decay)
        self.num_islands = 0
        self.current_island = 0
        self.island_config_names = []
        # Keep an empty list (not None) so inherited helpers that fall back to
        # ``for island in self.islands`` when ``self.archives`` is still empty
        # (e.g. log_status before the graph is seeded) are safe no-ops.
        self.islands = []

        # PV <-> dimension bookkeeping.  Adapter dimensions are append-only, so a
        # "dropped" PV keeps its dim/archive but leaves ``active_pvs`` (excluded
        # from selection / P_form / sampling).
        self.dim_pv: List[str] = []          # dimension index -> pv_id
        self.pv_dim: Dict[str, int] = {}     # pv_id -> dimension index
        self.pv_grace: Dict[str, int] = {}   # pv_id -> remaining grace iterations
        self.active_pvs: List[str] = []      # currently-live problem_views
        self.pv_grace_period = int(getattr(config, "pv_grace_period", 5))
        self.n_init_pv = int(getattr(config, "num_islands", 2))
        self.max_pv = int(getattr(config, "max_islands", 5))

        # v2 knobs
        self.pform_tau = float(getattr(config, "pform_tau", 0.3))
        self.pform_lambda = float(getattr(config, "pform_lambda", 8.0))
        self.pv_dead_ratio = float(getattr(config, "pv_dead_ratio", 0.1))
        self.pv_dedup_accept_prob = float(getattr(config, "pv_dedup_accept_prob", 0.1))
        self.insight_top_k = int(getattr(config, "insight_top_k", 5))

        # PV memory: every framing ever tried (live + dropped) for dedup / revive.
        # pv_id -> {label, description, best_score, status, dim}
        self.pv_memory: Dict[str, Dict[str, Any]] = {}
        # Distillation: solution_strategy node id -> list[{iter, dnorm, what}]
        self.insights: Dict[str, List[Dict[str, Any]]] = {}
        self._rng = random.Random()

        # Attached by the controller (needs an LLM pool + output_dir to build).
        self.experience_graph = None

    # ------------------------------------------------------------------
    # Runtime wiring
    # ------------------------------------------------------------------
    def attach_experience_graph(self, experience_graph: Any) -> None:
        self.experience_graph = experience_graph

    # ------------------------------------------------------------------
    # PV slot management (one slot == one adapter dimension == one archive)
    # ------------------------------------------------------------------
    def _make_archive_config(self, preset: Optional[Dict[str, Any]]) -> ArchiveConfig:
        cfg = self.config
        higher_is_better = getattr(cfg, "higher_is_better", {}) or {}
        common = dict(
            max_size=getattr(cfg, "population_size", 20),
            k_neighbors=getattr(cfg, "k_neighbors", 5),
            higher_is_better=higher_is_better,
            pareto_objectives=getattr(cfg, "pareto_objectives", []) or [],
            pareto_objectives_weight=getattr(cfg, "pareto_objectives_weight", 0.0),
            fitness_key=getattr(cfg, "fitness_key", None),
        )
        if preset:
            return ArchiveConfig(
                elite_ratio=preset["elite_ratio"],
                pareto_weight=preset["pareto_weight"],
                fitness_weight=preset["fitness_weight"],
                novelty_weight=preset["novelty_weight"],
                **common,
            )
        return ArchiveConfig(
            elite_ratio=getattr(cfg, "archive_elite_ratio", 0.2),
            pareto_weight=getattr(cfg, "pareto_weight", 0.4),
            fitness_weight=getattr(cfg, "fitness_weight", 0.3),
            novelty_weight=getattr(cfg, "novelty_weight", 0.3),
            **common,
        )

    def _create_pv_slot(self, pv_id: str, preset: Optional[Dict[str, Any]] = None) -> int:
        higher_is_better = getattr(self.config, "higher_is_better", {}) or {}
        diversity = create_diversity_strategy(
            self._diversity_strategy_type, higher_is_better=higher_is_better
        )
        idx = self.num_islands
        self.archives.append(
            UnifiedArchive(config=self._make_archive_config(preset), diversity_strategy=diversity)
        )
        self.adapter.add_dimension(
            AdaptiveState(
                decay=self.decay,
                intensity_min=self.intensity_min,
                intensity_max=self.intensity_max,
            )
        )
        self.dim_pv.append(pv_id)
        self.pv_dim[pv_id] = idx
        self.island_config_names.append((preset or {}).get("name", "balanced"))
        self.num_islands += 1
        logger.info(
            f"AdaGraph: created PV slot {idx} (pv_id={pv_id[:8]}, "
            f"preset={(preset or {}).get('name', 'balanced')}); active PVs="
            f"{len(self.active_pvs) + 1}"
        )
        return idx

    def ensure_pv_slot(
        self, pv_id: str, preset: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, bool]:
        """Return (dimension_index, created_new) for ``pv_id``, creating a slot
        (with a grace period) the first time we see it."""
        if pv_id in self.pv_dim:
            if pv_id not in self.active_pvs:  # revived
                self.active_pvs.append(pv_id)
            return self.pv_dim[pv_id], False
        idx = self._create_pv_slot(pv_id, preset)
        self.active_pvs.append(pv_id)
        self.pv_grace[pv_id] = self.pv_grace_period
        self.pv_memory[pv_id] = {
            "label": (self._pv_label(pv_id) or pv_id[:8]),
            "best_score": float("-inf"),
            "status": "live",
            "dim": idx,
        }
        return idx, True

    # ------------------------------------------------------------------
    # PV quality / health (global-normalised decayed reward R_k / V_k)
    # ------------------------------------------------------------------
    def _pv_quality(self, pv_id: str) -> float:
        idx = self.pv_dim.get(pv_id)
        if idx is None:
            return 0.0
        v = self.adapter.decayed_visits[idx] if idx < len(self.adapter.decayed_visits) else 0.0
        r = self.adapter.dimension_rewards[idx] if idx < len(self.adapter.dimension_rewards) else 0.0
        return (r / v) if v > 0 else 0.0

    def _pv_label(self, pv_id: str) -> Optional[str]:
        if self.experience_graph is None:
            return None
        from skydiscover.experience_graph.nodes import find_node
        node = find_node(self.experience_graph.root, pv_id)
        return node.label if node else None

    def _global_best_pv(self) -> Optional[str]:
        if self.best_program_id:
            return self._pv_of_solution(self.best_program_id)
        return None

    def droppable_pvs(self) -> List[str]:
        """Active PVs that are past grace and do not hold the global best."""
        best_pv = self._global_best_pv()
        return [
            pv for pv in self.active_pvs
            if self.pv_grace.get(pv, 0) == 0 and pv != best_pv
        ]

    def compute_p_form(self) -> float:
        """Probability that a paradigm event opens a NEW problem_view.

        s = health of the most-droppable slot relative to the best PV.  A free
        slot counts as s=0 (maximally open); a fleet whose weakest droppable PV is
        still healthy gives s→1 (P_form→0).
        """
        if not self.active_pvs:
            return 1.0
        qmax = max((self._pv_quality(pv) for pv in self.active_pvs), default=0.0)
        if len(self.active_pvs) < self.max_pv:
            s = 0.0  # free slot → easy to open, no drop needed
        else:
            drop = self.droppable_pvs()
            if not drop:
                return 0.0  # nobody can be dropped → cannot open
            qweak = min(self._pv_quality(pv) for pv in drop)
            s = qweak / (qmax + 1e-9)
        return _sigmoid(self.pform_lambda * (self.pform_tau - s))

    def sample_target_pvs(self, n: int) -> List[str]:
        """Sample up to n distinct active PVs by UCB score (R/V + exploration)."""
        if not self.active_pvs:
            return []
        total = max(sum(self.adapter.dimension_visits) or 0, 1)
        scores: Dict[str, float] = {}
        for pv in self.active_pvs:
            idx = self.pv_dim[pv]
            nk = self.adapter.dimension_visits[idx] or 1
            q = self._pv_quality(pv)
            scores[pv] = q + self.adapter.ucb_exploration * math.sqrt(math.log(total + 1) / nk)
        chosen: List[str] = []
        pool = dict(scores)
        for _ in range(min(n, len(pool))):
            # softmax-ish weighted pick
            items = list(pool.items())
            weights = [max(v, 1e-6) for _, v in items]
            pick = self._rng.choices([k for k, _ in items], weights=weights, k=1)[0]
            chosen.append(pick)
            del pool[pick]
        return chosen

    def drop_weakest_pv(self) -> Optional[str]:
        """Deactivate the weakest droppable PV; returns its id (memory kept)."""
        drop = self.droppable_pvs()
        if not drop:
            return None
        victim = min(drop, key=self._pv_quality)
        self.active_pvs.remove(victim)
        if victim in self.pv_memory:
            self.pv_memory[victim]["status"] = "dropped"
        logger.info(f"AdaGraph: dropped PV {victim[:8]} (q={self._pv_quality(victim):.4g}); active={len(self.active_pvs)}")
        return victim

    # ------------------------------------------------------------------
    # Dedup memory + insight text
    # ------------------------------------------------------------------
    def pv_info(self, pv_id: str) -> Dict[str, str]:
        from skydiscover.experience_graph.nodes import find_node
        n = find_node(self.experience_graph.root, pv_id) if self.experience_graph else None
        return {"label": (n.label if n else ""), "description": (n.description or "" if n else "")}

    def direction_labels(self, pv_id: str) -> List[Dict[str, str]]:
        """Existing solution_strategy nodes (directions) under a PV."""
        from skydiscover.experience_graph.nodes import find_node
        pv = find_node(self.experience_graph.root, pv_id) if self.experience_graph else None
        if pv is None:
            return []
        return [
            {"label": c.label, "description": c.description or ""}
            for c in pv.children
            if c.node_type == "internal"
        ]

    def best_in_pv(self, pv_id: str) -> Optional[Program]:
        idx = self.pv_dim.get(pv_id)
        if idx is None or idx >= len(self.archives):
            return None
        return self.archives[idx].get_best()

    def tried_framings(self) -> List[Dict[str, str]]:
        """Label+description of all framings ever tried (for dedup judging)."""
        out: List[Dict[str, str]] = []
        from skydiscover.experience_graph.nodes import find_node
        for pv_id, meta in self.pv_memory.items():
            node = find_node(self.experience_graph.root, pv_id) if self.experience_graph else None
            out.append({
                "pv_id": pv_id,
                "label": (node.label if node else meta.get("label", "")) or "",
                "description": (node.description if node and node.description else "") or "",
                "status": meta.get("status", "live"),
            })
        return out

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _leaf_in_subtree(node: Any, solution_id: str) -> bool:
        stack = [node]
        while stack:
            n = stack.pop()
            if n.node_type == "leaf" and n.solution_id == solution_id:
                return True
            stack.extend(n.children)
        return False

    def _pv_of_solution(self, solution_id: str) -> Optional[str]:
        """The problem_view ancestor id of the leaf carrying ``solution_id``."""
        graph = self.experience_graph
        if graph is None or graph.root is None:
            return None
        for pv in graph.root.children:
            if pv.node_type != "internal":
                continue
            if self._leaf_in_subtree(pv, solution_id):
                return pv.id
        return None

    # ------------------------------------------------------------------
    # Framework-facing add (Runner seeds the initial program through this)
    # ------------------------------------------------------------------
    def add(
        self,
        program: Program,
        iteration: Optional[int] = None,
        parent_id: Optional[str] = None,
        target_island: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Register a program without PV routing.

        ``Runner._add_initial_program`` calls this to seed the very first program
        *before* any problem_view exists.  AdaGraph routes real programs into PVs
        via :meth:`place_and_add` (the ExperienceGraph decides placement), so here
        we only store the program and update best-tracking; ``_seed_graph`` later
        inserts it into the graph (creating PV #0) and its archive.
        """
        if iteration is not None:
            program.iteration_found = iteration
            self.last_iteration = max(self.last_iteration, iteration)
        self.programs[program.id] = program
        self._invalidate_global_pareto_cache()
        self._update_best_program(program)
        if self.config.db_path:
            self._save_program(program)
        return program.id

    # ------------------------------------------------------------------
    # Placement + add (graph decides the PV; archive + adapter follow)
    # ------------------------------------------------------------------
    async def place_and_add(
        self,
        program: Program,
        rationale: str,
        placement_hint: Optional[str],
        iteration: int,
        parent_id: Optional[str] = None,
        is_migration: bool = False,
        preset: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], int, bool]:
        """Insert into the graph (LLM_place picks the PV), then add to that PV's
        archive + adapter dimension.  Returns (pv_id, dim_idx, created_new_pv)."""
        score = self.get_program_proxy_score(program)
        # Exploit / migration children MUST stay in their parent's problem_view:
        # attach deterministically under the parent's solution_strategy node (no
        # LLM_place call — which would otherwise freely re-frame the child and both
        # mis-route migrations and blow past the PV cap).  Only spawn ("new_form")
        # and the empty-graph seed (None) go through LLM_place, which may open a PV.
        deterministic = placement_hint == "attach" and parent_id is not None
        try:
            if deterministic:
                await self.experience_graph.attach_under_parent(
                    parent_solution_id=parent_id,
                    solution_id=program.id,
                    score=score,
                    rationale=rationale or "",
                    leaf_label=(program.metadata or {}).get("changes", "solution"),
                    iteration=iteration,
                    parent_id=parent_id,
                    extra={"is_migration": is_migration},
                )
            else:
                await self.experience_graph.insert(
                    solution_id=program.id,
                    score=score,
                    rationale=rationale or "",
                    iteration=iteration,
                    parent_id=parent_id,
                    placement_hint=placement_hint,
                    extra={"is_migration": is_migration},
                )
        except Exception as e:  # pragma: no cover - graph failures shouldn't kill the run
            logger.warning(f"AdaGraph: graph insert failed: {e}")

        pv_id = self._pv_of_solution(program.id)
        if pv_id is None:
            # Graph didn't resolve a PV; fall back to the current PV (or a fresh one).
            pv_id = self.dim_pv[self.current_island] if self.dim_pv else f"pv-{uuid.uuid4()}"

        idx, created = self.ensure_pv_slot(pv_id, preset)
        self._add_to_slot(program, idx, iteration, parent_id, is_migration)
        return pv_id, idx, created

    def _add_to_slot(
        self,
        program: Program,
        idx: int,
        iteration: Optional[int],
        parent_id: Optional[str],
        is_migration: bool,
    ) -> None:
        """Mirror of :meth:`AdaEvolveDatabase.add` body, routed to PV slot ``idx``."""
        if iteration is not None:
            program.iteration_found = iteration
            self.last_iteration = max(self.last_iteration, iteration)

        was_added = self.archives[idx].add(program)
        # Keep the program in the flat store regardless of archive eviction so the
        # graph leaf's solution_id always resolves (graph = full memory).
        self.programs[program.id] = program

        if not was_added:
            logger.debug(
                f"AdaGraph: archive {idx} rejected {program.id[:8]} "
                f"(fitness={self._get_fitness(program):.4f})"
            )
            return

        fitness = self._get_fitness(program)
        if not is_migration:
            self.adapter.record_evaluation(idx, fitness)
        else:
            self.adapter.receive_external_improvement(idx, fitness)

        self._invalidate_global_pareto_cache()
        global_improved = self._update_best_program(program)
        if self.paradigm_tracker is not None and not is_migration:
            self.paradigm_tracker.record_improvement(global_improved, self._global_best_score)

        # PV memory best + distilled "what changed" (globally-normalised).
        pv_id = self.dim_pv[idx] if idx < len(self.dim_pv) else None
        if pv_id and pv_id in self.pv_memory:
            self.pv_memory[pv_id]["best_score"] = max(self.pv_memory[pv_id]["best_score"], fitness)
        if not is_migration:
            self._capture_insight(program, parent_id, fitness)

        if self.config.db_path:
            self._save_program(program)

    # ------------------------------------------------------------------
    # Deterministic placement: new direction (SS) / new framing (PV)
    # ------------------------------------------------------------------
    def place_direction(
        self,
        program: Program,
        target_pv_id: str,
        ss_label: str,
        rationale: str,
        iteration: int,
        parent_id: Optional[str] = None,
        ss_description: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Create a NEW solution_strategy under ``target_pv_id`` and place the leaf
        there (deterministic — never leaks into another PV)."""
        score = self.get_program_proxy_score(program)
        ok = self.experience_graph.create_direction(
            problem_view_id=target_pv_id,
            solution_id=program.id,
            score=score,
            rationale=rationale or "",
            ss_label=ss_label or "New Direction",
            ss_description=ss_description,
            leaf_label=(program.metadata or {}).get("changes", "direction"),
            iteration=iteration,
            parent_id=parent_id,
            extra={"adagraph_direction": True},
        )
        if not ok:
            target_pv_id = self.dim_pv[self.current_island]
        idx, _ = self.ensure_pv_slot(target_pv_id)
        self._add_to_slot(program, idx, iteration, parent_id, False)
        return target_pv_id, idx

    def place_form(
        self,
        program: Program,
        pv_label: str,
        ss_label: str,
        rationale: str,
        iteration: int,
        parent_id: Optional[str] = None,
        pv_description: Optional[str] = None,
        preset: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int]:
        """Open a NEW problem_view (dropping the weakest PV first if at cap).

        If at cap and nothing can be dropped (all PVs still in grace / hold the
        global best), fall back to opening a direction under the strongest PV so
        the work is not wasted and the cap is never exceeded.
        """
        if len(self.active_pvs) >= self.max_pv:
            if self.drop_weakest_pv() is None:
                target = max(self.active_pvs, key=self._pv_quality) if self.active_pvs else None
                if target is not None:
                    return self.place_direction(
                        program, target, ss_label or pv_label, rationale, iteration, parent_id
                    )
        score = self.get_program_proxy_score(program)
        pv_id = self.experience_graph.create_problem_view(
            pv_label=pv_label or "New Framing",
            solution_id=program.id,
            score=score,
            rationale=rationale or "",
            ss_label=ss_label or "Initial Direction",
            pv_description=pv_description,
            leaf_label=(program.metadata or {}).get("changes", "framing"),
            iteration=iteration,
            parent_id=parent_id,
            extra={"adagraph_form": True},
        )
        idx, _ = self.ensure_pv_slot(pv_id, preset)
        self._add_to_slot(program, idx, iteration, parent_id, False)
        return pv_id, idx

    # ------------------------------------------------------------------
    # Distillation
    # ------------------------------------------------------------------
    def _capture_insight(self, child: Program, parent_id: Optional[str], child_fitness: float) -> None:
        if not parent_id:
            return
        parent = self.programs.get(parent_id)
        if parent is None:
            return
        delta = child_fitness - self.get_program_proxy_score(parent)
        if delta <= 0:
            return
        denom = max(abs(self._global_best_score), 1e-9)
        dnorm = delta / denom  # global-normalised (avoids poor-direction bias)
        ss = self.experience_graph._solution_strategy_of(child.id) if self.experience_graph else None
        if ss is None:
            return
        lst = self.insights.setdefault(ss.id, [])
        lst.append({
            "iter": child.iteration_found,
            "dnorm": round(dnorm, 6),
            "what": (child.metadata or {}).get("changes", "")[:200],
        })
        lst.sort(key=lambda d: d["dnorm"], reverse=True)
        del lst[self.insight_top_k:]

    def _ss_ids_under_pv(self, pv_id: str) -> List[str]:
        from skydiscover.experience_graph.nodes import find_node
        pv = find_node(self.experience_graph.root, pv_id) if self.experience_graph else None
        if pv is None:
            return []
        return [c.id for c in pv.children if c.node_type == "internal"]

    def _format_insights(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        entries = sorted(entries, key=lambda d: d["dnorm"], reverse=True)[: self.insight_top_k]
        lines = ["## What has improved solutions so far (highest-impact first)"]
        for e in entries:
            lines.append(f"  - (+{e['dnorm']:.4f}) {e['what']}")
        return "\n".join(lines)

    def insight_text_for_pv(self, pv_id: str) -> str:
        entries: List[Dict[str, Any]] = []
        for ss_id in self._ss_ids_under_pv(pv_id):
            entries.extend(self.insights.get(ss_id, []))
        return self._format_insights(entries)

    def insight_text_global(self) -> str:
        entries: List[Dict[str, Any]] = []
        for lst in self.insights.values():
            entries.extend(lst)
        return self._format_insights(entries)

    # ------------------------------------------------------------------
    # Per-iteration PV selection (grace first, then UCB) over ACTIVE PVs
    # ------------------------------------------------------------------
    def end_iteration(self, iteration: int) -> None:
        self._iteration_count = iteration
        self.last_iteration = max(self.last_iteration, iteration)
        if not self.active_pvs:
            return

        # Spend one grace tick on the PV we just used.
        if 0 <= self.current_island < len(self.dim_pv):
            cur_pv = self.dim_pv[self.current_island]
            if self.pv_grace.get(cur_pv, 0) > 0:
                self.pv_grace[cur_pv] -= 1

        # Active PVs still under grace are force-selected before UCB resumes.
        grace = [pv for pv in self.active_pvs if self.pv_grace.get(pv, 0) > 0]
        if grace:
            self.current_island = self.pv_dim[min(grace, key=lambda p: self.pv_dim[p])]
        elif self.use_ucb_selection:
            self.current_island = self.pv_dim[self._select_active_pv_ucb(iteration)]
        else:
            cur = self.dim_pv[self.current_island] if self.current_island < len(self.dim_pv) else self.active_pvs[0]
            order = self.active_pvs
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
            self.current_island = self.pv_dim[nxt]

    def _select_active_pv_ucb(self, iteration: int) -> str:
        """UCB (R_k/V_k + exploration) restricted to active PVs; cold ones first."""
        cold = [
            pv for pv in self.active_pvs
            if self.adapter.dimension_visits[self.pv_dim[pv]] < self.adapter.min_visits
        ]
        if cold:
            return self._rng.choice(cold)
        total = max(sum(self.adapter.dimension_visits) or 0, 1)
        best_pv, best = self.active_pvs[0], float("-inf")
        for pv in self.active_pvs:
            idx = self.pv_dim[pv]
            nk = self.adapter.dimension_visits[idx] or 1
            ucb = self._pv_quality(pv) + self.adapter.ucb_exploration * math.sqrt(
                math.log(total + 1) / nk
            )
            if ucb > best:
                best, best_pv = ucb, pv
        return best_pv

    # ------------------------------------------------------------------
    # Siblings: search across all PV archives (parent may not be in current PV)
    # ------------------------------------------------------------------
    def get_children(self, parent_id: str, limit: int = 5) -> List[Program]:
        children: List[Program] = []
        for archive in self.archives:
            if hasattr(archive, "get_children"):
                children.extend(archive.get_children(parent_id))
        children.sort(key=lambda p: getattr(p, "iteration_found", 0))
        return children[-limit:]
