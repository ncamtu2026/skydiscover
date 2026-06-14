# Phân tích Improvement — CloudCast `ke_both_0609_091938`

> **Run:** `benchmarks/ADRS/cloudcast/outputs/reproduce/ke_both_0609_091938`
> **Metric chính:** `combined_score = 1 / total_cost` — score cao hơn = tổng transfer cost thấp hơn.
> **Tổng checkpoints:** 87 | **Tổng improvement events:** 5

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | Total Cost | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|---|
| **CK 1** | None → **0.001125** | 889 | — (baseline) | Minimum Steiner Tree via MST | Thay vì chạy Dijkstra độc lập cho từng destination, xây broadcast tree dạng MST để chia sẻ edge giữa nhiều destinations. Mỗi edge chỉ trả một lần nhưng phục vụ nhiều đích → giảm tổng chi phí. | Improve from solution | **[4]** *Automating High-Performance Group Communication on Multicore Systems* |
| **CK 2** | 0.001125 → **0.001271** | 787 | +13.0% | Shortest Path Heuristic (SPH) — Directed Steiner Tree | SPH tôn trọng hướng cạnh trong đồ thị có hướng, trong khi MST có thể tạo path không hợp lệ. SPH gắn destination gần nhất vào cây hiện tại theo thứ tự tăng dần, tạo tree chia sẻ nhiều edge hơn. | Improve from solution | **[4]** *Automating High-Performance Group Communication* |
| **CK 20** | 0.001271 → **0.001293** | 773 | +1.8% | Hierarchical Partitioned Optimization (POP-inspired) — Full rewrite | POP phân vùng các destination thành sub-problems nhỏ hơn, giải routing cục bộ để giảm độ phức tạp. Tổng hợp các solution cục bộ cho tổng cost thấp hơn so với SPH greedy toàn cục. | **Paradigm breakthrough (meta analysis)** | **[5]** *POP: The Art of Cutting Optimization Problems Down to Size* |
| **CK 23** | 0.001293 → **0.001511** | 662 | +16.9% | Minimum Spanning Arborescence + Pruning — k-means clustering theo graph topology | Dùng farthest-first clustering theo topology đồ thị để nhóm các destination địa lý gần nhau, sau đó xây MST arborescence trong mỗi cluster. Cluster tốt hơn → edge sharing cao hơn trong cluster → tổng chi phí thấp hơn POP phân vùng ngẫu nhiên. | **Paradigm breakthrough (meta analysis)** | None |
| **CK 78** | 0.001511 → **0.001602** | 624 | +6.0% | Zelikovsky's Iterative Steiner Component Heuristic | Thay vì greedy theo khoảng cách gần nhất (SPH), Zelikovsky chọn Steiner component nào giảm cost nhiều nhất mỗi bước — quyết định greedy tối ưu cục bộ hơn. Cây Steiner kết quả ngắn hơn đáng kể so với clustering hay SPH đơn thuần. | **Paradigm breakthrough (meta analysis)** | None |

---

## Nhận xét tổng quan

- **CK 1 & CK 2** dùng **improve from solution** (incremental evolution) và đều tận dụng paper [4] về broadcast tree trên multicore systems.
- **CK 20, 23, 78** đều do **paradigm breakthrough** — hệ thống meta-analyze các solution hiện có để sinh ra ý tưởng thuật toán hoàn toàn mới, không còn cải tiến tăng dần.
- Bước nhảy lớn nhất là **CK 23 (+16.9%)** khi chuyển từ random partition (POP) sang topology-aware clustering.
- Sau **CK 78** (iteration 78/100), không có thêm improvement — hệ thống stuck tại score **0.001602** đến hết run.
- Final best total cost: **624** (giảm 30% so với baseline seed ~889).
