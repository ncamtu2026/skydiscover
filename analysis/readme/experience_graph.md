# ExperienceGraph — Hướng dẫn sử dụng

Module ghi lại tất cả solution đã evaluate vào một cây phân tầng `paradigm → formulation → mechanism → leaf`, phục vụ hai mục đích độc lập: **visualize quá trình exploration** và **cung cấp context cho paradigm breakthrough**.

---

## 1. Bật trong config

Thêm vào file YAML config của benchmark:

```yaml
search:
  database:
    # Bật ghi tree (insert mọi solution, save file)
    use_experience_graph: true

    # (tuỳ chọn) Có inject summary vào paradigm prompt không?
    # Default: true — chỉ có tác dụng khi use_experience_graph: true
    experience_graph_use_paradigm: true

# (tuỳ chọn) LLM riêng cho ExperienceGraph (mặc định dùng guide_models)
llm:
  experience_graph_models:
    - name: gemini/gemini-2.0-flash
      weight: 1.0

# (tuỳ chọn) Điều chỉnh tham số module
experience_graph:
  compress_threshold: 4      # mechanism node > N leaf thì nén khi summarize
  snapshot_interval: 50      # lưu full snapshot mỗi N iteration
  rationale_max_chars: 2000
  tree_render_max_chars: 8000
  place_temperature: 0.3
  group_temperature: 0.3
```

**Hai flag độc lập:**

| Flag | Tác dụng |
|------|----------|
| `use_experience_graph: true` | Build + lưu tree. Không nhét vào prompt nào. |
| `experience_graph_use_paradigm: true` | Thêm summary tree vào paradigm breakthrough prompt. |

Muốn chỉ xem graph mà không ảnh hưởng gì đến chạy:
```yaml
use_experience_graph: true
experience_graph_use_paradigm: false
```

---

## 2. Output files

Sau khi chạy, trong `output_dir` của run sẽ có:

```
output_dir/
├── experience_graph.json                    # full tree hiện tại (dùng để resume)
├── experience_graph_events.jsonl            # event log mỗi insert + mỗi summarize
└── experience_graph_snapshots/
    ├── snapshot_000000_first.json           # snapshot sau insert đầu tiên
    ├── snapshot_000050_interval.json        # snapshot mỗi 50 iteration
    ├── snapshot_000150_summarize.json       # snapshot khi paradigm stagnation trigger
    └── snapshot_001000_shutdown.json        # snapshot cuối run
```

### Event log format (`experience_graph_events.jsonl`)

```jsonc
// Mỗi solution được insert
{
  "event_type": "insert",
  "iteration": 42,
  "timestamp": "2026-06-14T10:23:45",
  "solution_id": "abc123...",
  "score": 0.8472,
  "is_paradigm_breakthrough": false,
  "action": "ATTACH_TO",              // ATTACH_TO | NEW_BRANCH_UNDER | SPLIT
  "leaf_label": "interval bottom-up",
  "placement_path": ["DP", "interval", "bottom-up"],
  "total_leaves": 15,
  "total_internal": 7,
  "llm_place_time_ms": 830
}

// Mỗi lần paradigm stagnation trigger (nếu experience_graph_use_paradigm: true)
{
  "event_type": "summarize",
  "iteration": 150,
  "n_leaves": 50,
  "n_paradigm_branches": 4,
  "n_compressed": 2,
  "summary_char_length": 1240
}
```

---

## 3. Visualize sau run

```bash
python -m skydiscover.experience_graph.visualize <output_dir>

# Ví dụ
python -m skydiscover.experience_graph.visualize ./benchmarks/ADRS/txn_scheduling/reproduce/run_001

# Chỉ định file output
python -m skydiscover.experience_graph.visualize ./run_001 --out my_viz.html
```

Mở file HTML trong browser. File self-contained, không cần server.

### Giao diện HTML

**Panel trái — Score Timeline**
- Scatter plot iteration → score
- Màu cam/★ = paradigm breakthrough solutions
- Đường đứt đỏ = lúc paradigm stagnation trigger (nếu có summarize events)
- Hover để xem `leaf_label`, `action`, `placement_path`

**Panel phải — Exploration Tree**
- Cây D3 collapsible theo snapshot đang chọn
- Màu node: xanh dương = paradigm, xanh lá = formulation, cam = mechanism, xám = leaf thường, tím = leaf paradigm breakthrough
- Node lá có size tỉ lệ với score
- Click node để collapse/expand nhánh
- Hover để xem chi tiết (score, solution ID, rationale)

**Slider dưới** — chọn snapshot để replay lại quá trình phát triển cây theo thời gian

---

## 4. Runtime logs

Trong log của run, các dòng liên quan đến ExperienceGraph:

```
INFO  ExperienceGraph enabled (output_dir=./run_001)
INFO  ExperienceGraph [NEW_BRANCH_UNDER] "interval bottom-up" score=0.8472 → DP → interval → bottom-up
INFO  ExperienceGraph [ATTACH_TO] "greedy sweep" score=0.6130 [PARADIGM] → Greedy → sweep → single-pass
INFO  ExperienceGraph [SPLIT] "LP relaxation" score=0.7891 → LP → relaxation → LP_vs_ILP_split
INFO  ExperienceGraph: summarized (50 leaves, 4 paradigm branches, 2 compressed)
```

---

## 5. Resume từ checkpoint

Khi resume một run đã có `experience_graph.json`, tree sẽ tự load lại:

```
INFO  ExperienceGraph: loaded tree from checkpoint (47 leaves, 18 internal nodes)
```

Events JSONL tiếp tục append, snapshots tiếp tục ghi — không mất dữ liệu cũ.

---

## 6. Tắt hoàn toàn (default)

Mặc định `use_experience_graph: false` — module không chạy, không có overhead nào, behavior y hệt ban đầu.
