# Phân tích Improvement — CloudCast `ke_parent_0608_113550`

> **Run:** `benchmarks/ADRS/cloudcast/outputs/reproduce/ke_parent_0608_113550`
> **Metric chính:** `combined_score = 1 / total_cost` — score cao hơn = tổng transfer cost thấp hơn.
> **Tổng checkpoints:** 126 | **Tổng improvement events:** 6

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | Total Cost | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|---|
| **CK 1** | None → **0.000965** | 1035 | — (baseline) | Initial seed solution (Dijkstra per destination) | Giải pháp seed ban đầu, chạy Dijkstra độc lập cho từng destination. Không có sharing giữa các path. | Improve from solution | None |
| **CK 11** | 0.000965 → **0.001214** | 824 | +25.8% | Approximate Minimum Steiner Tree via Metric Closure (KMB) | Chuyển từ tìm path độc lập sang xây broadcast tree — cấu trúc tree tự nhiên chia sẻ bandwidth giữa các destination. KMB tạo MST trên metric closure của terminals, đảm bảo approximation tốt theo lý thuyết. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |
| **CK 23** | 0.001214 → **0.001280** | 781 | +5.4% | Greedy Shared-Cost Pruning via Incremental Path Merging | Tăng dần các path chia sẻ edge nhiều nhất, merge lại để tối đa hóa edge reuse. Phương pháp này tránh được chi phí dư thừa mà KMB đôi khi tạo ra khi merge path không hiệu quả. | **Paradigm breakthrough (meta analysis)** | None |
| **CK 34** | 0.001280 → **0.001416** | 706 | +10.6% | K-shortest paths with load balancing across partitions | Phân phối các partition qua K-shortest path song song thay vì một cây đơn, giảm bottleneck trên từng link. Cân bằng tải cho phép tận dụng nhiều đường song song với chi phí tổng thấp hơn. | Improve from solution | **[2]** *Automating High-Performance Group Communication on Multicore Systems* |
| **CK 35** | 0.001416 → **0.001511** | 662 | +6.7% | Approximate Steiner Tree with Minimum Spanning Arborescence | Dùng directed arborescence (Edmonds' algorithm) thay vì undirected MST để xử lý đúng đồ thị có hướng và chi phí bất đối xứng. Arborescence đảm bảo path hợp lệ trong directed graph → cost thấp hơn KMB undirected. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |
| **CK 112** | 0.001511 → **0.001511** | ~662 | ~0.0% (marginal) | Capacity-Aware Metric Closure — penalty factor cho bandwidth thấp | Thêm capacity penalty vào edge weight của metric closure, tự động né các link bottleneck. Cải thiện cực nhỏ (floating point), về thực tế xem như không đổi. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |

---

## Nhận xét tổng quan

- CK11 là bước nhảy lớn nhất (+25.8%) do chuyển từ paradigm "path finding" sang "tree construction".
- **CK34 là improvement duy nhất có paper attribution thực** — [2] *Automating HPC Group Communication*; các CK11, CK35, CK112 cite paper nhưng là **hallucination**.
- CK35 giải quyết nhược điểm của KMB trên directed graph bằng arborescence — cải thiện đáng kể.
- CK112 là improvement marginal gần như bằng 0 — hệ thống thực tế stuck từ CK35.
- Final best total cost: **~662** (giảm 36% so với baseline 1035).
