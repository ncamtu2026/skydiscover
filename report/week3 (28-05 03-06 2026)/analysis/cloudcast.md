### Questions
- Các cải tiến thành công là gì?
- Nhờ đâu đạt được các cải tiến thành công?
- Bị stuck khi nào?
- Nguyên nhân tại sao stuck?
- So sánh Deepseek và GLM 4.7 -> Phương pháp model nào tốt hơn? Tại sao tốt hơn? Làm sao để model còn lại cũng đạt được điểm tốt đó -> gap của mô hình ấy.
### Phân tích
- Mô tả bài toán: gửi 1 file lớn đến nhiều đích khác nhau, sao cho chi phí tối thiểu.
#### Phân tích các cải tiến thành công/thất bại
- GLM-4.7
	- iter 2: 
		- dijstra -> steiner tree
			- Ý tưởng là các đích có thể chung đường đi, nên thay vì gửi file đi lại nhiều lần, thì ta tìm đường dùng chung để đi.
			- Cải thiện: cost 1035 -> 961
	- iter 18:
		- thay vì tự implement steiner tree -> dùng steiner tree trong thư viện NetworkX
		- 961 -> 891
		- Câu hỏi: implement trong NetworkX hơn như nào
	- iter 21:
		- chuyển từ dùng steiner tree sang Arborescence
			- steiner tree -> tìm bộ cạnh có chi phí nhỏ nhất sao cho nối được mọi điểm -> từ đó có thể tại sử dụng cạnh -> build graph to
			- arborescence -> làm sao để xây 1 cây mà từ một điểm đến mọi điểm khác sao cho cây đó có tổng chi phí thấp nhất
		- Câu hỏi: trong trường hợp nào mà Arborescence lại tốt hơn steiner tree, có log được thông tin evaluate đó không.
	- iter 30:
		- chuyển sang dùng Hierarchical Zone-Based Routing
		- Dự đoán: vấn đề là steiner tree nó luôn ưu tiên đường ngắn nhất, traffic các đường bị cao lên, trong khi có thể tận dụng các đường khác. Zone-based tư duy bài toán thành thay vì tìm đường trực tiếp đến đích, gom đích thành các zone, mục tiêu là chuyển vào zone trước, rồi mới tìm đến đích. Cái mục tiêu chuyển tới là gateway, một node mà tổng cost đến các node trong community là thấp nhất.
	* ##### Tổng quan: Stagnation hoàn toàn từ iteration 30
		
		**Từ checkpoint_40 đến checkpoint_100: 0 improvement trong 70 iterations liên tiếp.**
		
		Best score đứng yên ở `0.001519` (avg_cost = 131.43) — cùng program từ iteration 30.
		
		---
		
		###### Các ý tưởng đã thử và tại sao không improve
		
		Tất cả ideas từ iteration 31-100+ đều thuộc 5 nhóm, **đều thất bại vì cùng một lý do gốc rễ:**
		
		###### Nhóm 1 — Flow optimization (thử đi thử lại nhiều lần)
		
		- `min_cost_flow`, `network_simplex`, `scipy.linprog` Multi-Commodity Flow
		- Successive Shortest Path with Residual Graphs
		
		→ Optimize đúng thứ sai: minimize tổng `flow × edge_cost` nhưng **bỏ qua hoàn toàn instance_cost** (runtime × nodes × $0.54/hr). Flow formulation không model được chiều "throughput thấp → runtime dài → tốn thêm tiền VM cho toàn topology".
		
		###### Nhóm 2 — Biến thể cây (Steiner/Arborescence, thử lại nhiều lần)
		
		- Steiner Tree approximation (đã thành công ở cp_18, thử lại 4-5 lần)
		- Minimum Spanning Arborescence (đã thành công ở cp_21, thử lại 3-4 lần)
		
		→ Search đang **rediscover lại các thuật toán đã từng là best** với framing khác nhau. Ceiling của nhóm này đã đạt được rồi. Incremental variation không phá được barrier.
		
		###### Nhóm 3 — K-Shortest Paths / Multi-path
		
		- Yen's K-Shortest Paths, Edge-Disjoint paths, partition load balancing
		
		→ Ý tưởng split partitions across nhiều path đúng về nguyên tắc (throughput cao hơn = runtime ngắn hơn = instance cost thấp hơn), nhưng các implementation vẫn dùng `weight='cost'` để chọn path → không thực sự tận dụng được throughput.
		
		###### Nhóm 4 — Graph structure analysis
		
		- Spectral Partitioning, Edge Betweenness Centrality, Multi-Gateway Hierarchical Routing
		
		→ Community detection đã là winner ở cp_30 rồi. Các biến thể spectral/betweenness không tốt hơn vì không phản ánh sát cost structure thực tế của network bằng greedy modularity.
		
		###### Nhóm 5 — "Congestion-aware" variants (gần đúng nhất nhưng vẫn sai)
		
		- Congestion-Aware Pricing, Capacity-Aware Multi-Path Partitioning, Iterative Congestion-Aware Routing with Dynamic Edge Costs
		
		→ Ý tưởng gần đúng nhất. Nhưng implementation điều chỉnh edge weight dựa trên `throughput capacity`, **không phải dựa trên impact thực lên instance_cost**. Công thức đúng phải là:
		
		```
		effective_weight = egress_cost + (num_nodes × 0.54/3600) × (data_vol / throughput)
		```
		
		Không có implementation nào đến được đây.
		
		---
		
		###### Lý do gốc rễ của stagnation
		
		Search đang bị mắc kẹt trong một **local optimum về mặt conceptual** — tất cả các paradigm được generate đều là biến thể của "chọn path tốt nhất trên edge cost". LLM không biết được công thức `__total_cost()` thực tế trong simulator, nên:
		
		1. Không biết instance_cost tồn tại và phụ thuộc vào runtime
		2. Không biết runtime phụ thuộc vào throughput bottleneck
		3. Không biết egress limit của AWS (5 Gbps) tạo ra bottleneck lớn khi nhiều flow đổ vào
		
		Để phá vỡ ceiling này cần thay đổi **objective function** được đưa vào thuật toán, không phải thay đổi thuật toán routing.
- Deepseek-V4-Pro
	## Hướng 1 — cloudcast_0529_1448 -> Deepseek
	
	### Tiến trình
	
	**cp_1 → avg_cost 155.10** — Baseline: Dijkstra riêng lẻ cho từng destination.
	
	**cp_4 → 145.69** (-6%) Greedy multi-source Dijkstra với penalty diversity: build 3 candidate trees, penalize edges đã dùng để cây sau đi đường khác, chọn cây rẻ nhất. Improve vì lần đầu khai thác shared edges giữa destinations.
	
	**cp_5 → 138.47** (-5%) Tăng lên 10 candidates + random noise ±15% + tree pruning. Improve vì khám phá không gian rộng hơn, prune bỏ intermediate nodes thừa.
	
	**cp_8 → 123.62** (-11%) ← ceiling **Dreyfus-Wagner exact DP**: Floyd-Warshall all-pairs → DP bitmask `dp[mask][v]` trên mọi subset của terminals × mọi node. Tìm Steiner tree tối ưu chính xác. Improve lớn vì thay thế hẳn greedy approximation bằng exact algorithm.
	
	**cp_9 trở đi → stagnation hoàn toàn** Mọi idea sau (LP, min-cost flow, residual graphs, GRASP, annealing) đều optimize cùng objective. Không thể beat exact algorithm trên chính objective đó.
	
	---
	
	## Hướng 2 — cloudcast_0601_1526 -> Deepseek
	
	### Tiến trình
	
	**cp_1 → avg_cost 192.33** — Baseline khác, điểm xuất phát cao hơn.
	
	**cp_18 → 178.23** (-7%) Chuyển từ manual KMB sang `networkx.approximation.steiner_tree` (convert sang undirected trước). Improve vì undirected Steiner tree tận dụng được asymmetric cost tốt hơn cách dựng MST thủ công.
	
	**cp_21 → 138.86** (-22%) **Minimum Spanning Arborescence**: build subgraph từ shortest paths giữa các cặp terminal, sau đó `nx.minimum_spanning_arborescence`. Improve lớn vì làm việc trực tiếp trên directed graph — không mất thông tin asymmetry của cloud transfer costs.
	
	**cp_30 → 131.43** (-5%) **Community-based hierarchical routing**: `greedy_modularity_communities` nhóm nodes → chọn gateway cho mỗi cluster → route `src → gateway → dsts`. Improve vì community structure tự nhiên phản ánh cost structure (intra-provider rẻ hơn), giảm số cross-region hops đắt.
	
	**cp_40 trở đi → stagnation hoàn toàn** Tất cả paradigms tiếp theo đều xoay quanh LP / flow / Steiner variants — đều optimize sai objective hoặc đã bị exact algorithm vượt qua rồi.
	
	---
	
	## Tại sao Hướng 1 thắng hẳn
	
	||Hướng 1 (Dreyfus-Wagner)|Hướng 2 (Community-based)|
	|---|---|---|
	|Best avg_cost|**123.62**|131.43|
	|Chênh lệch|—|~$8/config (+6%)|
	
	**Lý do cốt lõi:**
	
	Dựa trên cost model của simulator — `partitions` là SET nên sharing edges là free — tổng egress cost bằng đúng `data_vol × Σ unique edge costs`. Đây là bài toán **Minimum Steiner Tree** chính xác.
	
	- **Dreyfus-Wagner** giải exact bài toán đó với k=6-7 terminals. Kết quả là global optimum.
	- **Arborescence** bị lệch objective: phải span ALL nodes trong subgraph thay vì chỉ terminals → tree structure bị distort → edges thừa → cost cao hơn.
	- **Community-based** là heuristic 2-level hierarchy: community clustering ≠ cost-optimal Steiner points, bỏ lỡ các cấu trúc tree phức tạp hơn không theo hierarchy.
	
	Hướng 1 thắng vì nó nhận ra đúng bản chất bài toán (Steiner tree) và dùng exact algorithm cho nó. Hướng 2 tiệm cận dần từ nhiều góc khác nhau nhưng không bao giờ formulate đúng objective.




Chốt giải thích hiện tại:
- GLM chọn hướng đúng từ đầu, nhưng lại implement với thư viện xấp xỉ steiner tree -> thử đi thử lại fail -> đổi hẳn hướng sang Arborescence -> sau đó đổi sang community-based
- Deepseek cũng định hướng từ đầu steiner tree, nhưng dám implement build exact steiner tree -> thành công do bài toán nhỏ -> to lên là chết với độ phức tạp.
- Nhận xét thêm: cả 2 bài mới tối ưu 1 cost là cost vận chuyển, chưa tính đến câu chuyện về instance cost (gửi càng lâu thì instance cost càng cao) -> nếu gửi quá nhiều vào 1 đường cost thấp nhất về lý thuyết mà không để tâm đến instance cost do delay gửi lâu -> cost cứ thế mà tăng.
- Khi nào instance cost gửi 1 đường chết, cần chia, khi src đưa đến 2 dst khác nhau, 2 dst này có thời điểm chung đường, tổng vận chuyển chúng cao hơn limit -> chia ra -> chậm, trong khi còn đường khác có thể đi -> đây là yếu tố chưa được consider.