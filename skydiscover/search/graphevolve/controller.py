"""GraphEvolveController — policy-driven evolution loop over an ExperienceGraph.

No islands.  Each iteration the policy picks an action (exploit / crossover /
space-explore), the controller assembles the matching prompt, generates a
full-rewrite child, evaluates it, inserts it into the graph, and feeds the
outcome back into the policy.  The ExperienceGraph is the population; the flat
program store and the :class:`PolicyState` sidecar live on the database.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from skydiscover.context_builder.graphevolve import GraphEvolveContextBuilder
from skydiscover.llm.llm_pool import LLMPool
from skydiscover.search.base_database import Program
from skydiscover.search.default_discovery_controller import (
    DiscoveryController,
    DiscoveryControllerInput,
)
from skydiscover.search.graphevolve.policy import (
    CROSSOVER,
    EXPLOIT,
    NEW_FORM,
    SPACE_EXPLORE,
    GraphEvolvePolicy,
)
from skydiscover.utils.code_utils import (
    apply_diff,
    extract_diffs,
    extract_evolve_block,
    merge_evolve_block,
    parse_full_rewrite,
)

logger = logging.getLogger(__name__)

_VERIFY_SYSTEM = (
    "You judge whether code solutions use genuinely different CORE algorithmic "
    "mechanisms (not just surface code differences). Respond ONLY with a JSON object."
)


class GraphEvolveController(DiscoveryController):
    def __init__(self, controller_input: DiscoveryControllerInput):
        # Default streaming ON for all GraphEvolve LLM pools (generation, guide,
        # ExperienceGraph) so progress is visible live for every benchmark
        # without per-config edits.  Must run before super().__init__ builds the
        # pools.  Only fills models that left ``stream`` unset (None); an explicit
        # True/False in the config is preserved.
        llm_cfg = controller_input.config.llm
        if bool(getattr(controller_input.config.search.database, "stream_output", True)):
            for pool in (
                llm_cfg.models,
                llm_cfg.guide_models,
                llm_cfg.experience_graph_models,
            ):
                for m in pool:
                    if getattr(m, "stream", None) is None:
                        m.stream = True

        super().__init__(controller_input)

        db_config = self.config.search.database
        self.enable_retry = getattr(db_config, "enable_error_retry", True)
        self.max_retries = getattr(db_config, "max_error_retries", 2)

        # Hyperparameters
        self.bootstrap_k = int(getattr(db_config, "bootstrap_k", 5))
        # Reasoning-mode overrides applied to the generation call during bootstrap.
        self.bootstrap_thinking = getattr(db_config, "bootstrap_thinking", None)
        self.bootstrap_thinking_budget = getattr(db_config, "bootstrap_thinking_budget", None)
        self.bootstrap_reasoning_effort = getattr(db_config, "bootstrap_reasoning_effort", None)
        self.crossover_set_size = int(getattr(db_config, "crossover_set_size", 5))
        self.crossover_max_attempts = int(getattr(db_config, "crossover_max_attempts", 8))
        self.context_solutions_m = int(getattr(db_config, "context_solutions_m", 2))
        self.previous_attempts_n = int(getattr(db_config, "previous_attempts_n", 5))

        # ExperienceGraph: the population. Owned here, attached to the database.
        from skydiscover.experience_graph.experience_graph import ExperienceGraph

        eg_llm_pool = LLMPool(self.config.llm.experience_graph_models)
        self.experience_graph = ExperienceGraph(
            config=self.config.experience_graph,
            llm_pool=eg_llm_pool,
            output_dir=self.output_dir,
        )
        self.database.attach_experience_graph(self.experience_graph, self.output_dir)

        # Policy reads/writes the database's PolicyState sidecar.
        self.policy = GraphEvolvePolicy(db_config, self.database.policy_state)

        # Fresh run: start "non-stagnant" so the circuit breaker keeps space-explore
        # off until improvement genuinely stalls.  Resumed runs keep their saved signal.
        if self.policy.state.t == 0 and self.policy.state.G_global == 0.0:
            self.policy.state.G_global = float(getattr(db_config, "initial_g_global", 1.0))

        # Optional features (config-gated)
        self.use_idea_stage = bool(getattr(db_config, "use_idea_stage", False))
        self.diversity_mode = str(getattr(db_config, "diversity_mode", "llm"))
        self.exploit_sampling = str(getattr(db_config, "exploit_sampling", "local"))
        self.analyze_graph = bool(getattr(db_config, "analyze_graph", False))
        self.force_attach_existing = bool(getattr(db_config, "force_attach_existing", True))

        # Code-generation scope (see GraphEvolveDatabaseConfig).
        self.evolve_block_only = bool(getattr(db_config, "evolve_block_only", True))
        self.exploit_diff_based = bool(getattr(db_config, "exploit_diff_based", True))

        self._completed = 0  # successful generations (for bootstrap gating)
        self._iteration_stats_log_path: Optional[str] = None

        logger.info(
            f"GraphEvolveController initialized (bootstrap_k={self.bootstrap_k}, "
            f"crossover_set_size={self.crossover_set_size})"
        )

    def _init_context_builder(self) -> None:
        self.context_builder = GraphEvolveContextBuilder(self.config)

    async def _call_llm(self, system_message: str, user_message: str, **kwargs):
        """Echo every prompt to stdout before dispatching (debug visibility)."""
        import sys

        sys.stdout.write(
            "\n========== LLM PROMPT ==========\n"
            f"[SYSTEM]\n{system_message or '(none)'}\n"
            f"[USER]\n{user_message or '(none)'}\n"
            "========== END PROMPT ==========\n"
        )
        sys.stdout.flush()
        return await super()._call_llm(system_message, user_message, **kwargs)

    # ====================================================================
    # Iteration stats logging (mirrors AdaEvolve's adaevolve_iteration_stats)
    # ====================================================================
    def _setup_iteration_stats_logging(self) -> None:
        out = self.output_dir or "."
        os.makedirs(out, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._iteration_stats_log_path = os.path.join(
            out, f"graphevolve_iteration_stats_{ts}.jsonl"
        )
        logger.info(f"GraphEvolve iteration stats → {self._iteration_stats_log_path}")

    def _log_iteration_stats(
        self,
        iteration: int,
        plan: Optional[Dict[str, Any]],
        child: Optional["Program"],
        iteration_time: float,
        gen_extra: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        if not self._iteration_stats_log_path:
            return
        action = (plan or {}).get("action", "unknown")
        ps = self.policy.state
        entry: Dict[str, Any] = {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "direction_node_id": (plan or {}).get("direction_node_id"),
            "direction_label": (plan or {}).get("direction_label", ""),
            "space_target": (plan or {}).get("target"),
            "parent_id": (plan or {}).get("parent_id"),
            "parent_score": (plan or {}).get("parent_score"),
            "child_id": child.id if child else None,
            "child_score": self.database.proxy_score(child) if child else None,
            "child_metrics": child.metrics if child else None,
            "policy": {
                "p_space": self.policy.p_space(),
                "w_exploit": ps.w_exploit,
                "w_crossover": ps.w_crossover,
                "w_new_form": ps.w_new_form,
                "w_new_dir": ps.w_new_dir,
                "G_global": ps.G_global,
                "best_global": ps.best_global,
                "t": ps.t,
            },
            "iteration_result": {
                "success": error is None,
                "error": error,
                "iteration_time_seconds": round(iteration_time, 3),
                "llm_generation_time_seconds": round(gen_extra.get("llm_time", 0.0), 3),
                "eval_time_seconds": round(gen_extra.get("eval_time", 0.0), 3),
            },
        }
        try:
            with open(self._iteration_stats_log_path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write iteration stats: {e}")

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
        logger.info(f"GraphEvolve: running {max_iterations} iterations")
        self._setup_iteration_stats_logging()

        await self._ensure_seed_in_graph(iteration=max(start_iteration - 1, 0))

        for iteration in range(start_iteration, total):
            if self.shutdown_event.is_set():
                logger.info("Shutdown requested")
                break
            try:
                await self._run_iteration(iteration, checkpoint_callback)
            except Exception as e:
                logger.exception(f"Iteration {iteration} failed: {e}")

        logger.info("GraphEvolve completed")
        self.database.log_status()
        try:
            self.experience_graph.save_shutdown(iteration=total)
        except Exception as e:
            logger.warning(f"ExperienceGraph shutdown save failed: {e}")
        self.database.save_policy_state()
        return self.database.get_best_program()

    async def _ensure_seed_in_graph(self, iteration: int) -> None:
        """Insert any pre-existing programs (the seed) into the empty graph."""
        if getattr(self.experience_graph, "_total_leaves", 0) > 0:
            return
        for prog in list(self.database.programs.values()):
            score = self.database.proxy_score(prog)
            rationale = (prog.metadata or {}).get("changes") or "Initial seed program"
            try:
                await self.experience_graph.insert(
                    solution_id=prog.id,
                    score=score,
                    rationale=rationale,
                    iteration=iteration,
                    parent_id=prog.parent_id,
                )
                self.policy.update_global(score)
            except Exception as e:
                logger.warning(f"Seed graph insert failed: {e}")

    async def _run_iteration(self, iteration: int, checkpoint_callback) -> None:
        attempts = 1 + (self.max_retries if self.enable_retry else 0)
        error_context: Optional[str] = None
        plan: Optional[Dict[str, Any]] = None
        child: Optional[Program] = None
        gen_extra: Dict[str, Any] = {}
        iter_start = time.time()

        for _ in range(attempts):
            plan = await self._plan_action(iteration, error_context)
            child, error, gen_extra = await self._generate_and_eval(plan["prompt"], iteration, plan)
            if child is not None:
                break
            error_context = error
            logger.debug(f"Iteration {iteration} attempt failed: {error}")

        iter_time = time.time() - iter_start

        if child is None:
            logger.warning(f"Iteration {iteration}: all attempts failed ({error_context})")
            self._log_iteration_stats(iteration, plan, None, iter_time, gen_extra, error_context)
            return

        # Log prompt + raw LLM response into the program record (viewable in web_analysis)
        self.database.log_prompt(
            template_key=f"graphevolve_{plan['action']}",
            program_id=child.id,
            prompt=plan["prompt"],
            responses=[gen_extra.get("response", "")],
        )

        graph_rationale = self._extract_graph_rationale(gen_extra.get("response", ""), plan)
        await self._commit(child, plan, iteration, checkpoint_callback, graph_rationale)
        self._log_iteration_stats(iteration, plan, child, iter_time, gen_extra)

    # ====================================================================
    # Action planning
    # ====================================================================
    async def _plan_action(
        self, iteration: int, error_context: Optional[str]
    ) -> Dict[str, Any]:
        directions = self.database.build_direction_stats()
        bootstrapping = self._completed < self.bootstrap_k
        has_dir = len(directions) > 0

        # Bootstrap: seed the graph with diverse solution directions via space_explore.
        # Only fall back to EXPLOIT when the graph is still empty (first iter after seed insert).
        if not has_dir:
            action = EXPLOIT
        elif bootstrapping:
            action = SPACE_EXPLORE  # populate graph with k diverse directions before policy runs
        else:
            action = self.policy.choose_action(has_dir)

        if action == CROSSOVER:
            sources = await self._assemble_crossover_set(directions)
            if len(sources) < 2:
                action = EXPLOIT  # fallback: not enough distinct sources
            else:
                base_score = max(
                    (s.get("score", float("-inf")) for s in sources), default=float("-inf")
                )
                # Collect recent crossover programs so the LLM avoids repeating them
                prior_crossovers = sorted(
                    [p for p in self.database.programs.values()
                     if (p.metadata or {}).get("action") == CROSSOVER],
                    key=lambda p: p.iteration_found or 0, reverse=True
                )[:5]
                idea = None
                if self.use_idea_stage:
                    idea = await self._generate_idea_crossover(sources, prior_crossovers)
                prompt = self.context_builder.build_crossover_prompt(
                    sources, previous_attempts=prior_crossovers, idea=idea,
                    error_context=error_context,
                )
                return {
                    "action": CROSSOVER,
                    "prompt": prompt,
                    "base_score": base_score,
                    "parent_id": None,
                }

        if action == SPACE_EXPLORE:
            # During bootstrap: always NEW_FORM to maximise graph diversity.
            # After bootstrap: let the space bandit decide.
            target = NEW_FORM if bootstrapping else self.policy.choose_space_target()
            summary = ""
            try:
                summary = await self.experience_graph.summarize(iteration=iteration)
            except Exception as e:
                logger.warning(f"summarize failed: {e}")
            explored_map = self._explored_map_text(summary, directions)
            if self.analyze_graph and explored_map:
                analysis = await self._analyze_graph_llm(explored_map)
                if analysis:
                    explored_map += f"\n\n# Search Analysis\n{analysis}"
            # Skip exemplar assembly during bootstrap — saves N verify LLM calls when
            # there are only 1-4 directions; explored_map already shows what exists.
            if bootstrapping:
                exemplars = []
            else:
                exemplar_set = await self._assemble_crossover_set(directions)
                exemplars = [s["program"] for s in exemplar_set]
            seed = self.database.get_best_program()
            best_pv = self.database.global_best_problem_view()
            best_pv_info = self._pv_info(best_pv)
            idea = None
            if self.use_idea_stage and not bootstrapping:
                seed_desc = (seed.solution or "")[:400] if seed else ""
                idea = await self._generate_idea_space(target, explored_map, seed_desc)
            prompt = self.context_builder.build_space_prompt(
                target=target,
                explored_map=explored_map,
                exemplars=exemplars,
                seed=seed,
                best_pv_info=best_pv_info,
                idea=idea,
                error_context=error_context,
            )
            return {
                "action": SPACE_EXPLORE,
                "prompt": prompt,
                "target": target,
                "seed_score": self.database.proxy_score(seed),
                "parent_id": seed.id if seed else None,
                "bootstrap_space": bootstrapping,  # flag: skip space bandit update
            }

        # EXPLOIT (default / fallback)
        return self._plan_exploit(directions, bootstrapping=False, error_context=error_context)

    def _plan_exploit(
        self, directions: List[Any], bootstrapping: bool, error_context: Optional[str]
    ) -> Dict[str, Any]:
        if not bootstrapping and directions and self.exploit_sampling == "global":
            return self._plan_exploit_global(directions, error_context)
        if bootstrapping or not directions:
            parent = self.database.get_best_program()
            prompt = self.context_builder.build_mutate_prompt(
                parent=parent, error_context=error_context
            )
            return {
                "action": EXPLOIT,
                "prompt": prompt,
                "parent_id": parent.id if parent else None,
                "parent_score": self.database.proxy_score(parent),
                "direction_node_id": None,
                "direction_label": "",
            }

        node_id = self.policy.choose_direction(directions)
        dstats = next((d for d in directions if d.node_id == node_id), directions[0])
        node_id = dstats.node_id

        pidx = self.policy.sample_powerlaw(dstats.scores)
        parent = self.database.programs.get(dstats.leaf_ids[pidx]) if pidx is not None else None
        if parent is None:
            parent = self.database.get_best_program()

        cidx = self.policy.sample_context(
            dstats.scores, self.context_solutions_m, exclude={pidx} if pidx is not None else set()
        )
        context_programs = [
            self.database.programs[dstats.leaf_ids[i]]
            for i in cidx
            if dstats.leaf_ids[i] in self.database.programs
        ]

        node = self.database.direction_node(node_id)
        siblings: List[Program] = []
        direction_info = None
        if node is not None:
            leaves = [lf for lf in self.database.leaves_under(node) if lf.score is not None]
            leaves.sort(key=lambda lf: lf.score, reverse=True)
            for lf in leaves[: self.previous_attempts_n]:
                prog = self.database.program_of(lf)
                if prog is not None and prog.id != (parent.id if parent else None):
                    siblings.append(prog)
            pv = self.database.problem_view_of_direction(node_id)
            direction_info = {
                "pv_label": getattr(pv, "label", "") if pv else "",
                "pv_desc": getattr(pv, "description", "") if pv else "",
                "ss_label": node.label,
                "ss_desc": node.description or "",
            }

        prompt = self.context_builder.build_mutate_prompt(
            parent=parent,
            direction_info=direction_info,
            siblings=siblings,
            context_programs=context_programs,
            error_context=error_context,
        )
        return {
            "action": EXPLOIT,
            "prompt": prompt,
            "parent_id": parent.id if parent else None,
            "parent_score": self.database.proxy_score(parent),
            "direction_node_id": node_id,
            "direction_label": node.label if node is not None else "",
        }

    # ====================================================================
    # Crossover set assembly (quality-weighted sample + LLM-verify diversity)
    # ====================================================================
    async def _assemble_crossover_set(self, directions: List[Any]) -> List[Dict[str, Any]]:
        if self.diversity_mode == "embedding":
            return self._assemble_crossover_set_embedding(directions)
        reps: List[Dict[str, Any]] = []
        for d in directions:
            node = self.database.direction_node(d.node_id)
            if node is None:
                continue
            # Use quality-weighted random leaf (not always the best) for crossover diversity
            leaves = [lf for lf in self.database.leaves_under(node) if lf.score is not None]
            if not leaves:
                continue
            leaf_scores = [lf.score for lf in leaves]
            leaf_idx = self.policy.sample_powerlaw(leaf_scores)
            leaf = leaves[leaf_idx] if leaf_idx is not None else leaves[-1]
            prog = self.database.program_of(leaf)
            if prog is None:
                continue
            pv = self.database.problem_view_of_direction(d.node_id)
            desc = node.description or ""
            if pv is not None and pv.label:
                desc = f"{pv.label} / {node.label}. {desc}".strip()
            reps.append(
                {"program": prog, "label": node.label, "description": desc, "score": d.best}
            )

        k = min(self.crossover_set_size, len(reps))
        # No need to verify when candidates ≤ k — just return them all directly.
        if len(reps) <= k:
            return reps
        scores = [r["score"] for r in reps]
        selected: List[int] = []
        used: set = set()
        attempts = 0
        while len(selected) < k and attempts < self.crossover_max_attempts and len(used) < len(reps):
            i = self.policy.sample_powerlaw(scores, exclude=used)
            if i is None:
                break
            used.add(i)
            attempts += 1
            if not selected:
                selected.append(i)
                continue
            if await self._llm_verify_distinct([reps[j] for j in selected], reps[i]):
                selected.append(i)
        return [reps[i] for i in selected]

    async def _llm_verify_distinct(
        self, selected: List[Dict[str, Any]], candidate: Dict[str, Any]
    ) -> bool:
        """True if ``candidate`` is mechanistically distinct from all ``selected``."""
        language = self.config.language or "python"

        def _block(rep: Dict[str, Any]) -> str:
            code = extract_evolve_block(rep["program"].solution)
            return f"[{rep['label']}]\n```{language}\n{code}\n```"

        existing = "\n\n".join(_block(r) for r in selected)
        cand = _block(candidate)
        user = (
            "Existing selected solutions:\n\n"
            f"{existing}\n\n"
            "Candidate solution:\n\n"
            f"{cand}\n\n"
            "Does the candidate use a genuinely DIFFERENT core algorithmic mechanism from "
            "ALL of the existing selected solutions? Respond with JSON: "
            '{"distinct": true} or {"distinct": false}.'
        )
        try:
            result = await self.guide_llms.generate(
                _VERIFY_SYSTEM, [{"role": "user", "content": user}], temperature=0.0
            )
            text = (result.text or "").strip()
            m = re.search(r"\{[^{}]*\}", text)
            if m:
                return bool(json.loads(m.group(0)).get("distinct", True))
        except Exception as e:
            logger.debug(f"crossover verify failed, accepting candidate: {e}")
        return True  # fail-open: keep diversity rather than drop a candidate

    # ====================================================================
    # Generation + evaluation
    # ====================================================================
    def _wrapper_template(self, parent: Optional["Program"]) -> str:
        """A full, marker-bearing solution to merge a generated EVOLVE block into.

        The non-evolved wrapper is invariant across a benchmark, so the parent's
        solution (or, lacking one, the current best) supplies it verbatim.
        """
        if parent is not None and getattr(parent, "solution", None):
            return parent.solution
        best = self.database.get_best_program()
        return best.solution if best is not None and best.solution else ""

    def _build_child_solution(
        self, response: str, action: str, parent: Optional["Program"]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Turn a raw LLM response into a full, runnable child solution.

        EXPLOIT with ``exploit_diff_based`` applies SEARCH/REPLACE diffs onto the
        parent (wrapper preserved automatically).  Otherwise the model produced a
        rewrite of the EVOLVE block (or whole file), merged back into the wrapper
        when ``evolve_block_only`` is on.
        """
        if self.exploit_diff_based and action == EXPLOIT and parent and parent.solution:
            diffs = extract_diffs(response)
            if diffs:
                child = apply_diff(parent.solution, response)
                if child == parent.solution:
                    return None, "Diff blocks did not match parent solution"
                return child, None
            # Model ignored the diff format — fall back to full-rewrite parsing.

        block = parse_full_rewrite(response, self.config.language)
        if not block:
            return None, "No valid solution in response"
        if self.evolve_block_only:
            return merge_evolve_block(self._wrapper_template(parent), block), None
        return block, None

    def _bootstrap_llm_kwargs(self) -> Dict[str, Any]:
        """Per-call LLM reasoning overrides while bootstrapping.

        During the first ``bootstrap_k`` completed rounds, apply the configured
        reasoning mode (e.g. ``bootstrap_thinking: false``) to the generation
        call.  Returns ``{}`` once bootstrap is over so models fall back to their
        own settings.  Only non-None overrides are sent.
        """
        if self._completed >= self.bootstrap_k:
            return {}
        kwargs: Dict[str, Any] = {}
        if self.bootstrap_thinking is not None:
            kwargs["thinking"] = self.bootstrap_thinking
        if self.bootstrap_thinking_budget is not None:
            kwargs["thinking_budget"] = self.bootstrap_thinking_budget
        if self.bootstrap_reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.bootstrap_reasoning_effort
        return kwargs

    async def _generate_and_eval(
        self, prompt: Dict[str, str], iteration: int, plan: Dict[str, Any]
    ) -> Tuple[Optional["Program"], Optional[str], Dict[str, Any]]:
        """Returns (child, error, gen_extra) where gen_extra carries response + timing."""
        child_id = str(uuid.uuid4())
        gen_extra: Dict[str, Any] = {"response": "", "llm_time": 0.0, "eval_time": 0.0}

        llm_start = time.time()
        try:
            result = await self._call_llm(
                prompt["system"], prompt["user"], **self._bootstrap_llm_kwargs()
            )
            response = result.text
        except Exception as e:
            return None, f"LLM error: {e}", gen_extra
        gen_extra["llm_time"] = time.time() - llm_start
        gen_extra["response"] = response or ""

        if not response:
            return None, "Empty LLM response", gen_extra

        parent_id = plan.get("parent_id")
        parent = self.database.programs.get(parent_id) if parent_id else None

        child_solution, parse_error = self._build_child_solution(
            response, plan["action"], parent
        )
        if not child_solution:
            return None, parse_error or "No valid solution in response", gen_extra

        eval_start = time.time()
        try:
            eval_result = await self.evaluator.evaluate_program(child_solution, child_id)
        except Exception as e:
            return None, f"Evaluation error: {e}", gen_extra
        gen_extra["eval_time"] = time.time() - eval_start

        metrics = eval_result.metrics
        artifacts = eval_result.artifacts
        if self._is_eval_failure(metrics, artifacts):
            err = (
                (metrics.get("error") if isinstance(metrics.get("error"), str) else None)
                or (artifacts or {}).get("error")
                or "Evaluation failed"
            )
            return None, f"Eval failure: {err}", gen_extra

        # Build a descriptive changes string for web_analysis / timeline
        action = plan["action"]
        dir_label = plan.get("direction_label", "")
        if action == EXPLOIT:
            changes = f"exploit → '{dir_label}'" if dir_label else "exploit (bootstrap)"
        elif action == CROSSOVER:
            changes = "crossover"
        elif plan.get("bootstrap_space"):
            changes = f"bootstrap → new direction"
        else:
            changes = f"space_explore → {plan.get('target', '')}"

        child = Program(
            id=child_id,
            solution=child_solution,
            language=self.config.language,
            metrics=metrics,
            iteration_found=iteration,
            parent_id=parent_id,
            generation=(parent.generation + 1) if parent else 0,
            metadata={
                "changes": changes,
                "action": action,
                "direction_label": dir_label,
                "parent_score": plan.get("parent_score"),
                "parent_metrics": parent.metrics if parent else None,
                "sampling_mode": action,
            },
            artifacts=artifacts,
        )
        return child, None, gen_extra

    @staticmethod
    def _is_eval_failure(metrics: Dict[str, Any], artifacts: Dict[str, Any]) -> bool:
        return bool(
            metrics.get("validity") in (0, -1)
            or (metrics.get("timeout") is True and metrics.get("validity") is None)
            or (
                metrics.get("combined_score") == 0
                and (metrics.get("error") is not None or "error" in (artifacts or {}))
            )
        )

    # ====================================================================
    # Commit: graph insert + policy update + persistence
    # ====================================================================
    async def _commit(
        self,
        child: Program,
        plan: Dict[str, Any],
        iteration: int,
        checkpoint_callback,
        graph_rationale: str = "",
    ) -> None:
        action = plan["action"]
        score = self.database.proxy_score(child)
        self.database.add(child, iteration=iteration)

        # Capture branch state before insert (for space-explore verification).
        pre_pv = self.database.problem_view_ids()
        pre_ss = self.database.solution_strategy_ids()
        if action == SPACE_EXPLORE:
            placement_hint = plan.get("target")
        elif self.force_attach_existing and action in (EXPLOIT, CROSSOVER):
            placement_hint = "attach"
        else:
            placement_hint = None

        rationale = graph_rationale or (child.metadata or {}).get("changes", action)
        extra = {"policy_action": action}
        if action == SPACE_EXPLORE:
            extra["space_target"] = plan.get("target")
        if action == EXPLOIT and plan.get("direction_node_id"):
            extra["direction_node_id"] = plan.get("direction_node_id")
        try:
            await self.experience_graph.insert(
                solution_id=child.id,
                score=score,
                rationale=rationale,
                iteration=iteration,
                parent_id=child.parent_id,
                placement_hint=placement_hint,
                extra=extra,
            )
        except Exception as e:
            logger.warning(f"ExperienceGraph insert failed: {e}")

        # Policy updates
        self.policy.tick()
        self.policy.update_global(score)

        if action == EXPLOIT:
            parent_score = plan.get("parent_score", float("-inf"))
            self.policy.record_direction_pull(plan.get("direction_node_id"))
            self.policy.update_action_reward(EXPLOIT, score > parent_score)
        elif action == CROSSOVER:
            self.policy.update_action_reward(CROSSOVER, score > plan.get("base_score", float("-inf")))
        elif action == SPACE_EXPLORE:
            target = plan["target"]
            created_new_form, created_new_dir = self.database.verify_space_placement(
                child.id, pre_pv, pre_ss
            )
            matched = (target == NEW_FORM and created_new_form) or (
                target != NEW_FORM and created_new_dir
            )
            if not matched:
                logger.warning(
                    f"Space-explore target '{target}' was attached to an existing branch "
                    f"(new_form={created_new_form}, new_dir={created_new_dir}); reward=0."
                )
            # Skip space bandit update during bootstrap: target was forced, not chosen by bandit
            if not plan.get("bootstrap_space"):
                improved = matched and score > plan.get("seed_score", float("-inf"))
                self.policy.update_space_reward(target, improved)

        self._completed += 1

        logger.info(
            f"Iter {iteration} [{action}] program {child.id[:8]} score={score:.4f} "
            f"(p_space={self.policy.p_space():.3f}, w_exploit={self.policy.state.w_exploit:.2f})"
        )

        if self.monitor_callback:
            try:
                self.monitor_callback(child, iteration)
            except Exception:
                logger.debug("Monitor callback error", exc_info=True)

        if iteration > 0 and iteration % self.config.checkpoint_interval == 0:
            self.database.save_policy_state()
            self.database.log_status()
            if checkpoint_callback:
                checkpoint_callback(iteration)

    # ====================================================================
    # Global exploit sampling
    # ====================================================================
    def _plan_exploit_global(
        self, directions: List[Any], error_context: Optional[str]
    ) -> Dict[str, Any]:
        """Power-law sample across ALL leaf programs regardless of direction."""
        all_ids: List[str] = []
        all_scores: List[float] = []
        for d in directions:
            for lid, sc in zip(d.leaf_ids, d.scores):
                all_ids.append(lid)
                all_scores.append(sc)

        parent: Optional[Program] = None
        if all_ids:
            idx = self.policy.sample_powerlaw(all_scores)
            pid = all_ids[idx] if idx is not None else all_ids[0]
            parent = self.database.programs.get(pid)

        if parent is None:
            parent = self.database.get_best_program()

        # Find direction info for the selected parent (best-effort)
        direction_info = None
        if parent is not None:
            for d in directions:
                if parent.id in d.leaf_ids:
                    node = self.database.direction_node(d.node_id)
                    if node is not None:
                        pv = self.database.problem_view_of_direction(d.node_id)
                        direction_info = {
                            "pv_label": getattr(pv, "label", "") if pv else "",
                            "pv_desc": getattr(pv, "description", "") if pv else "",
                            "ss_label": node.label,
                            "ss_desc": node.description or "",
                        }
                    break

        prompt = self.context_builder.build_mutate_prompt(
            parent=parent,
            direction_info=direction_info,
            error_context=error_context,
        )
        dir_label = (direction_info or {}).get("ss_label", "global")
        return {
            "action": EXPLOIT,
            "prompt": prompt,
            "parent_id": parent.id if parent else None,
            "parent_score": self.database.proxy_score(parent),
            "direction_node_id": None,
            "direction_label": dir_label,
        }

    # ====================================================================
    # Embedding-based crossover diversity
    # ====================================================================
    def _assemble_crossover_set_embedding(
        self, directions: List[Any]
    ) -> List[Dict[str, Any]]:
        """Select crossover sources by combined fitness+novelty score (no LLM verify call)."""
        from skydiscover.search.adaevolve.archive.diversity import CodeDiversity

        diversity = CodeDiversity()

        # Build candidate pool: one quality-weighted-random leaf per direction
        reps: List[Dict[str, Any]] = []
        for d in directions:
            node = self.database.direction_node(d.node_id)
            if node is None:
                continue
            leaves = [lf for lf in self.database.leaves_under(node) if lf.score is not None]
            if not leaves:
                continue
            leaf_scores = [lf.score for lf in leaves]
            leaf_idx = self.policy.sample_powerlaw(leaf_scores)
            leaf = leaves[leaf_idx] if leaf_idx is not None else leaves[-1]
            prog = self.database.program_of(leaf)
            if prog is None:
                continue
            pv = self.database.problem_view_of_direction(d.node_id)
            desc = node.description or ""
            if pv is not None and pv.label:
                desc = f"{pv.label} / {node.label}. {desc}".strip()
            reps.append({"program": prog, "label": node.label, "description": desc, "score": d.best})

        if len(reps) <= self.crossover_set_size:
            return reps

        programs = [r["program"] for r in reps]
        n = len(programs)

        # Novelty = average distance to all other candidates
        novelty_scores: List[float] = []
        for i, prog in enumerate(programs):
            dists = [diversity.distance(prog, programs[j]) for j in range(n) if j != i]
            novelty_scores.append(sum(dists) / len(dists) if dists else 0.0)

        fit_scores = [r["score"] for r in reps]

        def _norm(vals: List[float]) -> List[float]:
            lo, hi = min(vals), max(vals)
            span = hi - lo
            return [(v - lo) / span if span > 1e-9 else 0.5 for v in vals]

        norm_fit = _norm(fit_scores)
        norm_nov = _norm(novelty_scores)
        combined = [0.7 * f + 0.3 * nv for f, nv in zip(norm_fit, norm_nov)]

        # Quality-weighted sample without replacement from combined scores
        k = min(self.crossover_set_size, n)
        selected: List[int] = []
        used: Set[int] = set()
        while len(selected) < k and len(used) < n:
            i = self.policy.sample_powerlaw(combined, exclude=used)
            if i is None:
                break
            used.add(i)
            selected.append(i)

        return [reps[i] for i in selected]

    # ====================================================================
    # Two-stage ideation
    # ====================================================================
    _IDEA_SYSTEM = (
        "You are a creative algorithm designer. Plan — do not implement — new "
        "algorithmic approaches. Respond ONLY with the requested JSON object."
    )

    async def _generate_idea_crossover(
        self,
        sources: List[Dict[str, Any]],
        prior_crossovers: List[Program],
    ) -> Optional[Dict[str, Any]]:
        """Stage 1 for crossover: plan a synthesis strategy before coding."""
        src_lines: List[str] = []
        for i, src in enumerate(sources, 1):
            prog = src["program"]
            score = src.get("score")
            desc = src.get("description", "")
            snippet = (prog.solution or "")[:400]
            score_str = f" (score: {score:.4f})" if isinstance(score, (int, float)) else ""
            src_lines.append(
                f"Source {i}: {src.get('label', '')}{score_str}\n"
                f"Direction: {desc}\nSnippet:\n{snippet}"
            )
        prev_lines: List[str] = []
        for i, p in enumerate(prior_crossovers, 1):
            label = (p.metadata or {}).get("changes", f"Attempt {i}")
            prev_lines.append(f"Attempt {i}: {label}\n{(p.solution or '')[:200]}")

        user = (
            "Plan a crossover synthesis WITHOUT writing code.\n\n"
            "# Source Solutions\n"
            + "\n\n".join(src_lines)
            + "\n\n# Previous Crossover Attempts (avoid repeating)\n"
            + ("\n\n".join(prev_lines) if prev_lines else "None yet.")
            + "\n\nRespond with JSON:\n"
            '{"synthesis_strategy": "...", "key_ideas": ["..."], '
            '"combination_rationale": "...", "what_to_avoid": "...", '
            '"expected_strength": "..."}'
        )
        try:
            result = await self._call_llm(self._IDEA_SYSTEM, user)
            return self._parse_json_first(result.text or "")
        except Exception as e:
            logger.warning(f"Idea generation (crossover) failed: {e}")
            return None

    async def _generate_idea_space(
        self,
        target: str,
        explored_map: str,
        seed_desc: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Stage 1 for space_explore: plan a new direction before coding."""
        if target == NEW_FORM:
            instr = (
                "Propose a fundamentally NEW way of FRAMING this problem "
                "(a new problem_view) that is NOT present in the explored map."
            )
        else:
            instr = (
                "Propose a NEW SOLUTION STRATEGY under the current best problem framing "
                "that has NOT been tried yet (keep the same problem_view)."
            )

        user = (
            "Plan a new exploration direction WITHOUT writing code.\n\n"
            f"# Explored Map\n{explored_map}\n\n"
            f"# Current Best (jump-off)\n{seed_desc or '(not available)'}\n\n"
            f"# Instruction\n{instr}\n\n"
            "Respond with JSON:\n"
            '{"approach_name": "...", "problem_framing": "...", '
            '"solution_strategy": "...", "why_different": "...", '
            '"key_mechanisms": ["..."], "expected_advantage": "..."}'
        )
        try:
            result = await self._call_llm(self._IDEA_SYSTEM, user)
            return self._parse_json_first(result.text or "")
        except Exception as e:
            logger.warning(f"Idea generation (space_explore) failed: {e}")
            return None

    async def _analyze_graph_llm(self, explored_map: str) -> str:
        """Lightweight LLM analysis of explored directions (uses guide_llms, no thinking)."""
        system = (
            "You are an algorithm expert reviewing search progress. "
            "Be concise, specific, and actionable."
        )
        user = (
            f"Review this exploration history:\n\n{explored_map}\n\n"
            "In 2-3 sentences: (1) What pattern or bottleneck do you see? "
            "(2) What specific algorithmic approach NOT yet tried could be promising?"
        )
        try:
            result = await self.guide_llms.generate(
                system, [{"role": "user", "content": user}], temperature=0.0
            )
            return (result.text or "").strip()
        except Exception as e:
            logger.debug(f"Graph analysis failed: {e}")
            return ""

    @staticmethod
    def _parse_json_first(text: str) -> Optional[Dict[str, Any]]:
        """Extract the first well-formed JSON object from LLM response text."""
        start = 0
        while True:
            start = text.find("{", start)
            if start == -1:
                return None
            depth = 0
            for i in range(start, len(text)):
                c = text[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start += 1

    # ====================================================================
    # Helpers
    # ====================================================================
    @staticmethod
    def _extract_graph_rationale(response: str, plan: Dict[str, Any]) -> str:
        """Build a rationale string that gives LLM_place meaningful algorithmic context.

        Priority:
        1. Explanatory text BEFORE the first code block (LLM usually explains the approach).
        2. First docstring of the main function inside the code.
        3. Fallback to a terse action description (avoids 'exploit generation' leaking in).
        """
        action = plan.get("action", "")
        text = response or ""

        # 1. Pre-code explanation (most informative)
        m = re.search(r"```(?:python)?\s*\n", text)
        if m:
            pre = text[: m.start()].strip()
            if len(pre) > 30:
                lines = [ln.strip() for ln in pre.splitlines() if ln.strip()]
                rationale = " ".join(lines)[:400]
                return rationale

        # 2. First function docstring
        m = re.search(r'def \w+[^:]*:\s*"""(.*?)"""', text, re.DOTALL)
        if m:
            doc = m.group(1).strip().replace("\n", " ")
            return doc[:400]

        # 3. Terse fallback (never say "exploit generation")
        dir_label = plan.get("direction_label", "")
        if action == EXPLOIT:
            return f"Refinement of '{dir_label}' approach" if dir_label else "Iterative refinement"
        if action == CROSSOVER:
            return "Synthesis of multiple solution directions"
        target = plan.get("target", "new region")
        return f"Space exploration → {target}"

    def _pv_info(self, pv) -> Optional[Dict[str, str]]:
        if pv is None:
            return None
        return {"pv_label": pv.label, "pv_desc": pv.description or ""}

    def _explored_map_text(self, summary: str, directions: List[Any]) -> str:
        lines: List[str] = []
        if summary:
            lines.append(summary)
        listing: List[str] = []
        for d in directions:
            node = self.database.direction_node(d.node_id)
            if node is None:
                continue
            pv = self.database.problem_view_of_direction(d.node_id)
            pv_label = pv.label if pv else "?"
            listing.append(
                f"- {pv_label} / {node.label} (best {d.best:.4f}, {d.n_leaves} solutions)"
            )
        if listing:
            lines.append("\nAll solution directions tried so far:")
            lines.extend(listing)
        return "\n".join(lines) if lines else "(empty)"
