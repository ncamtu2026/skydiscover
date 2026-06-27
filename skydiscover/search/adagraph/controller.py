"""AdaGraphController — AdaEvolveController whose population substrate is the
ExperienceGraph.

It reuses AdaEvolve's whole generation pipeline (sampling per PV, retry, paradigm,
``_execute_generation``, logging) and only changes the parts that the graph
substrate touches:

  - ``run_discovery``      seed the graph (PV #0) + bootstrap to ``n_init`` PVs.
  - ``_run_iteration``     generative migration → generative spawn → paradigm →
                           normal step → place child into its graph-decided PV.
  - ``_spawn_pv``          generative spawn: a cheap reframe call opens a new PV.
  - ``_migrate_generative``star-from-best tech-transfer between PVs.

The graph lives on the database (``self.database.experience_graph``); the
controller holds the same reference for paradigm summaries.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Optional, Tuple

from skydiscover.context_builder.adagraph import AdaGraphContextBuilder
from skydiscover.search.adaevolve.controller import AdaEvolveController
from skydiscover.search.base_database import Program
from skydiscover.search.default_discovery_controller import DiscoveryControllerInput

logger = logging.getLogger(__name__)


class AdaGraphController(AdaEvolveController):
    def __init__(self, controller_input: DiscoveryControllerInput):
        super().__init__(controller_input)

        # Swap in the AdaGraph context builder (adds the reframe/spawn prompt).
        self.context_builder = AdaGraphContextBuilder(self.config)

        # The ExperienceGraph IS the population — ensure one exists and hand it to
        # the database.  AdaEvolveController already builds self.experience_graph
        # when use_experience_graph=True (always true for AdaGraph config).
        if self.experience_graph is None:
            from skydiscover.experience_graph.experience_graph import ExperienceGraph
            from skydiscover.llm.llm_pool import LLMPool

            eg_pool = LLMPool(self.config.llm.experience_graph_models)
            self.experience_graph = ExperienceGraph(
                config=self.config.experience_graph,
                llm_pool=eg_pool,
                output_dir=self.output_dir,
            )
        self.database.attach_experience_graph(self.experience_graph)

        db_cfg = self.config.search.database
        self.n_init_pv = int(getattr(db_cfg, "num_islands", 2))
        self.migration_interval = int(getattr(db_cfg, "migration_interval", 15))
        self.use_migration = bool(getattr(db_cfg, "use_migration", True))
        self._rng = random.Random()

        logger.info(
            f"AdaGraphController initialized (n_init_pv={self.n_init_pv}, "
            f"max_pv={getattr(db_cfg, 'max_islands', 5)}, "
            f"migration_interval={self.migration_interval})"
        )

    # AdaEvolve seeds copies into every island; AdaGraph seeds the graph instead.
    def _ensure_all_islands_seeded(self) -> None:
        return

    # ====================================================================
    # Main loop
    # ====================================================================
    async def run_discovery(
        self,
        start_iteration: int,
        max_iterations: int,
        checkpoint_callback=None,
    ) -> Optional[Program]:
        total = start_iteration + max_iterations
        logger.info(f"AdaGraph: running {max_iterations} iterations")
        self._setup_iteration_stats_logging()

        await self._seed_graph(max(start_iteration - 1, 0))
        await self._bootstrap_pvs(max(start_iteration - 1, 0))

        for iteration in range(start_iteration, total):
            if self.shutdown_event.is_set():
                logger.info("Shutdown requested")
                break
            try:
                await self._run_iteration(iteration, checkpoint_callback)
            except Exception as e:
                logger.exception(f"Iteration {iteration} failed: {e}")
            finally:
                self.database.end_iteration(iteration)

        logger.info("AdaGraph completed")
        self.database.log_status()
        try:
            self.experience_graph.save_shutdown(iteration=total)
        except Exception as e:
            logger.warning(f"ExperienceGraph shutdown save failed: {e}")
        return self.database.get_best_program()

    async def _seed_graph(self, iteration: int) -> None:
        """Insert pre-loaded seed program(s) into the empty graph → first PV(s)."""
        if getattr(self.experience_graph, "_total_leaves", 0) > 0:
            return
        seeds = list(self.database.programs.values())
        if not seeds:
            logger.warning("AdaGraph: no seed program found to insert into the graph")
            return
        for seed in seeds:
            rationale = (seed.metadata or {}).get("changes") or "Initial seed program"
            try:
                await self.database.place_and_add(
                    seed,
                    rationale=rationale,
                    placement_hint=None,
                    iteration=iteration,
                    parent_id=seed.parent_id,
                )
            except Exception as e:
                logger.warning(f"AdaGraph: seed graph insert failed: {e}")
        if self.database.num_islands > 0:
            self.database.current_island = 0

    async def _bootstrap_pvs(self, iteration: int) -> None:
        """Open up to ``n_init`` initial framings via generative spawn.

        Bounded by ``attempts`` so a run can't loop forever if LLM_place keeps
        attaching the reframe instead of opening a new problem_view.
        """
        attempts = 0
        max_attempts = 2 * max(self.n_init_pv, 1)
        while (
            self.database.num_islands < self.n_init_pv
            and self.database.num_islands < self.database.max_islands
            and attempts < max_attempts
        ):
            attempts += 1
            await self._spawn_pv(iteration, bootstrap=True)

    async def _run_iteration(self, iteration: int, checkpoint_callback) -> None:
        iter_start = time.time()

        # Generative tech-transfer migration (periodic, star-from-best).
        if (
            self.use_migration
            and iteration > 0
            and self.migration_interval > 0
            and iteration % self.migration_interval == 0
        ):
            try:
                await self._migrate_generative(iteration)
            except Exception as e:
                logger.warning(f"AdaGraph migration failed: {e}")

        # On GLOBAL stall, generate a paradigm batch and annotate each idea as
        # form-level (new PV, prob P_form) or direction-level (new SS in a sampled PV).
        if self.database.use_paradigm_breakthrough and self.database.is_paradigm_stagnating():
            try:
                await self._generate_and_annotate_paradigms(iteration)
            except Exception as e:
                logger.warning(f"AdaGraph paradigm generation failed: {e}")

        # Each iteration does EITHER a paradigm child (form/direction) OR a normal
        # exploit child (within its parent's PV).  No generative spawn.
        child: Optional[Program] = None
        result = None
        if self.database.use_paradigm_breakthrough and self.database.has_active_paradigm():
            child, result = await self._apply_paradigm(iteration)
        else:
            result = await self._run_normal_step(iteration)
            if result is not None and not result.error:
                child = Program(**result.child_program_dict)
                await self.database.place_and_add(
                    child,
                    rationale=self._graph_rationale(child),
                    placement_hint="attach",
                    iteration=iteration,
                    parent_id=result.parent_id,
                    is_migration=False,
                )

        iter_time = time.time() - iter_start
        if child is None or result is None or result.error:
            err = result.error if result is not None else "no child produced"
            logger.warning(f"Iteration {iteration}: {err}")
            self._log_iteration_stats(
                iteration=iteration,
                child_program=None,
                iteration_time=iter_time,
                llm_generation_time=(result.llm_generation_time if result else 0.0),
                eval_time=(result.eval_time if result else 0.0),
                error=err,
            )
            return

        self._finish_iteration(child, result, iteration, checkpoint_callback)

    def _finish_iteration(self, child, result, iteration, checkpoint_callback) -> None:
        if self.monitor_callback:
            try:
                self.monitor_callback(child, iteration)
            except Exception:
                logger.debug("Monitor callback error", exc_info=True)
        if result.prompt:
            self.database.log_prompt(
                template_key=(
                    "diff_user_message"
                    if self.config.diff_based_generation
                    else "full_rewrite_user_message"
                ),
                program_id=child.id,
                prompt=result.prompt,
                responses=[result.llm_response] if result.llm_response else [],
            )
        if iteration > 0 and iteration % self.config.checkpoint_interval == 0:
            self.database.log_status()
            if checkpoint_callback:
                checkpoint_callback(iteration)
        self._log_iteration_stats(
            iteration=iteration,
            child_program=result.child_program_dict,
            iteration_time=result.iteration_time,
            llm_generation_time=result.llm_generation_time,
            eval_time=result.eval_time,
            error=None,
        )

    # ====================================================================
    # Paradigm: batch annotation (form vs direction + PV sampling)
    # ====================================================================
    async def _generate_and_annotate_paradigms(self, iteration: int) -> None:
        await self._generate_paradigms_if_needed()  # inherited: LLM ideate + set_paradigms
        tracker = self.database.paradigm_tracker
        if tracker is None or not tracker.active_paradigms:
            return
        batch = tracker.active_paradigms
        if any("_ag_mode" in p for p in batch):
            return  # already annotated this batch

        p_form = self.database.compute_p_form()
        make_form = self._rng.random() < p_form  # ≤1 form per batch (slow PV churn)
        targets = self.database.sample_target_pvs(len(batch))
        for i, p in enumerate(batch):
            if i == 0 and make_form:
                p["_ag_mode"] = "form"
            else:
                p["_ag_mode"] = "direction"
                p["_ag_target_pv"] = targets[i] if i < len(targets) else (
                    targets[0] if targets else None
                )
        logger.info(
            f"AdaGraph paradigm batch: P_form={p_form:.2f}, make_form={make_form}, "
            f"{sum(1 for p in batch if p['_ag_mode']=='form')} form / "
            f"{sum(1 for p in batch if p['_ag_mode']=='direction')} direction"
        )

    async def _apply_paradigm(self, iteration: int) -> Tuple[Optional[Program], object]:
        paradigm = self.database.get_current_paradigm()
        if paradigm is None:
            return None, None
        if paradigm.get("_ag_mode") == "form":
            return await self._paradigm_form(iteration, paradigm)
        return await self._paradigm_direction(iteration, paradigm)

    async def _paradigm_form(self, iteration: int, paradigm: dict):
        """Open a new framing (with dedup vs tried framings + drop weakest)."""
        best = self.database.get_best_program()
        if best is None:
            return None, None
        try:
            summary = await self.experience_graph.summarize(iteration=iteration)
        except Exception:
            summary = ""
        insights = self.database.insight_text_global()
        prompt = self.context_builder.build_form_prompt(
            explored_map=summary, seed=best, paradigm=paradigm, insights=insights
        )
        result = await self._execute_generation(best, prompt, iteration, paradigm=paradigm)
        self.database.use_paradigm()
        if result.error or not result.child_program_dict:
            return None, result
        child = Program(**result.child_program_dict)
        child.metadata = {**(child.metadata or {}), "changes": "paradigm-form",
                          "paradigm_idea": paradigm.get("idea", "")}
        label = (paradigm.get("idea") or "New Framing")[:48]

        accept, matched_pv = await self._dedup_accept(label, paradigm)
        if accept:
            self.database.place_form(
                child, pv_label=label, ss_label="Initial Direction",
                rationale=self._graph_rationale(child), iteration=iteration,
                parent_id=best.id, pv_description=paradigm.get("description"),
            )
        else:
            # Rejected as a rediscovery → keep the work as a direction under the
            # matched (or best active) PV instead of opening a duplicate framing.
            target = matched_pv if matched_pv in self.database.active_pvs else (
                self.database.active_pvs[0] if self.database.active_pvs else None
            )
            if target is None:  # nothing to attach to → allow it as a PV after all
                self.database.place_form(
                    child, pv_label=label, ss_label="Initial Direction",
                    rationale=self._graph_rationale(child), iteration=iteration, parent_id=best.id,
                )
            else:
                child.metadata["changes"] = "paradigm-form→redirected-direction"
                self.database.place_direction(
                    child, target_pv_id=target, ss_label=label,
                    rationale=self._graph_rationale(child), iteration=iteration,
                    parent_id=best.id, ss_description=paradigm.get("description"),
                )
        return child, result

    async def _paradigm_direction(self, iteration: int, paradigm: dict):
        """Open a new, mechanistically-distinct solution_strategy inside a PV."""
        target = paradigm.get("_ag_target_pv")
        if target not in self.database.active_pvs:
            sampled = self.database.sample_target_pvs(1)
            target = sampled[0] if sampled else None
        if target is None:
            self.database.use_paradigm()
            return None, None
        pv_info = self.database.pv_info(target)
        siblings = self.database.direction_labels(target)
        parent = self.database.best_in_pv(target) or self.database.get_best_program()
        insights = self.database.insight_text_for_pv(target)
        prompt = self.context_builder.build_direction_prompt(
            pv_info=pv_info, sibling_directions=siblings, seed=parent,
            paradigm=paradigm, insights=insights,
        )
        result = await self._execute_generation(parent, prompt, iteration, paradigm=paradigm)
        self.database.use_paradigm()
        if result.error or not result.child_program_dict:
            return None, result
        child = Program(**result.child_program_dict)
        child.metadata = {**(child.metadata or {}), "changes": "paradigm-direction",
                          "paradigm_idea": paradigm.get("idea", "")}
        label = (paradigm.get("idea") or "New Direction")[:48]
        self.database.place_direction(
            child, target_pv_id=target, ss_label=label,
            rationale=self._graph_rationale(child), iteration=iteration,
            parent_id=(parent.id if parent else None),
            ss_description=paradigm.get("description"),
        )
        return child, result

    async def _dedup_accept(self, label: str, paradigm: dict) -> Tuple[bool, Optional[str]]:
        """LLM-judge whether the framing duplicates a tried one; if so accept only
        with ``pv_dedup_accept_prob``.  Returns (accept, matched_pv_id)."""
        framings = self.database.tried_framings()
        if not framings:
            return True, None
        desc = paradigm.get("description") or paradigm.get("idea", "")
        listing = "\n".join(
            f'[{f["pv_id"][:8]}] {f["label"]}: {f["description"][:140]}' for f in framings
        )
        user = (
            f"New problem framing:\n{label} — {desc}\n\n"
            f"Framings already tried:\n{listing}\n\n"
            "Is the NEW framing essentially the SAME core problem model as one of the "
            'tried ones? Respond JSON: {"duplicate": true|false, "match_id": "<8-char id or empty>"}'
        )
        try:
            res = await self.guide_llms.generate(
                "You judge whether two problem framings reduce to the same model. JSON only.",
                [{"role": "user", "content": user}], temperature=0.0,
            )
            m = re.search(r"\{[^{}]*\}", res.text or "")
            if m:
                v = json.loads(m.group(0))
                if v.get("duplicate"):
                    matched = None
                    mid = (v.get("match_id") or "").strip()
                    for f in framings:
                        if mid and f["pv_id"].startswith(mid):
                            matched = f["pv_id"]
                            break
                    accept = self._rng.random() < self.database.pv_dedup_accept_prob
                    logger.info(f"AdaGraph dedup: '{label}' ~ duplicate → accept={accept}")
                    return accept, matched
        except Exception as e:
            logger.debug(f"dedup judge failed, accepting: {e}")
        return True, None

    # ====================================================================
    # Bootstrap PV creation (reuses the form prompt, no paradigm)
    # ====================================================================
    async def _spawn_pv(self, iteration: int, bootstrap: bool = False) -> bool:
        best = self.database.get_best_program()
        if best is None:
            return False
        try:
            summary = await self.experience_graph.summarize(iteration=iteration)
        except Exception:
            summary = ""
        insights = self.database.insight_text_global()
        prompt = self.context_builder.build_form_prompt(
            explored_map=summary, seed=best, paradigm=None, insights=insights
        )
        result = await self._execute_generation(best, prompt, iteration)
        if result.error or not result.child_program_dict:
            logger.warning(f"AdaGraph bootstrap framing failed: {result.error}")
            return False
        child = Program(**result.child_program_dict)
        child.metadata = {**(child.metadata or {}), "changes": "bootstrap (new framing)"}
        label = self._docstring_label(child.solution) or f"Framing {len(self.database.active_pvs) + 1}"
        self.database.place_form(
            child, pv_label=label, ss_label="Initial Direction",
            rationale=self._graph_rationale(child), iteration=iteration, parent_id=best.id,
        )
        logger.info(f"AdaGraph: bootstrap framing → active PVs={len(self.database.active_pvs)}")
        return True

    # ====================================================================
    # Generative migration (tech-transfer, star-from-best over ACTIVE PVs)
    # ====================================================================
    async def _migrate_generative(self, iteration: int) -> None:
        immigrant = self.database.get_best_program()
        if immigrant is None:
            return
        immigrant_pv = self.database._pv_of_solution(immigrant.id)
        budget = int(getattr(self.database, "migration_count", 5))
        produced = 0

        for pv_id in list(self.database.active_pvs):
            if produced >= budget:
                break
            if pv_id == immigrant_pv:
                continue
            native = self.database.best_in_pv(pv_id)
            if native is None:
                continue
            context = {
                "program_metrics": native.metrics,
                "other_context_programs": {"": [immigrant]},
                "siblings": [],
                "error_context": None,
                "paradigm": None,
            }
            prompt = self.context_builder.build_prompt({"": native}, context)
            result = await self._execute_generation(native, prompt, iteration)
            if result.error or not result.child_program_dict:
                continue
            child = Program(**result.child_program_dict)
            child.metadata = {**(child.metadata or {}), "changes": "migration (tech-transfer)",
                              "migrated_from": immigrant_pv, "migrated_to": pv_id}
            await self.database.place_and_add(
                child, rationale=self._graph_rationale(child), placement_hint="attach",
                iteration=iteration, parent_id=native.id, is_migration=True,
            )
            produced += 1
        if produced:
            logger.info(f"AdaGraph: generative migration produced {produced} transfer(s)")

    # ====================================================================
    # Helpers
    # ====================================================================
    @staticmethod
    def _graph_rationale(child: Program) -> str:
        md = child.metadata or {}
        changes = md.get("changes", "")
        idea = md.get("paradigm_idea")
        if idea:
            return f"{changes} [PARADIGM: {idea}]"
        return changes or "solution"

    @staticmethod
    def _docstring_label(solution: Optional[str]) -> Optional[str]:
        """Short framing label from the first docstring line of the solution."""
        if not solution:
            return None
        m = re.search(r'"""\s*(.+)', solution)
        if m:
            line = m.group(1).strip().rstrip(".")
            return line[:48] if line else None
        return None
