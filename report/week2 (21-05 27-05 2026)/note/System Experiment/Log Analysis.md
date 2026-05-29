# Start Phase
**Island** (đảo) = một population độc lập. AdaEvolve dùng nhiều islands để tìm kiếm theo nhiều "hướng" khác nhau, tránh hội tụ sớm vào local optimum.
Initial program **được nhân bản** vào tất cả islands. Từ source code (`_ensure_all_islands_seeded`)
```
# Island 0: giữ program gốc
self.add(program, iteration=0, target_island=0)

# Island 1+: tạo bản copy với UUID mới
copy = Program(id=str(uuid.uuid4()), solution=program.solution, ...)
self.add(copy, iteration=0, target_island=1)
```


`decay=0.9` — Hệ số suy giảm của signal cải thiện G
Mỗi island duy trì một **tín hiệu tích lũy G** (Accumulated Improvement Signal), đo lường "đảo này có đang cải thiện không?". Công thức từ `adaptation.py`:

```
G_mới = decay × G_cũ + (1 - decay) × (cải_thiện_normalized)²
```

- `decay = 0.9` → G "nhớ" 10 lần gần nhất (trọng số giảm dần theo hàm mũ)
- Khi island tìm được solution tốt hơn: G tăng (đảo đang "năng suất")
- Khi không cải thiện: G giảm dần về 0
G được dùng để tính **search intensity** (nên explore hay exploit).


`ucb_selection=True` — Chọn island bằng UCB
**UCB = Upper Confidence Bound** — thuật toán chọn island nào sẽ được "chạy" ở iteration tiếp theo. Công thức UCB kinh điển:

```
UCB(island_i) = reward_avg(i) + C × √(ln(total_visits) / visits(i))
```

- **reward_avg**: điểm cải thiện trung bình của đảo (đảo tốt → exploitation)
- **Phần √**: bonus cho đảo ít được thăm (đảo chưa khám phá → exploration)
- **C = 1.41** (√2): hệ số cân bằng explore/exploit
Khi `False` (ablation): dùng round-robin đơn giản (`(iter + 1) % num_islands`).


`dynamic_islands=True` — Tự động sinh đảo mới
Khi **global productivity** (tỷ lệ iterations có cải thiện) giảm xuống dưới `spawn_productivity_threshold = 0.015`, hệ thống tự spawn thêm đảo mới (tối đa `max_islands = 5`), có `spawn_cooldown = 30` iterations giữa các lần spawn. Mỗi đảo mới được seed từ chương trình tốt nhất hiện tại. Với run 2 iterations, điều này cũng không kích hoạt.

# Process Phase

Iteration n: Chọn 1 island (UCB) → Gọi LLM → Sinh code → Evaluate → Cập nhật archive

## LLM SQL Original
Phân tích timeline thực nghiệm:
- Khởi động + eval chương trình ban đầu: 110.61s
	Chương trình ban đầu failed khi process beer.csv
- Iteration 1 (llm + eval) First Attempt: (llm: ?s, eval: 385s)
	- movies.csv: 25s
	- beer.csv: 54s
	- bird.csv: 10s
	- pdmx.csv: 231s
	- products.csv: 65s (TIMEOUT do quá 360s) => retry với attemp 2nd
- Iteration 1 (llm + eval) Second Attempt: 424.32s (llm: 110.99s, eval: 313.33s)
	- movies.csv: 7s
	- beer.csv: 33s
	- bird.csv: 2s
	- pdmx.csv: 83s
	- products.csv: 4s
- Iteration 2 (llm + eval) First Attempt: 316.34s (llm: 62s, eval: 254s)
	- movies.csv: 4s
	- beer.csv: 11s
	- bird.csv: 2s
	- pdmx.csv: 83s
	- products.csv: 4s
- Test eval chương trình tốt nhất: eval ~260s
	- movies.csv: 4s
	- beer.csv: 11s
	- bird.csv: 2s
	- pdmx.csv: 87s
	- products.csv: 4s

Đối với task này, eval.py có thể thấy tiêu tốn nhiều thời gian hơn so với tổng thời gian runtime xử lí từng .csv. Lí do là vì eval.py còn phải thực hiện:
- Tính số row, lượng từ trước và sau evolve để kiểm tra
- Đọc csv (không nhiều)
- evaluate_df_prefix_hit_cnt() dùng để tính điểm đang dùng giải thuật Trie bản Python thuần (chậm) để tìm prefix chung
Ví dụ với bird.csv dù runtime (reorder) chỉ 2s nhưng lại là dataset nặng nhất với 400k dòng (bình thường chỉ 10k-20k)

=> Kết luận hiện tại: initial program quá yếu và eval.py đang phải xử lí nhiều tác vụ

Evidence: đã test lại với log debug in ra nhiều thông tin hơn, xem tại [[eval_timing_20260526_111709.log]]
Tốc độ trung bình 1 lần eval là 150s

Thực hiện tối ưu:
- Đếm số lượng từ theo cột thay vì theo hàng
- prefix_hit_cnt() đang cố dùng multi thread trong khi Python không cho phép multi thread thực sự (GIL), thực hiện refactor lại code
- cache dataset (ở bản cũ mỗi iteration sẽ thực hiện read_csv)

Sau khi tối ưu tốc độ trung bình 1 lần eval là 50s, nhanh gấp 3 lần
Log mới xem tại [[eval_timing_20260526_122942.log]]


## Cloudcast
Chương trình bị slowdown và nghẽn với iteration 20 lần, log tại [[adaevolve_20260526_211505.log]]

Ite 1: (llm: 86.01s, eval: 22.19s)
Ite 2: (llm: 51.29s, eval: 4.48s)
Ite 3: (llm: 19.89s, eval: 4.39s)
Ite 4: (llm: 15.06s, eval: 4.20s)
Ite 5: (llm: 88.53s, eval: 5.42s)
Ite 6: (llm: 39.48s, eval: 370.82s) => thuật toán có vấn đề computationally expensive
...
Có thể thấy eval trung bình sẽ khoảng ~5s, còn thời gian dành cho llm dao động mạnh từ 10-100s
Sau ite 15, hệ thống detect stagnation (score ~0.0015 từ iter 5 đến iter 15, không cải thiện) và ra quyết định generating breakthrough ideas (gọi API lên deepseek)
Generated 3 paradigms:
[1] Use networkx min_cost_flow to compute optimal broadcast flow (approach: networkx.algorithms.flow.min_cost_flow)
[2] Use minimum spanning arborescence to compute a directed broadcast tree (approach: networkx.algorithms.tree.minimum_spanning_arborescence)
[3] Use networkx Steiner tree approximation for undirected broadcast tree (approach: networkx.algorithms.approximation.steiner_tree)
Ở ite 16 & 17, mỗi ite hệ thống eval 3 program tương ứng 3 paradigm trên, nhưng đều timeout 600s

Sau đó (22:49) hệ thống tự archive 3 paradigm cũ, **sinh 3 paradigm mới gần giống hệt** (min_cost_flow, Dijkstra, Steiner) và tiếp tục timeout thêm.
Trong ite 18, từ đoạn thực hiện gen program với paradigm thứ 3 Steiner trở đi: LLM API call bị timeout. Mỗi program được evolve sẽ có tới 3 lần time out 10 phút (tổng 4 lần chờ 40p, ite chạy paradigm x3 program => 120p 1 ite)

Lí do có thể:
- DeepSeek API quá tải
- Context quá dài: Prompt chứa parent code + context programs + sibling history + error context + paradigm description. Khi paradigm kích hoạt, prompt phình to thêm 2-3 KB. Nhiều token input → TTFT (time-to-first-token) dài hơn
- Độ dài response: LLM sinh code có thể 200 dòng hoặc 2000 dòng. Dài hơn → streaming kéo dài

Thử nghiệm lại với log ra thông tin word count input, output: log tại [[llm_timing_20260527_203212.log]]

Có thể thấy lượng token input và output không dao động gì lớn, nhưng code của SkyDiscover cũng chỉ gọi thẳng API với timeout 600s chứ không làm gì thêm => Khả năng do server Deepseek TTFT cao.

Do test nhanh ite = 5, hiện tượng timeout LLM API chưa xuất hiện, treo máy đến trưa 28/05 để quan sát