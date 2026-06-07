# OpenEvolve — Architecture Analysis

## 1. Tổng quan

Trong codebase SkyDiscover có **hai version** của OpenEvolve:

- **`openevolve_native`**: Port nội bộ thuật toán OpenEvolve gốc, chạy hoàn toàn trong
  SkyDiscover, dùng chung `DiscoveryController` như AdaEvolve.
- **`openevolve_backend`**: Thin wrapper gọi trực tiếp package `openevolve` bên ngoài,
  không dùng controller của SkyDiscover.

Giống AdaEvolve, OpenEvolve dùng **LLM làm toán tử mutation** — LLM đọc code của parent
và sinh ra biến thể mới. Sự khác biệt nằm ở cách tổ chức và quản lý population.

---

## 2. Cơ chế cốt lõi: MAP-Elites Grid

AdaEvolve lưu solution theo fitness + novelty score (UnifiedArchive). OpenEvolve dùng
**MAP-Elites grid** — mỗi island có một lưới ô (cell), mỗi ô đại diện cho một vùng
trong không gian **feature dimensions**.

Feature dimensions mặc định: `[complexity, diversity]`
- `complexity` = độ dài code (số ký tự)
- `diversity` = độ khác biệt so với reference pool (fast code diversity)

```
Grid của một island (ví dụ bins=10, 2 dimensions → 10×10 = 100 ô):

         complexity →
        ┌──┬──┬──┬──┐
d  low  │A │  │C │  │
i       ├──┼──┼──┼──┤
v       │  │B │  │D │
e       ├──┼──┼──┼──┤
r  high │  │  │E │  │
s       └──┴──┴──┴──┘
```

**Quy tắc MAP-Elites**: Mỗi ô chỉ giữ đúng **1 solution — solution có fitness cao nhất
trong ô đó**. Khi solution mới rơi vào ô đã có sẵn, chỉ cái fitness cao hơn được giữ lại.

Feature dimensions có thể là bất kỳ metric nào evaluator trả về (không nhất thiết phải
là complexity/diversity). Nếu dùng custom metric, bin được tính bằng min-max scaling
trên lịch sử giá trị quan sát được.

---

## 3. Cấu trúc lưu trữ

```
Database
├── programs: Dict[id → Program]         ← toàn bộ programs (global registry)
├── archive: Set[id]                     ← top-fitness programs, max_size=100
│
├── Island 0:
│   ├── island_feature_map: Dict[cell_key → program_id]   ← MAP-Elites grid
│   ├── island_programs: Set[id]
│   └── island_best: id
│
├── Island 1: ...
└── Island N: ...
```

Ngoài MAP-Elites grid per-island, còn có một **global archive** chứa top-fitness
programs từ tất cả islands. Archive này được dùng trong exploitation sampling.

---

## 4. Vòng lặp chính

```
for iteration in range(max_iterations):
    │
    ├── sample()
    │   ├── _sample_parent()                 → chọn parent (xác suất cố định)
    │   └── _sample_other_context_programs() → chọn context
    │
    ├── build_prompt() → LLM → parse code
    │
    ├── evaluate()
    │
    ├── add(child)
    │   ├── _calculate_feature_coords()      → tính (bin_0, bin_1, ...) của child
    │   ├── MAP-Elites insert:
    │   │     ô trống?    → thêm vào
    │   │     ô có sẵn?   → so fitness, giữ cái tốt hơn
    │   ├── _update_archive()                → cập nhật global archive
    │   ├── _enforce_population_limit()      → xóa worst nếu vượt limit
    │   └── _should_migrate()? → _migrate_programs()
    │
    └── current_island = (current_island + 1) % num_islands  ← round-robin
```

---

## 5. Parent Sampling

Tỉ lệ cố định, không thích nghi:

```python
rand = random.random()

if rand < 0.20:    → exploration  (20%)
elif rand < 0.90:  → exploitation (70%)
else:              → random       (10%)
```

| Mode | Cơ chế |
|---|---|
| **exploration** | Random uniform từ island hiện tại |
| **exploitation** | Random từ global archive, ưu tiên programs thuộc island hiện tại |
| **random** | Random uniform từ toàn bộ `programs` dict |

Không có label hay hướng dẫn mode nào được inject vào prompt (khác AdaEvolve).

---

## 6. Context Programs Sampling

Lấy từ **cùng island với parent**, theo 4 bước ưu tiên:

```
1. island_best (best program của island này, nếu khác parent)

2. top elite của island
   → sort by fitness, lấy top (n * elite_selection_ratio) = top 10%

3. programs từ các ô MAP-Elites gần parent (±2 ô theo mỗi dimension)
   → perturbation: feature_coord[i] += random.randint(-2, 2)
   → lý do: các solution "gần" trong feature space có thể gợi ý cải tiến hướng

4. random fill từ island (nếu vẫn còn thiếu)
```

Khác AdaEvolve: context chỉ lấy từ **local island**, không có global cross-pollination.

---

## 7. Migration

**Trigger**: khi `max(island_generations) - last_migration_generation >= migration_interval`
(default interval=10).

**Topology**: **bidirectional ring** — island i migrate sang cả (i+1) và (i-1):
```
Island 0 ↔ Island 1 ↔ Island 2 ↔ ... ↔ Island N ↔ Island 0
```

**Rate**: 10% top programs của mỗi island.

**Guards**:
- Skip nếu target island đã có identical solution
- Skip nếu program đã là migrant (tránh exponential duplication)

Migration xảy ra trong `add()` (sau khi thêm program mới), không phải trong vòng lặp
controller — đây là adaptation so với OpenEvolve gốc vì `DiscoveryController` không
gọi migration riêng.

---

## 8. Island Rotation

**Round-robin đơn giản** — sau mỗi `sample()`, island tăng lên 1:
```python
self.current_island = (self.current_island + 1) % self.num_islands
```

Không có UCB, không có adaptive selection. Mọi island được thăm đều nhau.

---

## 9. So sánh AdaEvolve vs OpenEvolve

| | AdaEvolve | OpenEvolve |
|---|---|---|
| **Archive** | UnifiedArchive (fitness + novelty score) | MAP-Elites grid (1 solution/cell) |
| **Diversity** | k-NN novelty, explicit elite_score | Tự nhiên qua MAP-Elites cells |
| **Parent sampling** | Adaptive intensity dựa trên G (accumulated signal) | Tỉ lệ cố định 20/70/10 |
| **Island rotation** | UCB (ưu tiên island productive gần đây) | Round-robin đều nhau |
| **Context programs** | Local diverse + global top (60/40) | Local only: best + elite + nearby cells |
| **Stagnation response** | Paradigm breakthrough (LLM sinh ý tưởng mới) | Không có |
| **Island spawning** | Dynamic khi global productivity thấp | Không có |
| **Prompt guidance** | Label exploration/exploitation + paradigm | Không có label hay mode guidance |
| **Migration topology** | Ring một chiều (i → i+1) | Ring hai chiều (i → i±1) |
| **Complexity** | Cao — nhiều cơ chế thích nghi | Thấp — đơn giản, tỉ lệ cố định |

OpenEvolve đơn giản hơn nhiều — không có cơ chế thích nghi, mọi tỉ lệ đều cố định.
MAP-Elites là cơ chế duy nhất để duy trì diversity. Phù hợp khi muốn một baseline
ổn định, ít hyperparameter cần tuning.
