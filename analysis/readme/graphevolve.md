# GraphEvolve — Hướng dẫn sử dụng

Một **search backend mới hoàn toàn**, điều khiển vòng lặp evolve bằng một *policy nhiều tầng* chạy trực tiếp trên [ExperienceGraph](experience_graph.md). Khác AdaEvolve/OpenEvolve: **không có island / migration / archive** — chính cái graph (`problem_view → solution_strategy → leaf`) đóng vai "population", và policy quyết định mỗi iteration làm gì.

Thiết kế lý thuyết đầy đủ: [analysis/architecture_analysis/advance_graph_evolve.md](../architecture_analysis/advance_graph_evolve.md).

---

## 0. Mỗi iteration làm gì

```
loop:
  a = chọn_action()                      # Tier 1: circuit-breaker + bandit 2-arm
  if a == EXPLOIT:
      dir   = chọn_direction_UCB()       # Tier 2a: UCB1-Normal trên solution_strategy
      parent= sample_parent_power_law()  #          power-law trong direction
      child = LLM_mutate(parent, context_solutions, previous_attempts)
  elif a == CROSSOVER:
      S     = sample_quality + LLM_verify # Tier 2b: lấy mẫu xác suất + LLM lọc diversity
      child = LLM_crossover(S)            #          tổng hợp k nguồn khác cơ chế
  elif a == SPACE_EXPLORE:
      tgt   = new_form | new_dir          # Tier 2c: bandit 2-arm
      child = LLM_generate_new(tgt, graph_summary, exemplars, seed=global_best)

  score = evaluate(child)
  insert_into_graph(child, score)         # graph tự đặt node (LLM_place)
  update_policy(a, score, ...)            # cập nhật bandit/UCB/stagnation
```

Ánh xạ khái niệm (proposal ↔ code, **graph giữ 2 tầng**):
- *paradigm / cách-nhìn (formulation)* → node `problem_view`
- *solution direction (mechanism)* = **arm của UCB** → node `solution_strategy`
- *paradigm breakthrough* → cờ `is_paradigm_breakthrough` (không phải tầng cây)

---

## 1. Bật trong config

Đặt `search.type: graphevolve`. Backend này **luôn dùng full-rewrite** (đặt `diff_based_generation: false`) và **luôn bật ExperienceGraph** (graph là population).

```yaml
language: python
diff_based_generation: false

llm:
  models:            [{ name: glm-4.7, weight: 1.0 }]
  guide_models:      [{ name: glm-4.7, weight: 1.0 }]   # dùng cho LLM-verify diversity (Tier 2b)
  experience_graph_models: [{ name: glm-4.7, weight: 1.0 }]  # dùng cho LLM_place của graph

search:
  type: graphevolve
  database:
    # Bootstrap: số vòng exploit-from-seed trước khi bật policy đầy đủ
    bootstrap_k: 5

    # Tier 1 — circuit breaker (stagnation) + bandit 2-arm action
    tau_stag: 0.01            # ngưỡng stagnation để bật space-explore
    sigmoid_lambda: 100.0     # độ "mềm" của circuit breaker
    decay_rho: 0.9            # decay EMA của tín hiệu stagnation toàn cục
    initial_g_global: 1.0     # khởi tạo "non-stagnant" để space-explore KHÔNG bật sớm
    bandit_alpha: 0.5         # thưởng cộng cho arm thắng
    bandit_beta: 0.5          # decay nhân cho arm thua
    w_max: 10.0               # clip trọng số bandit động

    # Tier 2a — UCB direction + power-law parent/context
    ucb_c: 1.0                # hằng số exploration (floor UCB)
    powerlaw_alpha: 1.0       # số mũ rank khi sample parent/context (0=uniform, ∞=luôn best)
    context_solutions_m: 2    # số inspiration code đưa vào prompt exploit
    previous_attempts_n: 5    # số "previous attempts" (Δ compact) trong direction

    # Tier 2b — crossover set
    crossover_set_size: 5     # số nguồn tối đa cho 1 lần crossover
    crossover_max_attempts: 8 # trần số lần sample+verify; chạm trần thì dừng (chấp nhận < k)

    # Error retry (giống AdaEvolve)
    enable_error_retry: true
    max_error_retries: 2

    # Hướng metric (tái dùng compute_proxy_score)
    higher_is_better: {}
    fitness_key: null
    pareto_objectives: []
```

> **Nguyên tắc bandit:** chỉ có *một* trọng số động mỗi tầng (exploit, new_form); arm còn lại (crossover, new_dir) **cố định = 1.0** làm mỏ neo — đảm bảo reachability và tránh trọng số tăng vô hạn.

---

## 2. Chạy

### CloudCast (có sẵn script)
```bash
cd benchmarks/ADRS/cloudcast
bash reproduce/run_graphevolve.sh            # ITERATIONS / MODEL / API_BASE / RUNS override qua env
# → outputs/reproduce/graphevolve/graphevolve_<timestamp>/
```

### Bất kỳ benchmark nào
```bash
uv run skydiscover-run initial_program.py evaluator/evaluator.py \
  -c <config.yaml> -s graphevolve -m glm-4.7 --api-base <url> -i 100 \
  -o outputs/my_graphevolve_run
```

Seed program (`initial_program.py`) được eval + add vào store trước, rồi **bootstrap** insert nó vào graph và chạy `bootstrap_k` vòng exploit-from-seed để đổ đầy graph; sau đó policy đầy đủ mới bật.

---

## 3. Output files

```
output_dir/
├── experience_graph.json              # full tree hiện tại (resume)
├── experience_graph_events.jsonl      # event mỗi insert + summarize (CÓ THÊM policy_action)
├── experience_graph_snapshots/        # snapshot tree theo interval
└── graphevolve_policy.json            # ← sidecar PolicyState (chỉ GraphEvolve)
```

### `graphevolve_policy.json` — trạng thái policy (sidecar)
```jsonc
{
  "w_exploit": 2.5,        // trọng số bandit action động (crossover neo = 1.0)
  "w_crossover": 1.0,
  "w_new_form": 1.0,       // trọng số bandit space động (new_dir neo = 1.0)
  "w_new_dir": 1.0,
  "pull_count": { "<solution_strategy_node_id>": 7, ... },  // n_k cho UCB
  "G_global": 0.42,        // tín hiệu stagnation toàn cục (EMA)
  "best_global": 0.871,
  "t": 83                  // đồng hồ iteration cho UCB
}
```
> Score-stats của direction (μ/σ²/f*) **không** lưu ở đây — chúng được *derive on-the-fly* từ các leaf dưới mỗi node, nên bền khi graph bị SPLIT. Chỉ `pull_count` + trọng số bandit là state.

### `experience_graph_events.jsonl` — thêm trường policy
Mỗi insert event của GraphEvolve có thêm:
```jsonc
{
  "event_type": "insert",
  "iteration": 42,
  "score": 0.8472,
  "action": "ATTACH_TO",          // graph placement (ATTACH/NEW_BRANCH/SPLIT)
  "policy_action": "exploit",     // ← mode policy: exploit | crossover | space_explore
  "space_target": "new_form",     // ← chỉ khi space_explore: new_form | new_dir
  "direction_node_id": "...",     // ← khi exploit: direction (arm) đã chọn
  "placement_path": ["flow", "greedy"],
  ...
}
```

---

## 4. Visualize (timeline tô màu theo mode)

Dùng đúng visualizer của ExperienceGraph — nó **tự nhận biết** GraphEvolve qua `policy_action` và đổi cách hiển thị timeline.

```bash
cd benchmarks/ADRS/cloudcast
bash reproduce/visualize_graphevolve.sh          # xuất HTML tĩnh (run mới nhất)
LIVE=1 bash reproduce/visualize_graphevolve.sh   # live server, refresh khi đang chạy

# hoặc trực tiếp
python -m skydiscover.experience_graph.visualize <output_dir> --out viz.html
```

**Panel trái — Score Timeline (adaptive):** mỗi iteration là một điểm, **màu/ký hiệu theo mode**:

| Mode | Màu | Ký hiệu | Ý nghĩa |
|------|-----|---------|---------|
| Exploit | xanh dương | ● circle | refine 1 parent trong 1 direction |
| Crossover | cam | ◆ diamond | tổng hợp nhiều direction |
| Explore · new formulation | tím | ▲ star-triangle | tạo `problem_view` mới (đổi cách nhìn) |
| Explore · new direction | xanh ngọc | ▲ triangle | tạo `solution_strategy` mới dưới best framing |
| Seed | xám | ○ open | program khởi tạo |

Hover một điểm thấy: `Mode`, `Placement` (graph action), `Path`, `Score`. Legend cho thấy phân bố exploit/crossover/explore của cả run. (Run AdaEvolve không có `policy_action` → timeline giữ nguyên 1 màu như cũ.)

**Panel phải** — cây ExperienceGraph + slider replay snapshot (như mô tả ở [experience_graph.md](experience_graph.md)).

---

## 5. Runtime logs

```
INFO  GraphEvolveController initialized (bootstrap_k=5, crossover_set_size=5)
INFO  Iter 12 [exploit]       program a1b2c3d4 score=0.8120 (p_space=0.001, w_exploit=2.50)
INFO  Iter 13 [crossover]     program e5f6...   score=0.8455 (p_space=0.001, w_exploit=2.50)
INFO  Iter 41 [space_explore] program 99aa...   score=0.7203 (p_space=0.640, w_exploit=1.00)
WARN  Space-explore target 'new_form' was attached to an existing branch (...); reward=0.
```
- `p_space` cao ⇒ hệ đang bão hòa, circuit breaker đẩy sang space-explore.
- Dòng WARN: graph đặt nhầm node mới vào nhánh cũ → policy không thưởng oan (Δ=0).

---

## 6. Resume

Resume từ checkpoint: store + `experience_graph.json` + `graphevolve_policy.json` đều tự load lại (bandit weights, `G_global`, `pull_count`, `t` được khôi phục). Run mới (fresh) khởi tạo `G_global = initial_g_global` để space-explore không bật sớm.

---

## 7. Bản đồ code

| File | Vai trò |
|------|---------|
| [skydiscover/search/graphevolve/policy.py](../../skydiscover/search/graphevolve/policy.py) | `PolicyState` + `GraphEvolvePolicy` (4 tầng, thuần, test được) |
| [skydiscover/search/graphevolve/database.py](../../skydiscover/search/graphevolve/database.py) | store phẳng + helper đọc graph + sidecar persistence |
| [skydiscover/search/graphevolve/controller.py](../../skydiscover/search/graphevolve/controller.py) | vòng lặp: plan → generate → eval → insert → update |
| [skydiscover/context_builder/graphevolve/](../../skydiscover/context_builder/graphevolve/) | builder + 3 template (mutate / crossover / space_explore) |
| `config.py: GraphEvolveDatabaseConfig` | hyperparameters (đăng ký type `graphevolve`) |
| [tests/search/test_graphevolve_policy.py](../../tests/search/test_graphevolve_policy.py) | unit test policy (cold-start, power-law, bandit, sigmoid...) |

**Thay đổi additive lên hạ tầng chung** (backward-compatible, không đụng AdaEvolve): `ExperienceGraph.insert` thêm `placement_hint` (bias LLM_place tạo nhánh mới cho space-explore) và `extra` (ghi `policy_action` vào event); `code_utils.extract_evolve_block`.
