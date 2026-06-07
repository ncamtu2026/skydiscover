# AdaEvolve — Architecture Analysis

## 1. Tổng quan

AdaEvolve là một thuật toán **tiến hóa thích nghi dùng LLM làm toán tử mutation**.
Thay vì random mutation truyền thống, LLM đọc code của solution hiện tại và sinh ra biến thể mới
dựa trên guidance trong prompt. Toàn bộ quá trình xoay quanh vòng lặp:

```
sample parent → build prompt → LLM sinh code mới → evaluate → lưu vào archive
```

---

## 2. Khởi tạo — Solution đầu tiên đến từ đâu?

Có hai con đường:

**Con đường 1 (phổ biến): User cung cấp `initial_program_path`**
```
Runner(initial_program_path="solution.py")
    → đọc file từ disk
    → evaluate để lấy metrics
    → database.add(program)  ← thêm vào island 0
    → _ensure_all_islands_seeded()  ← copy sang các island còn lại
```

**Con đường 2: Không có initial program**
```
_generate_child() → database.programs rỗng
    → _run_from_scratch_iteration()
    → build_prompt(current_program=None)  ← không có parent
    → LLM tự sinh solution từ mô tả bài toán trong system_message
```

---

## 3. Cấu trúc lưu trữ — Islands & Archive

Chỉ có **một chỗ lưu duy nhất**: các island archives trong database.

```
Database
├── Island 0: UnifiedArchive [A, B, C, D, ...]
├── Island 1: UnifiedArchive [A, E, F, G, ...]
└── Island N: UnifiedArchive [A, H, I, J, ...]
```

Tất cả solution — từ solution ban đầu đến mọi solution sinh ra qua tiến hóa — đều nằm
chung trong archive. **Không có storage riêng cho "parent" hay "context programs".**
Đây chỉ là vai trò được gán tạm thời trong mỗi iteration:

- **parent**: 1 solution được chọn để LLM improve
- **context programs**: N solution khác được chọn để LLM tham khảo thêm

Iteration sau, solution đang là "context" có thể trở thành "parent" và ngược lại.

---

## 4. Vòng lặp chính

```
run_discovery()
│
├── _ensure_all_islands_seeded()
│
└── for iteration in range(max_iterations):
    │
    ├── [nếu paradigm enabled] is_paradigm_stagnating()?
    │   └── YES + no active paradigm → _generate_paradigms_if_needed()
    │                                   → LLM sinh ý tưởng đột phá
    │
    ├── _run_normal_step()  [có retry nếu thất bại]
    │   └── _generate_child()
    │       ├── database.sample()      → chọn parent + context
    │       ├── build_prompt()         → xây dựng prompt
    │       ├── _call_llm()            → sinh code mới
    │       ├── parse code (diff / full rewrite)
    │       └── evaluator.evaluate()   → tính metrics
    │
    ├── database.add(child)            → lưu solution mới
    │
    └── database.end_iteration()
        ├── _should_spawn_island()     → spawn island mới nếu cần
        ├── UCB / round-robin          → chọn island tiếp theo
        └── migration (định kỳ)        → copy top programs sang island liền kề
```

---

## 5. Cơ chế Adaptive Search

### 5.1 AdaptiveState — Per-island

Mỗi island có một `AdaptiveState` tracking **accumulated signal G**:

```
G_t = ρ * G_{t-1} + (1 - ρ) * δ²

  δ = normalized improvement delta
  ρ = decay (default 0.9)
```

`G` phản ánh mức độ cải thiện gần đây của island:
- G cao → island đang productive → giảm `search_intensity` → khai thác (exploitation)
- G thấp → island bị kẹt → tăng `search_intensity` → khám phá (exploration)

```
search_intensity = I_min + (I_max - I_min) / (1 + √(G + ε))
```

### 5.2 Parent Sampling — 3 bước

**Bước 1**: Tính `search_intensity` của island hiện tại (từ G)

**Bước 2**: Random roll xác định mode:
```
rand < intensity              → exploration   (xác suất = intensity)
rand < intensity + (1-i)*0.7  → exploitation  (xác suất = (1-intensity)*70%)
else                          → balanced      (xác suất = (1-intensity)*30%)
```

Ví dụ với intensity=0.4: exploration=40%, exploitation=42%, balanced=18%

**Bước 3**: Chọn parent theo mode:

| Mode | Cơ chế |
|---|---|
| exploitation | Top 25% fitness cao nhất (hoặc Pareto front nếu multi-objective) |
| exploration | Ưu tiên solution có novelty cao (khác biệt nhất so với phần còn lại) |
| balanced | Kết hợp cả fitness và novelty |

Mode còn được inject vào prompt dưới dạng label để LLM biết nên làm gì:
- exploration → *"Consider alternative algorithmic approaches..."*
- exploitation → *"This solution works well, but improvements are still possible..."*

### 5.3 MultiDimensionalAdapter — Cross-island UCB

`MultiDimensionalAdapter` chọn island tiếp theo theo UCB:

```
UCB = reward_avg + C * √(ln(N) / visits)
```

**Hai normalization khác nhau cho hai mục đích khác nhau:**
- Search intensity dùng LOCAL best → scale-invariant per-island
- UCB rewards dùng GLOBAL best → fair cross-island comparison (tránh "Poor Island Bias")

Dùng **decay** trên rewards để breakthrough cũ không thống trị mãi.

---

## 6. Context Programs trong Prompt

### 6.1 Context programs là gì?

Context programs là các solution được chọn từ archive và đưa vào prompt để LLM tham khảo.
Mỗi context program hiển thị **full code + metrics** của solution đó.

### 6.2 Context programs đến từ đâu?

```python
# 60% local: từ cùng island — top performers, chọn những cái KHÁC NHẤT so với parent
local_context = archive.sample_other_context_programs(parent, local_count)

# 40% global: top performers từ TẤT CẢ islands (cross-pollination)
global_context = _sample_global_top(parent.id, global_count)
```

**Ban đầu context programs không có** (list rỗng). Chúng xuất hiện dần:
```
Iter 1: archive=[A]       → context=[]
Iter 2: archive=[A,B]     → context=[A hoặc B] (1 cái)
Iter 3: archive=[A,B,C]   → context=[top 2 khác parent nhất]
Iter N: archive đủ lớn   → context=num_context_programs đầy đủ (default 4)
```

### 6.3 Cấu trúc đầy đủ của prompt LLM nhận

```
[system] Mô tả bài toán + hướng dẫn

[user]
  Parent program (code + metrics + label exploration/exploitation)

  Other Context Solutions:
    Program 1: code + metrics   ← local archive (diverse từ parent)
    Program 2: code + metrics   ← local archive
    Program 3: code + metrics   ← global top
    ...

  Search Guidance:
    [Evaluator feedback — nếu parent có artifact feedback]
    [Paradigm breakthrough — nếu đang stagnate toàn cục]
    [Sibling context — các mutations đã thử trên parent này]
    [Error retry context — nếu đang retry sau lỗi]
```

---

## 7. Paradigm Breakthrough

### 7.1 Mục đích

Khi toàn bộ hệ thống bị kẹt (improvement rate < threshold trong window_size iteration),
một LLM thứ hai (guide_model) được gọi để phân tích bài toán và sinh ra "ý tưởng đột phá" —
các hướng tiếp cận hoàn toàn mới mà evolutionary search chưa thử.

### 7.2 Hai component

**ParadigmTracker** — state machine:
- `improvement_history`: window binary (1=improved, 0=not) size=30
- `active_paradigms`: batch 3 ý tưởng hiện tại, mỗi cái dùng tối đa `max_paradigm_uses=5` lần
- `tried_paradigms`: lịch sử các ý tưởng đã tiêu hết, bounded size=10

**ParadigmGenerator** — LLM caller:
- Nhận: evaluator code, best solution hiện tại, danh sách tried_paradigms (SUCCESS/FAILED)
- Sinh: JSON array 3 ý tưởng với `idea`, `description`, `what_to_optimize`, `cautions`, `approach_type`
- `tried_paradigms` trong prompt giúp LLM tránh lặp lại hướng đã thất bại

### 7.3 Vòng đời của một paradigm batch

```
is_stagnating() = True AND has_active_paradigm() = False
    → LLM được gọi → sinh 3 ý tưởng → lưu vào active_paradigms

Mỗi iteration có paradigm active:
    → inject vào prompt: "BREAKTHROUGH IDEA — IMPLEMENT THIS: ..."
    → use_paradigm() → increment usage count → rotate sang ý tưởng tiếp

Khi cả 3 ý tưởng đều đã dùng max_uses lần:
    → archive sang tried_paradigms (kèm outcome SUCCESS/FAILED)
    → has_active_paradigm() = False
    → nếu vẫn stagnating → LLM được gọi lại
```

### 7.4 Phân biệt hai counter

| Counter | Ý nghĩa |
|---|---|
| `max_paradigm_uses=5` | Mỗi ý tưởng được inject vào prompt tối đa 5 lần trong một batch |
| `max_tried_paradigms=10` | Bộ nhớ lịch sử cho LLM, giữ tối đa 10 ý tưởng đã dùng xong (rolling) |

`tried=10` **không có nghĩa là hết quota** — LLM vẫn tiếp tục được gọi bình thường,
chỉ là window nhớ lịch sử bị rolling (ý tưởng cũ nhất bị drop).

---

## 8. Migration

Định kỳ mỗi `migration_interval` iteration (default=15), top programs của từng island
được copy sang island liền kề theo **ring topology**:

```
Island 0 → Island 1 → Island 2 → ... → Island 0
```

Migration giúp lan truyền solution tốt giữa các island, tránh từng island tiến hóa
hoàn toàn độc lập. Solution nhận từ migration **không** cộng vào UCB rewards
(island không "earn" improvement này), nhưng vẫn cập nhật best_score và G
để search intensity phản ánh đúng.

---

## 9. Empirical Analysis — Benchmark Results

### 9.1 Dữ liệu phân tích

| Run | Benchmark | Iterations | Paradigm invocations | Score range |
|---|---|---|---|---|
| cloudcast_0529 | Cloudcast | 41 | 4 (+1 pending) | 0.00130 → 0.00161 |
| cloudcast_0530 | Cloudcast | 52 | 10 (+1 pending) | 0.00161 → 0.00161 |
| cloudcast_0601 | Cloudcast | 100 | 18 | 0.00096 → 0.00151 |
| llmsql_0529 | LLM SQL | 39 | 4 | 0.11265 → 0.65782 |
| llmsql_0530 | LLM SQL | 76 | 6 | 0.65782 → 0.70946 |
| txn_0601 | Txn Scheduling | 98 | 27 | 3333.33 → 3952.57 |

### 9.2 Cơ chế nào tạo ra cải thiện?

Tổng 32 improvement events phân tích được:

| Benchmark | Parent-based | Paradigm | Tổng |
|---|---|---|---|
| Cloudcast | 4 | 5 | 9 |
| LLM SQL | 13 | 5 | 18 |
| Txn Scheduling | 4 | 1 | 5 |
| **Tổng** | **21 (66%)** | **11 (34%)** | **32** |

**Parent-based** tạo ra phần lớn cải thiện **lớn và sớm** (giai đoạn khám phá ban đầu).
**Paradigm** có tác dụng chủ yếu ở **giai đoạn giữa/cuối** khi parent-based đã cạn kiệt.

### 9.3 Pattern quan sát được

**Cloudcast** — bài toán khó, hit ceiling sớm:
- 5 invoke đầu (tried=0→10) có tác dụng, 13–23 invoke sau vô ích
- Sau tried=10: rate=0.000, paradigm invoke liên tục mỗi ~5 iter nhưng không breakthrough

**LLM SQL** — không gian tìm kiếm rộng hơn:
- Parent-based tạo bước nhảy lớn nhất (iter 2: +481%)
- Paradigm vẫn có tác dụng dù tried=10 (iter 83–84 ở llmsql_0530)

**Txn Scheduling** — kẹt lâu nhất:
- 27 invocations, rate=0.000 từ iter 21 đến 88 (67 iter liên tục)
- Chỉ 1 paradigm breakthrough duy nhất ở iter 88, cuối run

### 9.4 Hiệu suất paradigm invoke

Tổng ~69 invocations, chỉ ~11 tạo ra improvement trực tiếp → **~16% invoke hiệu quả**.
Phần lớn invocations không hiệu quả xảy ra khi hệ thống đã thực sự hit ceiling,
không phải stagnation tạm thời.
