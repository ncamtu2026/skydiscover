# Adaptive Search Designs: AdaEvolve · GraphEvolve · AdaGraph

> Consolidated, code-grounded design reference for the three adaptive evolutionary
> search backends in SkyDiscover, as of **2026-06-22**.
> Sources: `skydiscover/search/{adaevolve,graphevolve,adagraph}/`,
> `skydiscover/experience_graph/`, `skydiscover/config.py`.
>
> This document describes *what each algorithm does step by step* and *how every
> decision is made* (the probability/score formulas, the state that drives them,
> and where in the code they live). It supersedes the older per-algorithm notes
> (`adaevolve_architecture.md`, `graphevolve.md`, `advance_graph_evolve.md`,
> `adagraph_architecture.md`) by putting all three side by side.

---

## 0. Shared substrate

All three backends plug into the same discovery loop and share several primitives.

### 0.1 The unit of work: `Program`
A `Program` (see `search/base_database.py`) carries: `id`, `solution` (source
code), `metrics` (the evaluator's raw output dict), `parent_id`, `generation`,
`iteration_found`, and a free-form `metadata` dict (used for `changes`, `action`,
`paradigm_idea`, etc.).

### 0.2 The per-iteration pipeline  *(see Fig. 0)*
Every backend runs the same skeleton (`Controller.run_discovery` → `_run_iteration`):

1. **Plan / select** — decide *what kind of move* to make and *which parent(s)* to
   build from. This is where the three algorithms differ most.
2. **Generate** — build a prompt (context builder) and call the LLM pool to produce
   a child solution (full rewrite or SEARCH/REPLACE diff).
3. **Evaluate** — run the user's evaluator on the child, producing `metrics`.
4. **Commit** — store the program, update the population structure (islands or
   ExperienceGraph), and update the adaptive state that drives future decisions.
5. **Housekeeping** — `end_iteration` rotates the active island/PV, fires migration
   on schedule, checkpoints.

### 0.3 Proxy score (the single scalar everything optimizes)
The evaluator returns a metrics dict; the search layer collapses it to one number
via `compute_proxy_score(metrics, fitness_key, pareto_objectives, higher_is_better)`
(`utils/metrics.py`). `higher_is_better` / `fitness_key` / `pareto_objectives` are
read from the database config. **All bandit rewards, archive rankings, UCB stats,
and "did it improve?" tests are computed on this proxy score**, so the metric
direction is consistent everywhere.

### 0.4 The ExperienceGraph (population substrate for GraphEvolve & AdaGraph)  *(see Fig. 1)*
A two-level tree (`experience_graph/experience_graph.py`, `nodes.py`):

```
ROOT
└── problem_view      (internal, field_name="problem_view")   ← a *framing* of the problem
    └── solution_strategy (internal, field_name="solution_strategy") ← a *direction*/mechanism
        └── leaf        (one evaluated Program: solution_id, score, rationale)
```

- **`insert(solution_id, score, rationale, placement_hint, ...)`** — renders the
  current tree as text and calls **LLM_place**, a JSON-returning LLM call that
  picks exactly one of three actions:
  - **ATTACH_TO(target_id)** — same problem_view *and* same solution_strategy as an
    existing branch → append the leaf under that strategy node.
  - **NEW_BRANCH_UNDER(target_id, new_path)** — diverges at some level. `new_path`
    lists the internal nodes to create (2 entries = brand-new problem_view +
    strategy; 1 entry = new strategy under an existing problem_view).
  - **SPLIT(target_leaf_id, ...)** — two leaves reveal a strategy distinction not yet
    in the tree → wrap the old leaf + new leaf under a freshly created
    solution_strategy node.
  Parsing is defensive: a missing/garbled `action` is *inferred* from which fields
  are present, and a hard parse failure falls back to `NEW_BRANCH_UNDER(root)` with
  two "Unknown" internal nodes (`_ensure_two_level_path`).
- **`placement_hint`** biases LLM_place: `"new_form"` / `"new_dir"` nudge it to open
  a fresh problem_view / strategy; `"attach"` nudges it to reuse an existing branch.
- **Deterministic mutators** (used by AdaGraph to *guarantee* placement without an
  LLM_place call): `attach_under_parent` (ATTACH under the parent's strategy node),
  `create_direction` (force a new strategy under a given problem_view),
  `create_problem_view` (force a new problem_view).
- **`summarize()`** renders a compact, optionally LLM-compressed text view of the
  tree — fed to paradigm/space prompts so the generator can "see" what's been tried.

> Note: the `nodes.py` docstring still mentions an older "paradigm → formulation →
> mechanism" 3-layer naming; the **live** schema is the 2-layer
> `problem_view → solution_strategy` shown above (see `_ensure_two_level_path` and
> the LLM_place prompt in `_llm_place`).

---

## 1. AdaEvolve — adaptive multi-island evolution

**Config:** `AdaEvolveDatabaseConfig` (`search.type: adaevolve`).
**Code:** `search/adaevolve/{controller,database,adaptation}.py`.

*Architecture: Fig. 2 · intensity dial: Fig. 3.*

The population is a fixed-then-dynamic set of **islands**. Each island owns a
`UnifiedArchive` (a MAP-Elites-like store balancing fitness, novelty, and Pareto
status) and an `AdaptiveState`. A `MultiDimensionalAdapter` coordinates the islands
with UCB selection. There is no graph by default (it *can* attach an ExperienceGraph
for paradigm context, but islands are the substrate).

### 1.1 State that drives decisions
Per island `k`, `AdaptiveState` (`adaptation.py`) tracks:
- `best_score` — local best (used for **local** delta normalization).
- `accumulated_signal` G — EMA of squared *normalized* improvements:
  `G ← ρ·G + (1−ρ)·δ²`, where `δ = min((fitness − best)/(|best|+ε), 1)`.
- `improvement_count`, `total_evaluations` → productivity.

The `MultiDimensionalAdapter` additionally keeps, per island:
- `dimension_visits` (raw), `decayed_visits` `V` (`V ← ρ·V + 1`),
- `dimension_rewards` `R` — decayed cumulative reward, but normalized by the
  **global** best (`R ← ρ·R + δ_global`), and
- `global_best_score`.

**Why two normalizations?** Search *intensity* uses the **local** best so a small,
struggling island can still register "I'm improving relative to myself" and shift to
exploitation. UCB *cross-island* reward uses the **global** best so a trash island
making big percentage gains on tiny numbers can't out-compete a globally valuable
island ("Poor Island Bias" fix, documented in `adaptation.py`).

### 1.2 Decision 1 — search intensity (explore vs exploit *within* an island)
For the current island, intensity is:

```
intensity = I_min + (I_max − I_min) / (1 + √(G + ε))      # get_search_intensity()
```

- Low G (stagnant island) → intensity → I_max → **explore**.
- High G (productive island) → intensity → I_min → **exploit**.

Intensity is then turned into a **sampling mode** (`database.sample` /
`_sample_from_archive`) with a fixed split:

```
r ~ U(0,1)
r < intensity                         → "exploration"   (novelty-aware archive sample)
r < intensity + (1−intensity)·0.7     → "exploitation"  (top-k fitness / Pareto-front sample)
else                                  → "balanced"      (fitness-weighted sample)
```

So at `intensity=0.4`: 40% explore / 42% exploit / 18% balanced. `force_exploration`
or `use_adaptive_search=false` (→ `fixed_intensity`) overrides this.

**Context programs** for the prompt are *hybrid*: a `local_context_program_ratio`
fraction are the most-diverse picks from the parent's own archive, the rest are the
global top performers across all islands (cross-pollination).

### 1.3 Decision 2 — which island to work next (UCB)
After each iteration, `end_iteration` picks the next island
(`select_dimension_ucb`):

```
underexplored (visits < min_visits)? → pick one at random (cold-start)
else  argmax_k [ R_k/V_k  +  c·√( ln(N+1) / visits_k ) ]
```

`R_k/V_k` is "recent reward per recent visit" (both decayed, so old breakthroughs
fade and can't pin selection forever). `c = ucb_exploration` (√2 by default). An
ablation switch (`use_ucb_selection=false`) falls back to round-robin.

### 1.4 Decision 3 — migration (periodic cross-island transfer)
Every `migration_interval` iterations, **ring migration** copies the top
`migration_count` programs from island `i` to island `(i+1) mod K`
(`_migrate_archives`). Migrants enter via `receive_external_improvement`: this
raises the destination's `best_score` and G (pushing it toward exploitation of the
gift) **without** crediting the destination's UCB visits/rewards (it didn't earn it).

### 1.5 Decision 4 — dynamic island spawning
If `use_dynamic_islands`, `_should_spawn_island` fires when **all** of:
`use_unified_archive`, `num_islands < max_islands`,
`iterations_since_last_spawn ≥ spawn_cooldown`, and
**global productivity < `spawn_productivity_threshold`** (the whole fleet is
struggling). A new island gets a fresh archive whose weighting preset is chosen from
`ISLAND_CONFIG_PRESETS` preferring **underused** presets (`_select_spawn_config`),
is seeded with the top ~5 programs, and gets a fresh `AdaptiveState` dimension.

### 1.6 Decision 5 — paradigm breakthrough (escape deep stalls)
Independent of islands. When `use_paradigm_breakthrough` and
`is_paradigm_stagnating()` (global improvement rate below threshold, tracked by a
`paradigm_tracker`) and no paradigm is currently active, the controller calls a
`ParadigmGenerator` to LLM-ideate a batch of `paradigm_num_to_generate` *radically
different* approaches (optionally fed KnowledgeEvolve papers and/or an
ExperienceGraph summary as context, and a list of previously-tried ideas to avoid
repeats). While a paradigm is active, the **best** program is forced as parent so the
new idea is applied to the strongest solution. Each paradigm has a bounded number of
uses (`paradigm_max_uses`).

### 1.7 One AdaEvolve iteration, end to end
```
_run_iteration:
  if paradigm enabled and globally stagnating and no active paradigm:
      generate paradigm batch
  parent, context = database.sample(...)        # intensity→mode→parent; hybrid context
  if active paradigm: parent ← global best
  prompt = context_builder(parent, context, paradigm, siblings, error?)
  child  = LLM.generate(prompt)                  # diff or full rewrite
  metrics = evaluate(child)
  database.add(child → current island archive)   # updates AdaptiveState + UCB reward
finally end_iteration:
  maybe spawn island; pick next island (UCB); maybe migrate
```

---

## 2. GraphEvolve — policy-driven search over the ExperienceGraph

**Config:** `GraphEvolveDatabaseConfig` (`search.type: graphevolve`).
**Code:** `search/graphevolve/{controller,policy,database}.py`.

*Decision stack: Fig. 4 · circuit breaker: Fig. 5.*

**No islands.** The ExperienceGraph *is* the population. A pure, unit-testable
`GraphEvolvePolicy` (`policy.py`) makes every decision from `DirectionStats` (derived
live from the graph leaves) plus a small persisted `PolicyState` sidecar
(`graphevolve_policy.json`). A "direction" = one `solution_strategy` node; its score
stats (`mu`, `var`, `best`) are recomputed from the leaves under it each iteration,
so they stay correct even after the tree is restructured by a SPLIT.

### 2.1 Bootstrap
The first `bootstrap_k` *completed* generations are special: actions are forced to
seed the graph with diverse branches (always `SPACE_EXPLORE → NEW_FORM`, or `EXPLOIT`
when the graph is still empty), exemplar-assembly and idea stages are skipped, and
the space-bandit is **not** updated (the target was forced, not chosen). A configurable
**bootstrap reasoning mode** (`bootstrap_thinking` / `bootstrap_thinking_budget` /
`bootstrap_reasoning_effort`) can run these seeding generations with a different LLM
reasoning setting (e.g. thinking off) — applied only while `completed < bootstrap_k`.

### 2.2 The multi-tier decision stack (after bootstrap)
Each iteration the policy descends a stack of decisions:

**Tier 1 — action.** `choose_action`:
1. *Circuit breaker.* With probability `p_space = sigmoid(λ·(τ_stag − G_global))`,
   the action is `SPACE_EXPLORE`. `G_global` is an EMA of squared normalized global
   improvements (`update_global`: `G ← ρ·G + (1−ρ)·δ²`). When progress stalls,
   `G_global → 0`, so `p_space → sigmoid(λ·τ_stag)` rises and the search opens new
   territory. (A fresh run starts at `initial_g_global` so space-explore stays *off*
   until improvement genuinely stalls.)
2. Otherwise a **2-arm bandit** picks `EXPLOIT` vs `CROSSOVER`:
   `p_exploit = w_exploit / (w_exploit + w_crossover)`. `w_crossover` is a fixed
   anchor (=1.0); only `w_exploit` moves.

**Tier 2a — direction (for EXPLOIT).** `choose_direction` = **UCB1-Normal** over the
`solution_strategy` directions:
```
cold direction (pull_count==0)? → pick one at random   (natural cold start, UCB=+∞)
else argmax_d [ μ_d + √(16·var_d·ln(t−1)/n_d)  +  c·√(ln(t−1)/n_d) ]
```
The `√(16·var·ln/n)` is the UCB1-Normal term (favors high-mean, high-variance,
under-pulled directions); the `c·√(ln/n)` floor keeps exploration alive when a
direction's variance is 0.

**Parent within the chosen direction.** `sample_powerlaw` over the leaves' scores:
rank the leaves (rank 1 = best), weight `rank^(−powerlaw_alpha)`, sample one.
`alpha=0` → uniform; `alpha→∞` → always the best. `sample_context` draws `m` distinct
*inspiration* leaves the same way; the top `previous_attempts_n` sibling leaves are
shown to the LLM as "already tried."

**Tier 2b — crossover set (for CROSSOVER).** `_assemble_crossover_set`:
take one quality-weighted representative leaf per direction, then iteratively
quality-sample candidates and keep a candidate only if an **LLM-verify** call says it
is *mechanistically distinct* from all already-selected reps (fail-open: keep it on
error). Stops at `crossover_set_size` or `crossover_max_attempts`. This yields a small
set of genuinely different parents to recombine. (An `embedding` diversity mode is
also available.)

**Tier 2c — space target (for SPACE_EXPLORE).** `choose_space_target` = a second
2-arm bandit: `NEW_FORM` (open a new problem_view / framing) vs `NEW_DIR` (open a new
solution_strategy under the global-best problem_view). `w_new_dir` is the fixed
anchor; only `w_new_form` moves. During bootstrap the target is forced to `NEW_FORM`.

### 2.3 Generation specifics
- **EXPLOIT** can be diff-based (`exploit_diff_based`): the LLM emits SEARCH/REPLACE
  blocks applied onto the parent, preserving the fixed wrapper automatically. If the
  model ignores the diff format, it falls back to full-rewrite parsing.
- **`evolve_block_only`**: the model only rewrites the mutable EVOLVE-BLOCK, which is
  merged back into the parent's wrapper so `program.solution` is always runnable.
- CROSSOVER and SPACE_EXPLORE are always full rewrites.

### 2.4 Commit & reward (`_commit`)
1. Add the program; compute its proxy `score`.
2. **Insert into the graph** with a placement hint matching the action: `SPACE_EXPLORE`
   passes its `target` ("new_form"/"new_dir") so LLM_place opens a branch; EXPLOIT /
   CROSSOVER pass `"attach"` (when `force_attach_existing`) so the child stays in an
   existing branch.
3. `policy.tick()` (advance UCB clock `t`); `policy.update_global(score)` (update
   `G_global` + `best_global`).
4. **Bandit/UCB updates** keyed by action:
   - EXPLOIT → record a direction pull; `update_action_reward(EXPLOIT, score > parent_score)`.
   - CROSSOVER → `update_action_reward(CROSSOVER, score > base_score)`.
   - SPACE_EXPLORE → *verify the placement actually created the intended branch*
     (`verify_space_placement` compares pre/post problem_view & strategy id sets);
     reward the `new_form` arm only if it both matched **and** improved on the seed.
   Bandit update rule (`_bandit_update`): win → `w += alpha`; loss →
   `w = max(1, beta·w)`; clipped to `w_max`.
5. `completed += 1`.

### 2.5 One GraphEvolve iteration, end to end
```
_plan_action:
  bootstrapping? force SPACE_EXPLORE→NEW_FORM (or EXPLOIT if graph empty)
  else Tier1 choose_action:
      p_space circuit breaker → SPACE_EXPLORE → Tier2c target bandit
      else exploit/crossover bandit:
          EXPLOIT  → Tier2a UCB direction + power-law parent + context + siblings
          CROSSOVER→ Tier2b quality-sample + LLM-verify distinct set
  → build prompt
generate (bootstrap reasoning mode if bootstrapping) → evaluate → build child
_commit: graph insert (hinted) → tick/update_global → action-specific bandit/UCB reward
```

---

## 3. AdaGraph — AdaEvolve machinery where the graph *is* the islands

**Config:** `AdaGraphDatabaseConfig` (extends `AdaEvolveDatabaseConfig`,
`search.type: adagraph`).
**Code:** `search/adagraph/{controller,database}.py` — `AdaGraphController` **subclasses
`AdaEvolveController`** and reuses its whole generation/eval/paradigm/logging
pipeline. Only the parts the graph substrate touches are overridden.

*Architecture: Fig. 6 · iteration flow: Fig. 7.*

**Core idea:** keep AdaEvolve's per-dimension `AdaptiveState`/UCB/UnifiedArchive
machinery, but make each **dimension = one `problem_view` (PV)** of the
ExperienceGraph instead of a fixed island. PVs are born by *generative spawn* (a cheap
LLM reframe) on stalls, not by copying top programs into a fresh container. The graph
also keeps the full memory used for paradigm summaries and visualization.

### 3.1 PV lifecycle and bookkeeping
- `ensure_pv_slot(pv_id)` lazily binds a graph problem_view to an archive + adapter
  dimension the first time it's seen, marks it `active`, and gives it a **grace
  period** (`pv_grace_period` iterations during which UCB cannot starve it).
- `active_pvs` is the live set; `pv_memory` retains *all* PVs ever opened (for dedup),
  even after they're dropped.
- **PV health** `q_k = R_k / V_k` — the same decayed global-normalized reward over
  decayed visits as AdaEvolve, per PV (`_pv_quality`).

### 3.2 Seeding & bootstrap
`run_discovery`: `_seed_graph` inserts the seed program (LLM_place creates PV #0),
then `_bootstrap_pvs` opens up to `n_init` (= `num_islands`) framings via repeated
generative spawn (bounded attempts so it can't loop forever if LLM_place keeps
attaching instead of opening a new PV).

### 3.3 Decision 1 — per-iteration PV selection (grace → UCB)
`end_iteration` (over **active** PVs only):
1. Spend one grace tick on the PV just used.
2. If any active PV is still in grace → force-select it (protect newborns).
3. Else UCB (`_select_active_pv_ucb`): cold PVs (visits < `min_visits`) first, then
   `argmax_k [ q_k + c·√(ln(ΣN+1)/visits_k) ]`.
4. (Ablation: round-robin over active PVs.)

Within the selected PV, generation reuses AdaEvolve's intensity→mode→archive sampling
unchanged — so *intra-PV* explore/exploit is identical to AdaEvolve.

### 3.4 Decision 2 — what kind of child this iteration
Each iteration produces **either** a paradigm child **or** a normal exploit child
(never a free generative spawn mid-loop):
```
if paradigm enabled and globally stagnating:  generate + annotate a paradigm batch
if an active paradigm exists:                 _apply_paradigm  (form or direction)
else:                                          _run_normal_step (AdaEvolve exploit in current PV)
                                               → place_and_add(hint="attach")  # stays in parent's PV
```

### 3.5 Decision 3 — paradigm batch annotation (form vs direction)
When a batch of paradigm ideas is generated, `_generate_and_annotate_paradigms` labels
each idea:
- **P_form** = probability the batch opens a *new framing*. `compute_p_form`:
  `s` = health of the most-droppable PV slot relative to the best PV.
  Free slot (`active_pvs < max_pv`) → `s=0`; at cap → `s = q_weakest_droppable / q_max`;
  at cap with nothing droppable → `P_form = 0` (cannot open). Then
  `P_form = sigmoid(pform_lambda·(pform_tau − s))`. Healthy fleet → low P_form.
- At most **one** idea per batch becomes `form` (slow PV churn,
  `make_form = rand < P_form`); the rest are `direction`, each assigned a **target
  PV** sampled by `sample_target_pvs` (UCB-weighted softmax over active PVs).

### 3.6 Decision 4 — applying a paradigm
- **`_paradigm_form`** (open a new framing): generate from the global best using a
  *form* prompt (graph summary + global insights). Before committing, **dedup-judge**
  the framing against all `tried_framings` via an LLM: if judged a rediscovery, accept
  it as a new PV only with probability `pv_dedup_accept_prob`; otherwise *redirect* the
  work as a new direction under the matched (or best) PV — so the LLM effort is never
  wasted and the PV cap is respected. Opening a PV at cap first **drops the weakest
  droppable PV** (`place_form` → `drop_weakest_pv`); if nothing can be dropped, it
  falls back to a direction under the strongest PV.
- **`_paradigm_direction`** (new mechanism inside a PV): pick the target PV (sampled or
  re-sampled if stale), build a *direction* prompt (PV info + sibling direction labels
  + per-PV insights + best-in-PV as seed), generate, and `place_direction` — a
  **deterministic** `create_direction` that guarantees a brand-new solution_strategy
  under exactly that PV.

### 3.7 Decision 5 — generative migration (tech-transfer)
Every `migration_interval` iterations, `_migrate_generative` does a **star-from-best**
transfer: the global best is the "immigrant"; for each *other* active PV (up to
`migration_count`), the LLM is asked to evolve that PV's native best **using the
immigrant as context** (not copied in), and the result is `place_and_add(hint="attach")`
into the native PV with `is_migration=True`. Migration improvements feed the adapter
via `receive_external_improvement` (raise best/G, don't credit UCB).

### 3.8 Deterministic placement (why AdaGraph rarely calls LLM_place)
`place_and_add` uses **`attach_under_parent`** (no LLM_place) for exploit/migration
children — this keeps a child in its parent's PV instead of letting LLM_place re-frame
it (which would mis-route migrations and blow past the PV cap). Only the empty-graph
seed and explicit form-spawns go through LLM_place / the deterministic
`create_problem_view` / `create_direction` mutators.

### 3.9 Distilled insights
On every non-migration improvement, `_capture_insight` records a globally-normalized
"what changed" note under the child's solution_strategy, keeping the top
`insight_top_k` by impact. These are injected (per-PV or global) into form/direction
paradigm prompts so the generator builds on what has actually worked.

---

## 4. Side-by-side comparison  *(see Fig. 8)*

| Aspect | **AdaEvolve** | **GraphEvolve** | **AdaGraph** |
|---|---|---|---|
| Population substrate | Fixed/dynamic **islands** + UnifiedArchive each | **ExperienceGraph** (no islands) | ExperienceGraph **problem_views as islands** + archive each |
| Top-level move choice | implicit (always evolve current island) | **circuit-breaker + 2-arm bandit** (exploit / crossover / space) | paradigm-vs-exploit gate (reuses AdaEvolve sampling inside a PV) |
| Explore vs exploit | per-island **search intensity** `I_min+(I_max−I_min)/(1+√G)` → mode split | power-law parent + UCB direction; space-explore on stall | per-PV intensity (same as AdaEvolve) inside the chosen PV |
| "Which container next" | **UCB** over islands (`R/V + c√(lnN/n)`) | **UCB1-Normal** over directions | **grace → UCB** over active PVs |
| Stall signal | global productivity (spawn) + paradigm tracker | `G_global` EMA → `p_space` sigmoid circuit breaker | global paradigm tracker → `P_form` sigmoid |
| New territory | spawn island (copy top-k, new preset) | space-explore → `NEW_FORM`/`NEW_DIR` bandit | generative spawn / paradigm-form (LLM reframe) + dedup |
| Recombination | hybrid context programs | explicit **CROSSOVER** with LLM-verified diverse set | paradigm-direction / migration tech-transfer |
| Migration | ring copy top-k between islands | n/a (single graph) | **generative** star-from-best (LLM, not copy) |
| Diversity enforcement | archive novelty + presets | LLM-verify mechanistic distinctness | dedup-judge framings + deterministic PV/direction placement |
| Persisted decision state | adapter `to_dict` (per-island G/R/V) | `PolicyState` sidecar (bandit weights, pull counts, `G_global`) | adapter dims + `pv_memory`/`insights` + graph |
| LLM_place usage | only if EG attached for paradigm context | every commit (hinted) | rarely — deterministic mutators; LLM_place only for seed/form-spawn |

### Reading guide / where to look
- **Decision math:** `graphevolve/policy.py` (pure, testable) and
  `adaevolve/adaptation.py` (`AdaptiveState`, `MultiDimensionalAdapter`).
- **Loop orchestration:** each backend's `controller.py` (`run_discovery`,
  `_run_iteration`).
- **Population mechanics:** each backend's `database.py`.
- **Tree mechanics shared by GraphEvolve & AdaGraph:**
  `experience_graph/experience_graph.py` (`insert`, `_llm_place`, `_apply_decision`,
  `attach_under_parent`, `create_direction`, `create_problem_view`).
- **Tunables:** `config.py` — `AdaEvolveDatabaseConfig`,
  `GraphEvolveDatabaseConfig`, `AdaGraphDatabaseConfig`.

---

## Appendix A — Diagrams

All figures are plain-text (consistent with the other docs in this folder) so they
render in any viewer. Figures are referenced from the sections above.

### Fig. 0 — Shared per-iteration pipeline (all three backends)

```
                    ┌─────────────────────────────────────────────────────┐
                    │                  CONTROLLER LOOP                      │
                    │                (run_discovery)                        │
                    └─────────────────────────────────────────────────────┘
                                          │  for iteration in range(...)
                                          ▼
   ┌────────────┐   plan    ┌────────────────────────┐  prompt  ┌──────────────┐
   │ POPULATION │──────────▶│ 1. PLAN / SELECT        │─────────▶│ 2. GENERATE  │
   │  (islands  │  parent(s)│   what move? which      │          │  LLM pool →  │
   │   or graph)│◀───┐      │   parent(s)? (DIFFERS)  │          │  child code  │
   └────────────┘    │      └────────────────────────┘          └──────┬───────┘
         ▲           │                                                  │ solution
         │ commit    │ adaptive state                                   ▼
   ┌─────┴──────┐    │ (G, R, V, bandit w, …)              ┌────────────────────────┐
   │ 4. COMMIT  │◀───┘                                     │ 3. EVALUATE            │
   │  store +   │◀────────────────────────────────────────│   user evaluator →     │
   │  update    │                metrics                   │   metrics dict         │
   │  structure │                                          └────────────────────────┘
   └─────┬──────┘
         │  proxy_score = compute_proxy_score(metrics, fitness_key, higher_is_better, …)
         ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ 5. HOUSEKEEPING (end_iteration): rotate active island/PV · migrate on        │
   │    schedule · checkpoint · persist decision state                           │
   └────────────────────────────────────────────────────────────────────────────┘
```

### Fig. 1 — ExperienceGraph: tree schema + LLM_place decision (GraphEvolve & AdaGraph)

```
   TREE SCHEMA (2 internal layers)                 ONE LEAF = ONE EVALUATED PROGRAM
   ───────────────────────────────                 ────────────────────────────────
   ROOT                                             leaf {
   ├── problem_view  "Greedy framing"                 solution_id, score,
   │   ├── solution_strategy "Prefix-tree"            rationale_ref, label, desc
   │   │   ├── leaf  score=0.81                      }
   │   │   └── leaf  score=0.83
   │   └── solution_strategy "Column-stats sort"
   │       └── leaf  score=0.79
   └── problem_view  "ILP framing"
       └── solution_strategy "Branch & bound"
           └── leaf  score=0.74

   insert(solution_id, score, rationale, placement_hint):
        render tree as text ──▶  LLM_place (JSON)  ──▶  _apply_decision
                                       │
        ┌──────────────────────────────┼───────────────────────────────┐
        ▼                              ▼                               ▼
   ATTACH_TO(target_ss)        NEW_BRANCH_UNDER(target,new_path)   SPLIT(target_leaf)
   same PV & same strategy     diverges; new_path = nodes to make  two leaves reveal a
   → append leaf under SS      • 2 entries = new PV + new SS        new strategy → wrap
                               • 1 entry  = new SS under a PV       old+new leaf in a
                                                                    fresh SS node
   placement_hint biases the choice:  "attach" → reuse · "new_form" → new PV ·
   "new_dir" → new SS.   Parse failure ⇒ fallback NEW_BRANCH_UNDER(root, 2×"Unknown").

   AdaGraph adds DETERMINISTIC mutators (no LLM_place):
     attach_under_parent  → forced ATTACH under parent's SS (exploit/migration)
     create_direction     → forced new SS under a given PV   (paradigm-direction)
     create_problem_view  → forced new PV                    (paradigm-form / spawn)
```

### Fig. 2 — AdaEvolve: architecture (islands ↔ adapter)

```
                       MultiDimensionalAdapter  (cross-island coordinator)
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │  per dim k:  visits_k  ·  decayed_visits V_k  ·  decayed_reward R_k (GLOBAL-    │
   │              normalized)        global_best_score        ucb_exploration c     │
   │  select_dimension_ucb:  argmax_k [ R_k/V_k + c·√(ln(N+1)/visits_k) ]            │
   └───────────┬───────────────────────────┬───────────────────────────┬───────────┘
               │ dim 0                      │ dim 1                      │ dim k (spawned)
               ▼                            ▼                            ▼
   ┌───────────────────────┐    ┌───────────────────────┐    ┌───────────────────────┐
   │ ISLAND 0              │    │ ISLAND 1              │    │ ISLAND k              │
   │ UnifiedArchive        │    │ UnifiedArchive        │    │ (preset: underused)   │
   │  (fitness·novelty·    │    │                       │    │  seeded w/ top-5      │
   │   Pareto elite_score) │    │                       │    │                       │
   │ AdaptiveState:        │    │ AdaptiveState         │    │ AdaptiveState (fresh) │
   │  best_score (LOCAL)   │    │                       │    │                       │
   │  G = ρG+(1-ρ)δ²       │    │                       │    │                       │
   └───────────────────────┘    └───────────────────────┘    └───────────────────────┘
         ▲   ring migration top-k  │  i → (i+1) mod K every migration_interval │
         └──────────────────────────┴──────────────────────────────────────────┘
   Spawn (if global productivity < threshold & cooldown passed & islands<max).
   Paradigm breakthrough (orthogonal): on global stall → LLM ideates radical batch.
```

### Fig. 3 — AdaEvolve: intensity → sampling-mode (the explore/exploit dial)

```
   G (accumulated improvement signal, per island)
        low  ───────────────────────────────────────────────▶  high
        │ stagnant island                        productive island │
        ▼                                                          ▼
   intensity = I_min + (I_max−I_min)/(1+√(G+ε))
        high  (≈I_max, explore)                      low (≈I_min, exploit)

   draw r ~ U(0,1):     ├──────────── intensity ───────────┤
   mode =               │   EXPLORATION   │   EXPLOITATION  │  BALANCED │
                        0            intensity   intensity+        1
                                                 (1−int)·0.7
   example intensity=0.4:
        EXPLORATION 40%  │  EXPLOITATION 42%  │  BALANCED 18%
        novelty sample      top-k / Pareto       fitness-weighted
   context programs = local_ratio·(diverse from parent) + rest·(global top)
```

### Fig. 4 — GraphEvolve: the multi-tier decision stack (one iteration)

```
   _plan_action
     │
     ├─ completed < bootstrap_k ?  ──yes──▶  FORCE SPACE_EXPLORE→NEW_FORM
     │                                       (or EXPLOIT if graph empty)
     no
     ▼
   TIER 1  choose_action
     │  p_space = sigmoid(λ·(τ_stag − G_global))         ← circuit breaker
     │
     ├─ rand < p_space ──yes──▶ SPACE_EXPLORE ──▶ TIER 2c choose_space_target
     │                                              p_form = w_new_form/(w_new_form+w_new_dir)
     │                                              ├─ NEW_FORM  (open a problem_view)
     │                                              └─ NEW_DIR   (open SS under best PV)
     no  (2-arm bandit: p_exploit = w_exploit/(w_exploit+w_crossover))
     │
     ├─ EXPLOIT ──▶ TIER 2a choose_direction (UCB1-Normal)
     │                argmax_d [ μ_d + √(16·var_d·ln(t-1)/n_d) + c·√(ln(t-1)/n_d) ]
     │                cold direction (n_d==0) → random (UCB=+∞)
     │                parent  = sample_powerlaw(leaf scores, rank^-alpha)
     │                context = m inspiration leaves ·  siblings = top previous_attempts_n
     │
     └─ CROSSOVER ─▶ TIER 2b _assemble_crossover_set
                      quality-sample candidate ──▶ LLM-verify "mechanistically distinct?"
                      keep if distinct vs ALL selected; stop at crossover_set_size
                      (fail-open) · candidates ≤ k ⇒ skip verify

   _commit:  graph.insert(hint) → tick(t) → update_global(G,best)
             EXPLOIT    → record_direction_pull · reward(EXPLOIT, score>parent_score)
             CROSSOVER  → reward(CROSSOVER, score>base_score)
             SPACE      → verify_space_placement(created new_form/new_dir?) ·
                          reward(target, matched AND score>seed_score)
             bandit:  win → w+=alpha ;  loss → w=max(1,beta·w) ;  clip w_max
```

### Fig. 5 — GraphEvolve: circuit breaker (how stalling opens new territory)

```
   p_space = sigmoid( λ · (τ_stag − G_global) )          (λ=sigmoid_lambda, τ=tau_stag)

   p_space
     1 ┤                                  ████  ← improvement stalled (G_global→0):
       │                              ████        p_space high → SPACE_EXPLORE fires
   0.5 ┤- - - - - - - - - - - - ●- - - - - - -   (crossover point at G_global = τ_stag)
       │                    ████
     0 ┤████  ████  ████████
       └────────────────────────────────────────▶  G_global  (EMA of squared
        high (steady gains)            low (stalled)            normalized improvements)
   G_global ← ρ·G_global + (1−ρ)·max((score−best)/|best|,0)²   ;  fresh run starts at
   initial_g_global so space-explore stays OFF until progress genuinely stalls.
```

### Fig. 6 — AdaGraph: architecture (problem_view = adapter dimension)

```
   ExperienceGraph (FULL MEMORY + visualization)        Adapter / Archives (AdaEvolve reuse)
   ─────────────────────────────────────────────        ─────────────────────────────────────
   ROOT                                                  dim 0 ─ Archive(PV-A) ─ AdaptiveState
   ├── PV-A "framing α"  ◀───── pv_dim / dim_pv ───────▶ dim 1 ─ Archive(PV-B) ─ AdaptiveState
   │   ├── SS  ┌ leaf … (insights: top-k "what changed") dim 2 ─ Archive(PV-C) ─ AdaptiveState
   │   └── SS  └ leaf …                                  ⋮
   ├── PV-B "framing β"                                  active_pvs = {A,B,C}  (live set)
   └── PV-C "framing γ"                                  pv_memory  = every PV ever (dedup)
                                                         pv_grace   = newborns protected
   PV health  q_k = R_k / V_k   (decayed global-normalized reward / decayed visits)
   Per-iteration PV pick:  grace PVs first → else UCB( q_k + c·√(ln ΣN / visits_k) )
   Cap = max_pv; opening a PV at cap first DROPS the weakest droppable PV.
```

### Fig. 7 — AdaGraph: one iteration (form vs direction vs exploit) + migration

```
   _run_iteration (PV already chosen by previous end_iteration: grace → UCB)
     │
     ├─ iteration % migration_interval == 0 ?
     │     └─ _migrate_generative: star-from-best — for each OTHER active PV, LLM
     │        evolves its native best USING global best as context (not a copy);
     │        place_and_add(hint="attach", is_migration) → receive_external_improvement
     │
     ├─ paradigm enabled & globally stagnating ?
     │     └─ generate batch → annotate:
     │          P_form = sigmoid(pform_lambda·(pform_tau − s)),  s = q_weakest_drop / q_max
     │          ├─ ≤1 idea → "form"      (open new framing)
     │          └─ rest    → "direction" (each → a UCB-sampled target PV)
     │
     ├─ active paradigm ?  ──yes──▶ _apply_paradigm
     │     ├─ form:      generate from global best → DEDUP-judge vs tried framings
     │     │             duplicate? accept new PV only w/ pv_dedup_accept_prob,
     │     │             else REDIRECT as a direction under matched/best PV
     │     │             (at cap → drop_weakest_pv first) → create_problem_view
     │     └─ direction: best-in-PV as seed + sibling dirs + per-PV insights
     │                   → create_direction (deterministic new SS in that PV)
     │
     └─ else  _run_normal_step  (AdaEvolve intensity→mode sampling INSIDE current PV)
                 → place_and_add(hint="attach") → attach_under_parent (stays in PV)

   finally end_iteration: grace tick → choose next active PV (grace → UCB)
```

### Fig. 8 — "Same skeleton, different organs" (what each backend swaps in)

```
                         AdaEvolve            GraphEvolve              AdaGraph
   container          fixed/dyn islands     ExperienceGraph        graph problem_views
                                            (no islands)           (= dimensions)
   pick container     UCB over islands      UCB1-Normal over        grace → UCB over
                                            directions              active PVs
   pick move          (always evolve)       circuit-breaker +       paradigm-gate
                                            2-arm bandit            (form/dir/exploit)
   in-container       intensity→mode        power-law parent +      intensity→mode
   explore/exploit    (G-based dial)        UCB direction           (reused from Ada)
   new territory      spawn island          space-explore bandit    generative spawn /
                      (copy top-k)          (new_form/new_dir)      paradigm-form + dedup
   recombine          hybrid context        CROSSOVER + LLM-verify  migration tech-
                                            distinct set            transfer (LLM)
   diversity guard    archive novelty       LLM mechanistic verify  dedup-judge framings
   decision state     adapter G/R/V         PolicyState sidecar     adapter + pv_memory
                                            (bandit w, pulls,        + insights + graph
                                             G_global)
```
