# AdaGraph — Architecture & Algorithm

AdaGraph is **AdaEvolve's adaptive zeroth-order search with the ExperienceGraph as
the population substrate**. It reuses AdaEvolve's machinery verbatim — per-dimension
improvement signal `G`, search-intensity adaptation, UCB selection with
decayed global-normalised rewards, the `UnifiedArchive` quality-diversity store, and
the paradigm-breakthrough ideation — but the "islands" are no longer a fixed list:
they are the **`problem_view` (PV) nodes of the ExperienceGraph**, created and
retired dynamically.

Code: `skydiscover/search/adagraph/{controller,database}.py`,
`skydiscover/context_builder/adagraph/`, `skydiscover/experience_graph/` (shared),
config `AdaGraphDatabaseConfig` (`skydiscover/config.py`), registered as search type
`adagraph` in `skydiscover/search/route.py`.

---

## 1. Motivation

Two observations drove the design:

1. **The original GraphEvolve had a "complexity ratchet."** Every operator (space
   explore, crossover, exploit) ADDED complexity; nothing removed it; there was no
   selection pressure (the graph kept every leaf, uncapped); and a single global
   stagnation signal meant the bandit never learned (weights stayed at 1.0). Runs
   sprawled into 10+ baroque-but-similar framings and never isolated the clean
   winning mechanism.
2. **AdaEvolve already solves the hard parts** — adaptive explore/exploit via `G`,
   fair cross-island credit via global-normalised UCB rewards, archive eviction as
   real selection pressure, and paradigm breakthrough as deep reframing. The gap was
   purely the population *substrate*.

AdaGraph therefore **forks AdaEvolve and swaps only the substrate**: the graph
organises solutions by *framing* (`problem_view`) → *strategy* (`solution_strategy`)
→ *leaf*, and AdaEvolve's per-island adaptation runs per-PV.

---

## 2. The unifying principle

Everything in AdaGraph is valued by **global-normalised magnitude with decay**
(AdaEvolve's "avoid poor-island bias", eqs. 4–6 of the AdaEvolve paper). A raw local
delta `δ` is misleading: a `+0.5` gain on a weak direction (baseline 1) looks bigger
than a `+10` gain on a strong one (baseline 100), yet the latter is globally more
valuable. So a delta is always normalised by the **global best**:

```
r = (f' − f*_k) / f*_global        (per-improvement reward, AdaEvolve eq. 4)
R_k = ρ·R_k + r,  V_k = ρ·V_k + 1   (decayed reward / visits, eq. 5)
UCB_k = R_k/V_k + C·sqrt(ln N / n_k) (selection, eq. 6)
```

This single currency drives **three** AdaGraph decisions:
- **PV selection** — UCB over active PVs (`R_k/V_k + exploration`).
- **PV health** for the form-vs-direction split — a PV's `R_k/V_k`.
- **Insight distillation** — "what changed" entries ranked by `Δ_norm = Δ/|f*_global|`.

All of this lives in the inherited `MultiDimensionalAdapter`
(`search/adaevolve/adaptation.py`); AdaGraph reuses it as-is.

---

## 3. Granularity: three tiers of creation

The central design choice is **what gets created, how often, and how distinct**:

| Tier | Creates | Frequency | Trigger | Placement |
|------|---------|-----------|---------|-----------|
| 1. **Refine** | a leaf under an existing `solution_strategy` | most common | exploit (UCB-selected PV, intensity → exploitation) | `attach` (deterministic, under parent's SS) |
| 2. **New direction** | a new `solution_strategy` (SS) inside a PV, mechanistically distinct | frequent | direction-level paradigm (sampled PV) | `create_direction` (deterministic, new SS under the PV) |
| 3. **New framing** | a new `problem_view` (PV) | rare / deep | form-level paradigm (prob `P_form`, with dedup + drop) | `create_problem_view` (deterministic, new PV under root) |

Rationale: a new **PV** is expensive and error-prone — create it sparingly, only to
go deep on a genuinely new model. A new **direction** is how a framing's space is
actually vetted — create it often and force it to differ from sibling directions.
Plain **exploit** stays within its PV (it tends to refine anyway).

`exploit-exploration` (intensity → exploration mode) is **deliberately left
unchanged** from AdaEvolve: it still samples a novel parent and stays within the PV;
the heavy lifting of "genuinely new, distinct direction" is done by direction-level
paradigm, not by exploit.

---

## 4. Data structures (`AdaGraphDatabase`)

`island_idx == adapter dimension == PV slot`, so almost all inherited
`AdaEvolveDatabase` methods work unchanged. Adapter dimensions are **append-only**;
a "dropped" PV keeps its dimension/archive but leaves the active set.

- `archives[idx]` — per-PV `UnifiedArchive` (live population, capped at
  `population_size`, elite + novelty eviction = the real selection pressure).
- `adapter` — `MultiDimensionalAdapter`; dim `idx` holds the PV's `G`, intensity,
  decayed reward/visits.
- `dim_pv: List[str]`, `pv_dim: Dict[str,int]` — slot ↔ pv_id mapping.
- `active_pvs: List[str]` — currently-live PVs (≤ `max_pv`). Selection, `P_form`,
  sampling operate only over these.
- `pv_grace: Dict[str,int]` — a newborn PV is force-selected for `pv_grace_period`
  iterations before UCB can starve it (and before it can be dropped).
- `pv_memory: Dict[str, {label, best_score, status, dim}]` — **every** framing ever
  tried (live + dropped), for dedup and revival.
- `insights: Dict[ss_id, List[{iter, dnorm, what}]]` — distilled "what changed",
  top-`insight_top_k` by `dnorm` per solution_strategy.
- The **ExperienceGraph** itself is the *full knowledge memory*: every accepted
  program becomes a leaf and is never pruned (drives paradigm summaries +
  visualization). Archive eviction never removes a graph leaf. → the graph
  visualization shows full history; the live per-PV population is the archive.

---

## 5. Per-iteration algorithm

```
run_discovery:
  seed_graph()                      # insert pre-loaded seed → PV #0 (LLM_place)
  bootstrap_pvs()                   # open up to n_init framings via form prompt
  for each iteration:
      _run_iteration()
      database.end_iteration()      # pick next current PV (grace → UCB over active)

_run_iteration:
  if iteration % migration_interval == 0:  migrate_generative()      # §8
  if is_paradigm_stagnating():             generate_and_annotate()   # §7
  if has_active_paradigm():
        child = apply_paradigm()    # form OR direction (annotated)
  else:
        child = run_normal_step()   # exploit within current PV → place_and_add(attach)
  finish_iteration()                # monitor, prompt log, checkpoint, stats
```

Each iteration produces **either** a paradigm child (tier 2/3) **or** an exploit
child (tier 1) — exactly as AdaEvolve consumes iterations with active paradigms.

`end_iteration` selects the next PV: any active PV still in grace wins; otherwise
UCB over **active** dims (`_select_active_pv_ucb`, cold PVs first). No generative
spawn, no copy-migration (both replaced by the mechanisms below).

---

## 6. PV lifecycle

- **Bootstrap.** The seed program is inserted via `LLM_place` (empty-tree branch),
  creating PV #0. Then `_bootstrap_pvs` calls the **form prompt** up to `n_init−1`
  more times (bounded attempts) to open initial framings.
- **Cap.** At most `max_pv` (=5) **active** PVs.
- **Drop to replace.** Opening a new framing at cap evicts the **weakest droppable**
  PV (`drop_weakest_pv`): lowest `R_k/V_k` among PVs that are past grace and do not
  hold the global best. The dropped PV → `pv_memory` (status=`dropped`); its leaves
  stay in the graph; its slot is freed (left the active set). If nothing is
  droppable, the would-be framing falls back to a **direction** under the strongest
  PV (cap never exceeded).
- **Dedup (10%).** Before opening a framing, an LLM judge (`guide_llms`) compares it
  against `pv_memory`. If judged a duplicate of a tried framing, it is accepted only
  with probability `pv_dedup_accept_prob` (0.1); otherwise the work is **redirected
  as a direction** under the matched / best PV (not discarded).
- **Revive.** If a new framing matches a *dropped* PV id and passes, `ensure_pv_slot`
  re-activates that PV slot rather than creating a fresh one.

---

## 7. Paradigm breakthrough (tier 2 & 3)

**Trigger (unchanged from AdaEvolve, global):** `ParadigmTracker.is_paradigm_stagnating()`
— over the last `paradigm_window_size` additions, the **global best** improved in
`< paradigm_improvement_threshold` fraction (i.e. it has stalled), and no batch is
still active. One firing produces `paradigm_num_to_generate` (=3) ideas, each used
`paradigm_max_uses` (=2) times.

**Inputs to ideation** (`_generate_paradigms_if_needed`, reused): current best
solution + score, previously-tried ideas, evaluator feedback, **the ExperienceGraph
summary** (the map of all framings tried, with scores — the graph's value-add), and
optional paper knowledge (off for cloudcast). Plus, baked in: the task description
and the full evaluator source.

**Form-vs-direction split (AdaGraph, per batch).** The global stall triggers the
batch; the *split* is a soft probability over the PV fleet state:

```
P_form = sigmoid( pform_lambda · (pform_tau − s) )
  s = health of the most-droppable slot relative to the best PV:
      free slot          → s = 0  (P_form high; no drop needed)
      at cap, droppable   → s = min(R_k/V_k over droppable) / max(R_k/V_k)
      at cap, none droppable → P_form = 0  (cannot open)
```

Healthier fleet → higher `s` → lower `P_form`. Per batch we draw **one** Bernoulli
`P_form` → at most **one** form idea (slow PV churn); the rest are direction ideas.
Each direction idea is assigned a **target PV sampled by UCB** (`sample_target_pvs`:
`R_k/V_k + exploration`, weighted, without replacement) so promising-but-under-vetted
PVs get directions too. Annotations are stored on the idea dict (`_ag_mode`,
`_ag_target_pv`).

**Application** (`_apply_paradigm`, one idea per iteration):
- *direction*: parent = target PV's archive best; prompt = `build_direction_prompt`
  (keeps the PV framing, shows sibling SS, demands a distinct mechanism, injects the
  PV's distilled insights); placed via `create_direction` (new SS under the PV).
- *form*: parent = global best; prompt = `build_form_prompt` (new framing, global
  insights); dedup-judged; placed via `create_problem_view` (drop + cap) or
  redirected to a direction.

**Why this resolves the earlier ambiguity:** paradigm *fires* on GLOBAL-best stall;
PV *health* (form vs direction) is measured by per-PV `R_k/V_k`. They are different
signals — a PV still climbing its own hill earns reward (so it stays "healthy" and
gets deepened) even while the global best is flat — so "all PVs fine → all
direction" and "a PV is dead → allow one form" are both reachable without
circularity.

---

## 8. Placement (deterministic)

All in-PV placement is **deterministic** (no LLM_place), which is what keeps the PV
cap honest and migrations on-target:

- `attach_under_parent` — exploit/migration: append a leaf under the parent's SS.
- `create_direction` — direction paradigm: new SS under a given PV + leaf.
- `create_problem_view` — form paradigm/bootstrap: new PV → SS → leaf under root.

`LLM_place` is used **only** for the empty-graph seed. (Earlier, routing
exploit/migration through `LLM_place` with a soft "attach" hint let the LLM re-frame
children — that both mis-routed migrations into "Initial Seed" and blew the PV cap to
10. Deterministic placement fixed both.)

---

## 9. Migration — generative tech-transfer

Every `migration_interval`, **star-from-best** over active PVs: the immigrant is the
global best; for each other active PV, generate a child with **parent = that PV's
native best** (keeps the destination framing) and the **immigrant only as context**
(imports its technique). The child is `attach`-placed in the destination PV and the
adapter records it via `receive_external_improvement` (updates best/`G` but **not**
UCB visits/rewards — the PV did not earn the credit). This mirrors AdaEvolve
migration but, because verbatim copy would violate the graph's "one framing per PV"
invariant, it is *generative* and *framing-preserving*. No crossover operator: the
global-top context already provides soft cross-pollination every generation.

---

## 10. Distillation — "what changed"

When a child improves over its parent (`Δ > 0`), AdaGraph records the **change** with
a **global-normalised magnitude**:

```
Δ_norm = (child_score − parent_score) / |f*_global|
insights[child_SS] += {iter, Δ_norm, what_changed}   (top-K by Δ_norm)
```

`what_changed` = the diff summary (diff-based) or the change note. Ranking by
`Δ_norm` (not raw `Δ`) avoids "poor-direction bias" — trivial edits on weak
directions don't flood the memory; globally-impactful edits surface. Distilled
insights are injected into prompts:
- per-SS / per-PV insights → direction prompts ("what reliably helps in this
  framing").
- global top insights → form / bootstrap prompts.

(Exploit-prompt injection is a natural extension; currently insights flow into the
paradigm/form/direction prompts that AdaGraph builds directly.)

---

## 11. Config (`AdaGraphDatabaseConfig`, inherits `AdaEvolveDatabaseConfig`)

| Key | Default | Meaning |
|-----|---------|---------|
| `population_size` | 20 | per-PV archive size (live population) |
| `num_islands` | 2 | `n_init` PVs to bootstrap |
| `max_islands` | 5 | `max_pv`: cap on active PVs |
| `use_dynamic_islands` | true | (legacy gate; generative spawn removed) |
| `pv_grace_period` | 5 | iterations a newborn PV is protected |
| `pform_tau` / `pform_lambda` | 0.3 / 8.0 | `P_form = σ(λ(τ−s))` |
| `pv_dead_ratio` | 0.1 | a PV is "dead" if `R/V < ratio·best R/V` |
| `pv_dedup_accept_prob` | 0.1 | accept prob for a duplicate framing |
| `insight_top_k` | 5 | distilled edits kept per SS / PV |
| `migration_interval` / `migration_count` | 15 / 5 | tech-transfer cadence / budget |
| `use_paradigm_breakthrough` | true | + `paradigm_window_size`/`_improvement_threshold`/`_max_uses`/`_num_to_generate` |
| `intensity_min` / `intensity_max` / `decay` | 0.15 / 0.5 / 0.9 | per-PV explore/exploit (inherited) |

---

## 12. What is reused vs new

**Reused unchanged** (imported, not copied): `MultiDimensionalAdapter` /
`AdaptiveState` (adaptation), `UnifiedArchive` (archive), `ParadigmGenerator` /
`ParadigmTracker` (paradigm), `ExperienceGraph` (graph), `AdaEvolveContextBuilder`
(exploit/migration prompts), and most of `AdaEvolveDatabase`/`AdaEvolveController`.

**New in AdaGraph:**
- `AdaGraphDatabase` — PV-as-island substrate: PV slots/active-set, `place_*`
  (attach/direction/form), drop/dedup-memory, `compute_p_form`, `sample_target_pvs`,
  per-PV UCB over active dims, distillation store, `add` override (seed) +
  `islands=[]` (safe inherited fallbacks).
- `AdaGraphController` — `run_discovery` (seed + bootstrap), `_run_iteration`
  (migration → paradigm-annotate → apply-paradigm xor exploit), `_apply_paradigm`
  (form/direction routing + dedup), generative migration over active PVs.
- `AdaGraphContextBuilder` + templates `form_reframe.txt`, `direction.txt`.
- Deterministic graph mutators `create_direction` / `create_problem_view` /
  `attach_under_parent` on `ExperienceGraph`.

---

## 13. Files

```
skydiscover/search/adagraph/database.py        # AdaGraphDatabase
skydiscover/search/adagraph/controller.py      # AdaGraphController
skydiscover/context_builder/adagraph/builder.py
skydiscover/context_builder/adagraph/templates/{form_reframe,direction}.txt
skydiscover/experience_graph/experience_graph.py  # + attach_under_parent / create_direction / create_problem_view
skydiscover/config.py                           # AdaGraphDatabaseConfig
skydiscover/search/route.py                     # register "adagraph"
skydiscover/cli.py                              # _SEARCH_CHOICES += "adagraph"
benchmarks/ADRS/cloudcast/reproduce/adagraph/config_adagraph.yaml
benchmarks/ADRS/cloudcast/reproduce/{run,visualize}_adagraph.sh
```

---

## 14. Known limitations / future work

- Insight injection currently reaches paradigm/form/direction prompts; exploit
  prompts (inherited path) do not yet receive per-SS insights.
- Dedup uses one `guide_llms` judge call per form attempt (form is rare, so cost is
  low); an embedding signature is a cheaper alternative.
- Dropped-PV revival re-activates the slot but does not re-seed from the archived
  best; re-seeding would give a stronger second chance.
- The whole paradigm-routing path is verified offline (DB mechanics, prompt
  formatting, imports); end-to-end behaviour needs a live LLM+evaluator run on
  cloudcast to validate framing/direction balance and `P_form` calibration.
