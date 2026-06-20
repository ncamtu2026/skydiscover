# Plan: GraphEvolve — search backend mới điều khiển bằng policy trên experience graph

## Context

Bạn đã propose một search policy nhiều tầng trong
[advance_graph_evolve.md](analysis/architecture_analysis/advance_graph_evolve.md)
(circuit-breaker theo stagnation → bandit 2-arm exploit/crossover → UCB chọn solution
direction → power-law chọn parent → MMR/LLM chọn 5 solution để crossover → space-explore).
Mục tiêu là biến nó thành **một method mới hoàn toàn, code tách bạch**, dùng lại vòng lặp
kiểu OpenEvolve/AdaEvolve nhưng **bỏ hẳn cơ chế island** — thay vào đó dùng chính
`ExperienceGraph` (đã code tại [skydiscover/experience_graph/](skydiscover/experience_graph/))
làm "population". Backend này chạy song song với `adaevolve/`, không sửa code adaevolve.

### Các chốt thiết kế đã thống nhất với bạn
1. **Arm của UCB = node `solution_strategy`** (giữ graph 2 tầng hiện tại, KHÔNG thêm tầng
   `mechanism`). Mapping khái niệm:
   - proposal *paradigm / cách-nhìn (formulation)* → node `problem_view`
   - proposal *solution direction (mechanism)* → node `solution_strategy` (= arm)
   - Tier 2c *new-formulation vs new-direction* → `NEW_BRANCH` 2-entry (new `problem_view`)
     vs 1-entry (new `solution_strategy` dưới `problem_view` cũ) — đã có sẵn trong graph.
   - *paradigm breakthrough* giữ nguyên là cờ `is_paradigm_breakthrough` (sự kiện sinh đặc
     biệt), không phải một tầng cây.
2. **Stats để sidecar** (`PolicyState`), không sửa `GraphNode` → graph vẫn neutral/read-only.
3. **Bỏ island**: KHÔNG dùng lại `AdaEvolveDatabase`/`UnifiedArchive`/migration. Graph là
   nơi lưu cấu trúc; một dict phẳng lưu `Program`.
4. **Full design ngay** (cả 4 tầng).
5. **Bootstrap** = seed program trong config + K vòng exploit-from-seed (LLM mutate seed) để
   đổ đầy graph, rồi policy đầy đủ mới bật.
6. **Embedding (Tier 2b)** = dùng `create_embedder` lọc thô ứng viên (diversity prefilter),
   rồi đưa shortlist vào **LLM judge** chọn tập 5 cuối — thay cho công thức MMR cosine thuần.
7. **Arm-stability**: score-stats (μ, σ², f*) **derive on-the-fly từ các leaf** đang nằm dưới
   node `solution_strategy` (bền với SPLIT); chỉ pull-count `n_k` lưu theo `node_id`, node mới
   sinh ra `n_k=0` → UCB=∞ → tự được ưu tiên (đúng cold-start trong proposal).
8. **Sinh code**: full-rewrite cho cả 3 action, mỗi action một template riêng.

---

## Kiến trúc & file

Tạo package mới `skydiscover/search/graphevolve/` (tên có thể đổi):

```
skydiscover/search/graphevolve/
  __init__.py
  policy.py        # GraphEvolvePolicy + PolicyState (toàn bộ logic 4 tầng, thuần)
  database.py      # GraphEvolveDatabase(ProgramDatabase): store + graph + policy-state
  controller.py    # GraphEvolveController(DiscoveryController): vòng lặp chính
  templates/
    mutate.txt          # exploit: refine 1 parent
    crossover.txt       # tổng hợp 5 solution
    space_explore.txt   # generate-new (new framing / new direction) + graph summary
```

### 1. `policy.py` — `PolicyState` (sidecar) + `GraphEvolvePolicy`

`PolicyState` (dataclass, serialize JSON cạnh graph trong `output_dir`):
- `w_exploit: float = 1.0`, `w_crossover: float = 1.0` (cố định) — bandit Tier 1.2
- `w_new_form: float = 1.0`, `w_new_dir: float = 1.0` (cố định) — bandit Tier 2c
- `pull_count: Dict[str, int]` — `n_k` theo `solution_strategy` node_id
- `G_global: float`, `best_global: float`, `t: int` — circuit breaker Tier 1.1
- siêu tham số đọc từ config (xem dưới)

`GraphEvolvePolicy` (thuần, nhận dữ liệu từ database):
- `choose_action(t)` — Tier 1: `P(space)=sigmoid(λ(τ_stag − G_global))` (bản mềm, giữ
  reachability); nếu không space thì bandit 2-arm `α_E = w_exploit/(w_exploit+w_crossover)`.
- `choose_direction(directions, t)` — Tier 2a: cold (`n_k=0`) → random; else
  UCB1-Normal `μ_k + sqrt(16·σ²_k·ln(t−1)/n_k)`. μ_k/σ²_k **derive từ leaves** của node.
- `sample_parent(direction, alpha)` — Tier 2a: power-law theo rank điểm các leaf.
- `choose_crossover_set(directions, k=5)` — Tier 2b: embedder lọc thô (prefilter theo
  quality + loại trùng embedding) → LLM judge chọn `min(k, |directions|)` representative.
- `choose_space_target()` — Tier 2c: bandit 2-arm new-form vs new-dir.
- `update_after_eval(action, ctx, child_score, parent_score, seed_score)` — cập nhật mọi tầng
  vừa dùng: `Δ_t` bandit (so parent/seed), `pull_count` của direction, `G_global`/`best_global`.

Clip `w_exploit ≤ w_max`. Hằng số mặc định: `α=β=0.5`, `c`/`ucb` theo config.

### 2. `database.py` — `GraphEvolveDatabase(ProgramDatabase)`

Sở hữu: `programs: Dict[str, Program]` (store phẳng), một `ExperienceGraph` (tự tạo từ
`config.experience_graph` + `experience_graph_models` pool), một `PolicyState`.
- `add(program, iteration)` (abstract): lưu vào dict, `_update_best_program`. (graph.insert
  để controller gọi async — theo đúng cách [controller.py adaevolve](skydiscover/search/adaevolve/controller.py:386).)
- `sample(...)` (abstract): trả về thin default (best parent) để thỏa interface; policy thật
  được controller gọi qua API giàu hơn dưới đây.
- Helper đọc graph (đọc `experience_graph.root`):
  `list_directions()` → các node `field_name=="solution_strategy"`;
  `leaves_under(node)`; `representative_leaf(node)` (best score);
  `program_of(leaf)` (qua `solution_id` → `programs`).
- Lưu/khôi phục `PolicyState` (JSON) khi save/load.

Tái dùng: `Program`, `ProgramDatabase` ([base_database.py](skydiscover/search/base_database.py:75)),
`ExperienceGraph` ([experience_graph.py](skydiscover/experience_graph/experience_graph.py)),
`create_embedder` ([embedder.py](skydiscover/knowledge/embedder.py:85)).

### 3. `controller.py` — `GraphEvolveController(DiscoveryController)`

Kế thừa base controller ([default_discovery_controller.py](skydiscover/search/default_discovery_controller.py:49))
để dùng lại `_call_llm`, evaluator wiring, `_parse_llm_response`, `_create_child_program`,
checkpoint. Override `run_discovery`:

**Bootstrap (K vòng):** mutate seed program (template `mutate.txt`) → evaluate → `db.add` →
`await graph.insert(...)`. Không chạy policy, chỉ exploit-from-seed.

**Vòng chính:**
```
a = policy.choose_action(t)
if a == EXPLOIT:
    dir = policy.choose_direction(db.list_directions(), t)
    parent = policy.sample_parent(dir, alpha)
    prompt = render("mutate.txt", parent, ...)
elif a == CROSSOVER:
    S = policy.choose_crossover_set(db.list_directions())   # embedder prefilter + LLM judge
    prompt = render("crossover.txt", S, ...)
elif a == SPACE_EXPLORE:
    tgt = policy.choose_space_target()                      # new-form | new-dir
    summary = await graph.summarize()
    prompt = render("space_explore.txt", tgt, summary, seed_ref, ...)
child = parse(await _call_llm(prompt))     # full-rewrite, trích EVOLVE-BLOCK
score = await evaluator.evaluate_program(child.solution)
db.add(child); await graph.insert(child.id, score, rationale, parent_id=...)
policy.update_after_eval(a, ctx, score, parent_score, seed_score)
```
Lưu `PolicyState` + graph theo `checkpoint_interval`; `graph.save_shutdown` khi kết thúc.

### 4. Templates (3 file)
Reuse template engine của `context_builder` (đọc file + format placeholder). Mỗi action một
prompt: `mutate` (refine 1 parent), `crossover` (tổng hợp 5 solution, để LLM tự quyết cách
lai), `space_explore` (sinh hướng mới theo `tgt` + graph summary, đối chiếu seed_ref).

### 5. Hạ tầng chung cần đụng tới (nhỏ)
- [route.py](skydiscover/search/route.py): `register_database("graphevolve", GraphEvolveDatabase)`
  + `register_controller("graphevolve", GraphEvolveController)`.
- [config.py](skydiscover/config.py): thêm `GraphEvolvePolicyConfig` (các siêu tham số:
  `bootstrap_k`, `ucb_c`, `powerlaw_alpha`, `bandit_alpha/beta`, `w_max`, `tau_stag`,
  `sigmoid_lambda`, `crossover_set_size`, `embedder` settings) và gắn vào `Config`; tái dùng
  `experience_graph` config + `experience_graph_models` pool đã có.
- [code_utils.py](skydiscover/utils/code_utils.py): thêm helper nhỏ
  `extract_evolve_block(solution) -> str` (trích đoạn giữa `EVOLVE-BLOCK-START/END`) cho
  embedding ở Tier 2b — dùng marker do [prepare.py](skydiscover/utils/prepare.py:33) đặt.
- YAML mẫu: thêm `configs/graphevolve.yaml` (hoặc một config dưới
  `benchmarks/ADRS/cloudcast/reproduce/memory/`) đặt `search.type: graphevolve`.

---

## Những gì KHÔNG làm
- Không sửa `adaevolve/` (controller/database/archive).
- Không thêm tầng `mechanism` vào graph; không sửa schema/prompt của `ExperienceGraph`.
- Không dùng island/migration/`UnifiedArchive`.
- Không claim regret bound; mục tiêu lý thuyết chỉ là reachability + asymptotic convergence
  (theo §5 của proposal): dùng circuit-breaker sigmoid + giữ `w_crossover=1.0`.

---

## Verification (end-to-end)
1. Chạy backend mới trên một benchmark nhẹ (cloudcast) với `search.type: graphevolve`,
   `max_iterations` nhỏ (vd 30–50), `bootstrap_k` ~5:
   `skydiscover ... --config configs/graphevolve.yaml` (hoặc đường chạy reproduce hiện có).
2. Kiểm tra artefacts trong `output_dir`:
   - `experience_graph.json` + `experience_graph_events.jsonl` tăng dần (graph được đổ đầy).
   - `policy_state.json` cập nhật: `pull_count` phân bố theo direction, `w_exploit` thay đổi,
     `G_global`/`best_global` tiến triển.
   - log mỗi vòng in ra `action` đã chọn (EXPLOIT/CROSSOVER/SPACE_EXPLORE) → xác nhận cả 3
     nhánh được kích hoạt.
3. Sanity theo từng tầng:
   - direction mới (`n_k=0`) phải được pull ít nhất 1 lần (UCB=∞).
   - khi best_global đứng yên nhiều vòng → `P(space)` tăng, space-explore kích hoạt.
   - crossover thực sự nhận ≤5 representative khác direction.
4. So điểm best cuối với một run `adaevolve` cùng budget để có baseline định tính.
5. Unit test thuần cho `policy.py` (không cần LLM): cold-start UCB=∞, power-law `alpha=0`→
   uniform / `alpha→∞`→ luôn top, bandit `Δ=0` decay `max(1.0, β·w)`, sigmoid circuit breaker
   đơn điệu theo `G_global`.
