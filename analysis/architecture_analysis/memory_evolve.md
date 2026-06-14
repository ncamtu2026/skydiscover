# ExperienceGraph — SolutionGraphMemory

## Bối cảnh & vấn đề

`ParadigmGenerator` hiện chỉ nhận được một flat list `previously_tried_ideas` (format: `"FAILED: scipy.minimize - ... (improvement: -0.0012)"`). Thông tin này quá nghèo nàn — không phản ánh toàn bộ landscape exploration thực sự qua các iteration bình thường.

**Mục tiêu:** Build `ExperienceGraph` — module độc lập (như `knowledge_evolve`) ghi lại TẤT CẢ solution đã evaluate vào một cây phân tầng, rồi cung cấp summary đó cho `ParadigmGenerator` như một "Exploration Map".

Design spec cây (INSERT + SUMMARIZE): `analysis/method_analysis/abstract_method_graph.md`

---

## Module mới: `skydiscover/experience_graph/`

```
skydiscover/experience_graph/
    __init__.py          # export ExperienceGraphConfig only (tránh circular import)
    config.py            # ExperienceGraphConfig dataclass
    nodes.py             # GraphNode + tree helpers
    experience_graph.py  # ExperienceGraph service class
    visualize.py         # CLI: đọc events + snapshots → sinh HTML interactive
```

### `nodes.py` — Data structure

```python
@dataclass
class GraphNode:
    id: str
    node_type: str             # "root" | "internal" | "leaf"
    label: str                 # 1–4 từ, do LLM sinh
    field_name: Optional[str]  # "paradigm" | "formulation" | "mechanism" (internal); None (root/leaf)
    children: List["GraphNode"]
    # Leaf-only:
    solution_id: Optional[str] = None
    score: Optional[float] = None
    rationale_ref: Optional[str] = None
    is_paradigm_breakthrough: bool = False
    # Serialization:
    def to_dict(self) -> Dict: ...
    @classmethod
    def from_dict(cls, d) -> "GraphNode": ...
```

Module-level helpers trong `nodes.py`:
- `find_node(root, node_id) -> Optional[GraphNode]` — DFS by id
- `find_parent(root, target_id) -> Optional[GraphNode]` — DFS tìm parent của target
- `render_for_insert(node, depth=0) -> str` — render cây text với id; leaf có `[PARADIGM]` marker khi `is_paradigm_breakthrough=True`

### `config.py` — ExperienceGraphConfig

```python
@dataclass
class ExperienceGraphConfig:
    place_temperature: float = 0.3       # LLM_place
    place_max_tokens: int = 1000
    group_temperature: float = 0.3       # LLM_group_leaves
    group_max_tokens: int = 800
    compress_threshold: int = 4          # mechanism node > N leaf → compress khi summarize
    rationale_max_chars: int = 2000      # cắt ngắn rationale trong prompt LLM_place
    tree_render_max_chars: int = 8000    # cắt ngắn cây render trong prompt LLM_place
    snapshot_interval: int = 50          # lưu full-tree snapshot mỗi N iteration
```

### `experience_graph.py` — Service class

```python
class ExperienceGraph:
    def __init__(self, config: ExperienceGraphConfig, llm_pool: LLMPool, output_dir=None):
        # Khởi tạo root node, thử load từ checkpoint nếu có

    async def insert(self, solution_id, score, rationale, is_paradigm_breakthrough=False) -> None:
        # 1. render_for_insert(self.root) → tree_text
        # 2. await _llm_place(rationale, tree_text) → decision dict
        # 3. _apply_decision(decision, ...) → mutate tree
        # 4. save() → ghi experience_graph.json

    async def summarize(self) -> str:
        # Recursive render; mechanism node > compress_threshold leaf
        # → await _llm_group_leaves(leaves) → compressed groups
        # Trả về "EXPLORATION SUMMARY (experience memory)" string

    async def _llm_place(self, rationale: str, tree_text: str) -> dict:
        # JSON schema strict: action, target_id, new_path[], target_leaf_id,
        # split_field_name, new_label, leaf_label
        # Fallback khi parse fail: NEW_BRANCH_UNDER root, new_path 3 level "Unknown"

    async def _llm_group_leaves(self, leaves: List[GraphNode]) -> list:
        # JSON schema: {"groups": [{"label": str, "leaf_ids": [str]}]}
        # Fallback: mỗi leaf là 1 group riêng

    def _apply_decision(self, decision, solution_id, score, rationale, is_paradigm_breakthrough):
        # ATTACH_TO / NEW_BRANCH_UNDER / SPLIT — pure tree ops, không LLM

    def save(self) -> None:                      # ghi experience_graph.json (current state)
    def _save_snapshot(self, iteration: int) -> None  # ghi snapshots/snapshot_{iter:06d}.json
    def _log_event(self, event: dict) -> None    # append vào experience_graph_events.jsonl
    def _try_load(self) -> None                  # load nếu tồn tại, bỏ qua nếu không có/corrupt
```

**`summarize()` là async** vì phải `await _llm_group_leaves()`.  
**Persistence:** 3 files trong `output_dir`:
- `experience_graph.json` — current full tree (overwrite mỗi insert, dùng để resume)
- `experience_graph_events.jsonl` — lightweight event log mỗi insert (append-only, không bao giờ mất)
- `experience_graph_snapshots/snapshot_{iter:06d}.json` — full tree tại các điểm quan trọng (dùng để visualize)

---

## Logging runtime

### Logger messages (dùng Python `logging` module)

| Sự kiện | Level | Message |
|---|---|---|
| Module init thành công | INFO | `ExperienceGraph enabled (output_dir=...)` |
| Load từ checkpoint | INFO | `ExperienceGraph: loaded tree from checkpoint ({N} leaves, {M} internal nodes)` |
| Sau `_apply_decision` | INFO | `ExperienceGraph [{action}] "{leaf_label}" score={score:.4f} [PARADIGM] → {path}` |
| LLM_place fallback | WARNING | `ExperienceGraph: LLM_place parse failed, using fallback NEW_BRANCH_UNDER root` |
| LLM_group_leaves fallback | WARNING | `ExperienceGraph: LLM_group_leaves failed for mechanism "{label}", using one-group-per-leaf` |
| Sau `summarize()` | INFO | `ExperienceGraph: summarized ({n_leaves} leaves, {n_paradigms} paradigm branches, {n_compressed} compressed)` |
| Insert exception | WARNING | `ExperienceGraph insert failed: {e}` |
| Summarize exception | WARNING | `ExperienceGraph summarize failed: {e}` |

**`{path}`** trong insert log = `paradigm_label → formulation_label → mechanism_label`, ví dụ:
```
ExperienceGraph [ATTACH_TO] "interval bottom-up" score=0.8472 → DP → interval → bottom-up
ExperienceGraph [NEW_BRANCH_UNDER] "greedy sweep" score=0.6130 [PARADIGM] → Greedy → sweep → single-pass
ExperienceGraph [SPLIT] "LP relaxation" score=0.7891 → LP → relaxation → LP_vs_ILP_split
```

---

## Event log (`experience_graph_events.jsonl`)

Mỗi dòng là 1 JSON event, append-only:

```jsonc
// insert event
{
  "event_type": "insert",
  "iteration": 42,
  "timestamp": "2026-06-14T10:23:45.123456",
  "solution_id": "abc123...",
  "score": 0.8472,
  "is_paradigm_breakthrough": false,
  "action": "ATTACH_TO",
  "leaf_label": "interval bottom-up",
  "placement_path": ["DP", "interval", "bottom-up"],
  "total_leaves": 15,
  "total_internal": 7,
  "llm_place_time_ms": 830
}

// paradigm summarize event (khi summarize() được gọi trước paradigm generation)
{
  "event_type": "summarize",
  "iteration": 150,
  "timestamp": "...",
  "n_leaves": 50,
  "n_paradigm_branches": 4,
  "n_compressed": 2,
  "summary_char_length": 1240,
  "llm_group_time_ms": 1200
}
```

---

## Snapshot (`experience_graph_snapshots/snapshot_{iter:06d}.json`)

Lưu tại:
- Sau insert đầu tiên (iter 0)
- Mỗi `snapshot_interval` iteration (default 50)
- Mỗi khi `summarize()` được gọi (trước paradigm generation)
- Khi controller shutdown (cuối run) — gọi `experience_graph.save()` trong `run_discovery()` sau vòng lặp chính

```json
{
  "version": 1,
  "iteration": 50,
  "timestamp": "2026-06-14T10:45:00",
  "total_leaves": 30,
  "total_internal": 12,
  "trigger": "interval",
  "tree": { "...GraphNode.to_dict() recursive..." }
}
```

`trigger`: `"first"` | `"interval"` | `"summarize"` | `"shutdown"`.

---

## LLM Calls

### LLM_place

Dùng `response_format` JSON schema strict (pattern từ `ParadigmGenerator`). Tất cả keys đều required; key không áp dụng để empty string / empty array.

```python
# Schema properties:
{
    "action":           enum ["ATTACH_TO", "NEW_BRANCH_UNDER", "SPLIT"],
    "target_id":        str,   # ATTACH_TO / NEW_BRANCH_UNDER
    "new_path":         [{"field_name": enum[paradigm|formulation|mechanism], "label": str}],  # NEW_BRANCH_UNDER
    "target_leaf_id":   str,   # SPLIT
    "split_field_name": enum[...],  # SPLIT
    "new_label":        str,   # SPLIT
    "leaf_label":       str    # luôn luôn có
}
```

### LLM_group_leaves

```python
# Schema:
{"groups": [{"label": str, "leaf_ids": [str]}]}
```

---

## `visualize.py` — CLI visualizer

```
python -m skydiscover.experience_graph.visualize <output_dir> [--out viz.html]
```

Đọc từ `output_dir`:
- `experience_graph_events.jsonl` → timeline data
- `experience_graph_snapshots/*.json` → tree states theo thời gian

Sinh ra một file HTML self-contained (mọi JS inline + CDN). Cấu trúc tương tự `extras/monitor/dashboard.html`:

### Panels trong HTML

**Panel trái — Score Timeline (Plotly)**
- Line chart: iteration → score, với scatter dots cho từng solution
- Màu: cam = paradigm breakthrough, xanh = normal
- Vertical line ở các `summarize` event (khi paradigm generation trigger)
- Hover: hiện `leaf_label`, `action`, `placement_path`, `solution_id[:8]`

**Panel phải — Tree View (D3 collapsible tree)**
- Render cây tại snapshot được chọn
- Màu node theo level: paradigm = xanh dương, formulation = xanh lá, mechanism = cam, leaf = tròn sized by score
- Leaf paradigm breakthrough có icon ★
- Click node để expand/collapse nhánh
- Tooltip: label, score (leaf), số children (internal)

**Bottom — Snapshot slider**
- Slider qua các snapshot files theo thời gian
- Hiện `iteration`, `total_leaves`, `trigger` cho snapshot hiện tại

**Stats bar**
- Total leaves, số paradigm branches, số breakthrough solutions, best score, số lần summarize

### Pattern kỹ thuật
- Plotly 2.x từ CDN (giống dashboard.html)
- D3 v7 từ CDN cho tree layout
- Theme toggle dark/light (giống dashboard.html)
- Toàn bộ data embed vào HTML dưới dạng `<script>const DATA = {...};</script>` → không cần server

---

## Files cần sửa

### 1. `skydiscover/config.py`

**LLMConfig** — thêm field + fallback trong `__post_init__`:
```python
experience_graph_models: List[LLMModelConfig] = field(default_factory=lambda: [])
# __post_init__: if not self.experience_graph_models: self.experience_graph_models = self.guide_models.copy()
```
Thêm `experience_graph_models` vào `all_models` trong `update_model_params` và provider-resolution loop.

**AdaEvolveDatabaseConfig** — thêm flag:
```python
use_experience_graph: bool = False
```

**Master Config** — thêm field:
```python
experience_graph: ExperienceGraphConfig = field(default_factory=ExperienceGraphConfig)
```

**from_dict / to_dict** — deserialization/serialization cho `experience_graph`, pattern giống `knowledge`.

---

### 2. `skydiscover/search/adaevolve/controller.py`

**`__init__`** — sau block KnowledgeEvolve init:
```python
self.experience_graph: Optional["ExperienceGraph"] = None
if getattr(db_config, "use_experience_graph", False):
    try:
        from skydiscover.experience_graph.experience_graph import ExperienceGraph
        eg_llm = LLMPool(self.config.llm.experience_graph_models)
        self.experience_graph = ExperienceGraph(
            self.config.experience_graph, eg_llm, self.output_dir
        )
        logger.info("ExperienceGraph enabled")
    except Exception as e:
        logger.warning(f"ExperienceGraph init failed, disabling: {e}")
```

**`_run_iteration`** — sau `self._process_result(result, ...)`:
```python
if self.experience_graph is not None and result.child_program_dict:
    try:
        child = Program(**result.child_program_dict)
        score = self.database.get_program_proxy_score(child)
        changes = child.metadata.get("changes", "")
        paradigm_idea = child.metadata.get("paradigm_idea")
        rationale = f"{changes} [PARADIGM: {paradigm_idea}]" if paradigm_idea else changes
        await self.experience_graph.insert(
            solution_id=child.id, score=score, rationale=rationale,
            is_paradigm_breakthrough=bool(paradigm_idea),
        )
    except Exception as e:
        logger.warning(f"ExperienceGraph insert failed: {e}")
```

Note: `_process_result` giữ nguyên sync; insert được gọi trực tiếp trong `_run_iteration` (cùng convention với `_log_iteration_stats`).

**`_generate_paradigms_if_needed`** — trước khi gọi `paradigm_generator.generate(...)`:
```python
experience_graph_summary = None
if self.experience_graph is not None:
    try:
        experience_graph_summary = await self.experience_graph.summarize() or None
    except Exception as e:
        logger.warning(f"ExperienceGraph summarize failed: {e}")
# Thêm experience_graph_summary=experience_graph_summary vào generate(...)
```

---

### 3. `skydiscover/search/adaevolve/paradigm/generator.py`

**`generate()` signature** — thêm:
```python
experience_graph_summary: Optional[str] = None
```

**`_build_prompt()`** — inject section trước output format (cùng convention với `knowledge_context`, `evaluator_feedback`):
```python
if experience_graph_summary:
    sections.insert(-1,
        "## Exploration Map (Experience Graph)\n\n"
        "Hierarchical map of ALL solution approaches explored so far. "
        "Paradigm breakthrough solutions are marked [PARADIGM].\n\n"
        f"{experience_graph_summary}"
    )
```
Chỉ inject ở non-prompt-optimization path (block `else`).

---

## Data flow tổng thể

```
_run_iteration
  └─ _run_normal_step → _generate_child → _execute_generation
       child.metadata["changes"], ["paradigm_idea"] được set
  └─ _process_result(result)            [sync, không thay đổi]
  └─ await experience_graph.insert(solution_id, score, rationale, is_pb)
       └─ _llm_place() → LLM → decision dict        [LLM call]
       └─ _apply_decision() → mutate tree            [pure tree op]
       └─ _log_event(insert_event) → events.jsonl   [append]
       └─ save() → experience_graph.json            [overwrite]
       └─ _save_snapshot() nếu first/interval      [conditional]
       └─ logger.info("[{action}] {leaf_label} score=... → {path}")

_generate_paradigms_if_needed
  └─ await experience_graph.summarize()
       └─ _render_summary() recursive
       └─ _llm_group_leaves() nếu cần compress      [LLM call, có thể N calls]
       └─ _log_event(summarize_event) → events.jsonl
       └─ _save_snapshot(trigger="summarize")
       └─ logger.info("summarized ({n_leaves} leaves, ...)")
       └─ returns "EXPLORATION SUMMARY..." string
  └─ paradigm_generator.generate(..., experience_graph_summary=...)

run_discovery() [sau vòng lặp chính]
  └─ experience_graph._save_snapshot(trigger="shutdown")
```

---

## Thứ tự inject trong prompt ParadigmGenerator

```
[0] Problem context
[1] Current program analysis
[2] Analysis framework (6 steps)
[3] Previously tried ideas (flat list, giữ nguyên)
[4] Techniques section
[5?] Evaluator feedback        (nếu có)
[6?] Knowledge context         (nếu có, từ KnowledgeEvolve)
[7?] Exploration Map           (nếu có, từ ExperienceGraph) ← MỚI
[8]  Output format
```

---

## Verification

1. Bật `use_experience_graph: true` → chạy vài iteration → kiểm tra `experience_graph.json`, `experience_graph_events.jsonl`, `experience_graph_snapshots/` đều được ghi
2. Log runtime: mỗi insert phải in `ExperienceGraph [{action}] "..." score=... → path`
3. Khi paradigm stagnation trigger → log "summarized" + prompt có section "## Exploration Map"
4. Tắt `use_experience_graph: false` (default) → behavior y hệt ban đầu, không có gì thay đổi
5. Resume từ checkpoint → tree load lại từ `experience_graph.json`, events.jsonl tiếp tục append, snapshots tiếp tục ghi
6. Sau run → chạy `python -m skydiscover.experience_graph.visualize <output_dir>` → mở HTML, kiểm tra timeline + tree slider hoạt động
