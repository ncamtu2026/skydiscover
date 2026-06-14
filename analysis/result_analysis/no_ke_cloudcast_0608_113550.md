# Phân tích Improvement — CloudCast `no_ke_0608_113550`

> **Run:** `benchmarks/ADRS/cloudcast/outputs/reproduce/no_ke_0608_113550`
> **Metric chính:** `combined_score = 1 / total_cost` — score cao hơn = tổng transfer cost thấp hơn.
> **Tổng checkpoints:** 93 | **Tổng improvement events:** 7

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | Total Cost | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|---|
| **CK 1** | None → **0.001005** | 995 | — (baseline) | Parallel paths + load balancing | Giải pháp đầu tiên dùng nhiều path song song để phân tải. Đặt baseline với chi phí ~995. | Improve from solution | None |
| **CK 6** | 0.001005 → **0.001050** | 952 | +4.5% | Steiner tree approximation + path sharing | Thêm Steiner tree approximation để chia sẻ edge giữa các destination thay vì routing hoàn toàn độc lập. Edge sharing trực tiếp giảm tổng chi phí broadcast. | Improve from solution | None |
| **CK 10** | 0.001050 → **0.001057** | 945 | +0.7% | Proximity-ordered Steiner tree | Sắp xếp thứ tự thêm node vào tree theo độ gần (proximity) thay vì ngẫu nhiên. Gắn node gần nhau trước giúp tận dụng các link rẻ nội bộ nhiều hơn. | Improve from solution | None |
| **CK 15** | 0.001057 → **0.001125** | 889 | +6.4% | Steiner Tree via MST + Metric Closure (KMB heuristic) | Áp dụng đúng thuật toán KMB: xây metric closure của các terminal rồi lấy MST — có nền tảng lý thuyết tốt hơn so với heuristic proximity trước đó. Kết quả cây tối ưu hơn và ổn định hơn qua các test case. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |
| **CK 23** | 0.001125 → **0.001294** | 773 | +15.0% | Hierarchical Region-Based Broadcast using Spectral Clustering | Spectral clustering phân vùng destination theo cấu trúc graph (2 cấp), route qua cluster medoid trước rồi mới đến từng node. Giảm số lần đi qua inter-region link đắt, tương tự kiến trúc hub-and-spoke. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |
| **CK 29** | 0.001294 → **0.001321** | 757 | +2.1% | Iterative Path Construction with Shared-Edge Discounting | Sau mỗi lần thêm path, giảm weight các edge đã dùng để khuyến khích tái sử dụng. Discount động này tạo ra cây Steiner với nhiều edge shared hơn approach greedy thông thường. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |
| **CK 31** | 0.001321 → **0.001511** | 662 | +14.4% | Directed Steiner Tree via Minimum Spanning Arborescence (KMB) | Thay MST undirected bằng Edmonds' Minimum Spanning Arborescence để xử lý đúng đồ thị có hướng — tránh path vô hiệu trong directed graph. KMB + arborescence cho approximation ratio tốt nhất trong các approach đã thử. | **Paradigm breakthrough (meta analysis)** | None (hallucinated) |

---

## Nhận xét tổng quan

- Ba improvement đầu (CK1, CK6, CK10) là **improve from solution** với improvement nhỏ, không có paper attribution.
- Bốn improvement sau đều do **paradigm breakthrough** — LLM có cite paper nhưng toàn bộ là **hallucination** (không có paper nào trong knowledge base).
- Tổng có **7 improvement events** — nhiều nhất trong các CloudCast runs, nhưng final score bằng ke_parent (0.001511).
- Không có KE nên LLM tự "phát hiện lại" các thuật toán (Steiner Tree, Spectral Clustering, Arborescence) nhưng mất nhiều iteration hơn và không có grounding từ paper thực.
- Final best total cost: **662** (giảm 33.5% so với baseline 995).
