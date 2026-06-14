AdaEvolve chạy một **vòng lặp tiến hóa**: mỗi iteration chọn một "quần thể con" (island), lấy một program làm parent và 4 programs đi kèm làm context, nhờ LLM viết ra chương trình con mới, chạy đánh giá, lưu kết quả.

Khi khởi động sẽ có 2 island, mỗi island có tối đa 20 programs. Mỗi island có preset tính cách tương ứng được khởi tạo từ đầu và không đổi đến cuối (balanced, quality, diversity, pareto, exploration). 2 island đầu sẽ là `balanced`. Nếu có thêm program muốn vào, nó phải có điểm số `elite_score` hơn program có điểm số này thấp nhất, điểm số này bị ảnh hưởng bởi preset tính cách. Đây cũng là thứ duy nhất preset tính cách ảnh hưởng.

Thứ làm nó khác biệt là 4 cơ chế cốt lõi sau.

### Signal tích lũy G (per island): Cách chọn program trong 1 island
**File**: `adaptation.py`, class `AdaptiveState`
Mỗi island giữ một số `G` — tín hiệu cải thiện tích lũy. Mỗi lần có program mới tốt hơn:
```python # adaptation.py:99-107
raw_delta = fitness - self.best_score
normalized_delta = self._normalize_delta(raw_delta)  # chia cho abs(best_score)

# G_t = ρ * G_{t-1} + (1-ρ) * δ²
self.accumulated_signal = self.decay * self.accumulated_signal + (1 - self.decay) * (normalized_delta**2)
```
Từ `G`, tính ra `intensity` — tỉ lệ explore vs exploit:
```python # adaptation.py:152-157
intensity = I_min + (I_max - I_min) / (1 + sqrt(G + ε))
```
**Ý nghĩa đơn giản**: Island đang cải thiện nhiều → `G` cao → `intensity` thấp → **khai thác** (exploit, dùng program tốt nhất làm gốc). Island đang giậm chân → `G` gần 0 → `intensity` cao → **thám hiểm** (explore, chọn parent ngẫu nhiên/đa dạng).
Từ `intensity`, quyết định _cách chọn parent_ và _nhét label gì vào prompt_:
```python
# database.py:556-562
rand = random.random()
if rand < intensity:
    mode = "exploration"       # chọn parent ngẫu nhiên/novelty
elif rand < intensity + (1-intensity)*0.7:
    mode = "exploitation"      # chọn parent tốt nhất
else:
    mode = "balanced"
```
Mỗi mode gắn với một **đoạn text khác nhau nhét vào đầu prompt** cho LLM `database.py:41-65`.

### UCB chọn island: "Iteration vào island nào?"
**File**: `adaptation.py`, method `select_dimension_ucb` + `database.py:784-785`
Khi có nhiều island, mỗi cuối iteration gọi UCB để chọn island tiếp theo:
```python # adaptation.py:430-452
reward_avg = dimension_rewards[i] / decayed_visits[i]   # phần thưởng gần đây
exploration_bonus = C * sqrt(ln(total_iterations) / raw_visits)  # UCB classic

ucb_score = reward_avg + exploration_bonus
```
Điểm tinh tế: `reward_avg` dùng **decayed visits** (trọng số giảm dần theo thời gian), còn `exploration_bonus` dùng **raw visits**. Mục đích: island tìm được đột phá lâu rồi thì phần thưởng _phai đi_ → không "ký ức hóa" một breakthrough cũ mà bỏ qua những island đang tiến bộ.
```python
#database.py:784-785
if self.use_ucb_selection:
    self.current_island = self.adapter.select_dimension_ucb(iteration)
```


### Paradigm Breakthrough
**File**: `paradigm/generator.py`, `controller.py:290-310`
Khi `ParadigmTracker` phát hiện toàn hệ thống đang stagnate (cải thiện toàn cục dưới ngưỡng), trigger một lần gọi LLM _riêng_ để sinh ra "ý tưởng đột phá":
```python
# controller.py:295-310
if self.database.use_paradigm_breakthrough and self.database.is_paradigm_stagnating():
    await self._generate_paradigms_if_needed()
```
LLM dùng framework 6 bước: hiểu bài toán → phân tích evaluator → xác định metric → ràng buộc → cấu trúc bài toán → cơ hội cải tiến. Output là danh sách `paradigm_ideas` (structured JSON). Ý tưởng này được nhét vào prompt các iteration sau.
Khi paradigm active:
```python
# controller.py:455-461
if paradigm:
    best_program = self.database.get_best_program()
    parent_dict = {parent_label: best_program}  # force dùng best làm parent
```
### Migration giữa các island
Mỗi `migration_interval` iteration (mặc định 15), copy top programs của island này sang island kế (ring topology):
```python
# database.py:793-814
if self.use_migration and iteration % self.migration_interval == 0:
    # copy top programs từ island src → island (src+1) % n
```
Migration _không cộng reward UCB_ cho island nhận, vì nó không tự tìm ra:
```python
# adaptation.py:370-380
# NOTE: We do NOT update improvement_count or total_evaluations
# because the island didn't earn this improvement
```
### Tạo mới island
```python
# database.py:2003-2041
def _should_spawn_island(self):
    if not self.use_dynamic_islands:      # 1. tính năng phải bật
        return False
    if not self.use_unified_archive:      # 2. phải dùng archive mode
        return False
    if not self.programs:                 # 3. phải có ít nhất 1 program
        return False
    if self.num_islands >= self.max_islands:     # 4. chưa đạt giới hạn (max=5)
        return False
    if iterations_since_spawn < self.spawn_cooldown:  # 5. cooldown 30 iter
        return False
    
    # Điều kiện cốt lõi: TẤT CẢ island đều ì ạch
    global_productivity = self.adapter.get_global_productivity()
    if global_productivity >= 0.015:      # ngưỡng 1.5%
        return False
    
    return True  # ← chỉ spawn khi toàn hệ thống đang kẹt
```
**Ý nghĩa**: đây là nước đi "thoát local optima" ở cấp quần thể — khi cả 2 island đều stagnate, thay vì chờ, hệ thống **mở thêm một mặt trận mới**. Island mới được seed bằng top 5 program tốt nhất từ các island hiện tại, nhưng với `AdaptiveState` sạch (G=0 → intensity cao → explore ngay).

Island mới nhận preset **chưa được dùng hoặc ít dùng nhất** trong 5 preset:
```python
# database.py:2116-2124
usage_counts = {preset["name"]: 0 for preset in ISLAND_CONFIG_PRESETS}
for name in self.island_config_names:
    usage_counts[name] += 1
# chọn ngẫu nhiên trong số preset ít được dùng nhất
underused = [p for p in ISLAND_CONFIG_PRESETS if usage_counts[p["name"]] == min_usage]
selected = random.choice(underused)
```
Island không bao giờ bị xoá.