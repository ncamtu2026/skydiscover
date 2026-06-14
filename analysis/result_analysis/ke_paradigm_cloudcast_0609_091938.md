# Phân tích Improvement — CloudCast `ke_paradigm_0609_091938`

> **Run:** `benchmarks/ADRS/cloudcast/outputs/reproduce/ke_paradigm_0609_091938`
> **Metric chính:** `combined_score = 1 / total_cost` — score cao hơn = tổng transfer cost thấp hơn.
> **Tổng checkpoints:** 98 | **Tổng improvement events:** 6

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | Total Cost | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|---|
| **CK 1** | None → **0.000997** | 1003 | — (baseline) | Full rewrite (initial solution) | Giải pháp đầu tiên được sinh ra, không có baseline để so sánh. Đặt nền tảng cho các iteration tiếp theo. | Improve from solution | None |
| **CK 3** | 0.000997 → **0.001005** | 995 | +0.9% | Multi-path distribution routing | Phân phối broadcast qua nhiều path song song thay vì một path duy nhất, giúp giảm tắc nghẽn trên từng link. Chi phí mỗi link được chia sẻ giữa các partition → tổng cost thấp hơn. | Improve from solution | None |
| **CK 17** | 0.001005 → **0.001375** | 727 | +36.8% | Hierarchical Aggregation via Spectral Clustering | Spectral clustering nhóm destination theo topology đồ thị, đưa traffic qua cluster gateway để tận dụng link rẻ trong nội bộ cluster. Giảm số lần đi qua các inter-cluster link đắt → tổng cost giảm mạnh. | **Paradigm breakthrough (meta analysis)** | **[2]** *Rethinking Graph Partitioning* |
| **CK 18** | 0.001375 → **0.001437** | 696 | +4.5% | Hierarchical Aggregation via Spectral Clustering (refined) | Tinh chỉnh cùng paradigm CK17: điều chỉnh số cluster và cách chọn gateway để phù hợp hơn với topology thực tế. Cải thiện marginal nhưng đáng kể trong bước fine-tune. | **Paradigm breakthrough (meta analysis)** | **[2]** *Rethinking Graph Partitioning* |
| **CK 33** | 0.001437 → **0.001453** | 688 | +1.1% | Partitioned Broadcast Trees using Label Propagation | Label propagation phát hiện cộng đồng tự nhiên trong đồ thị, xây Steiner tree cục bộ cho từng community. Chia nhỏ bài toán global thành sub-problem cục bộ giúp tìm cây rẻ hơn. | **Paradigm breakthrough (meta analysis)** | **[4]** *POP: The Art of Cutting Optimization Problems Down to Size* |
| **CK 34** | 0.001453 → **0.001548** | 646 | +6.5% | Partitioned Broadcast Trees using Label Propagation (refined) | Tinh chỉnh thêm cách xây Steiner tree trong mỗi partition từ paradigm CK33. Kết hợp tốt hơn giữa in-partition tree và inter-partition routing → tổng cost giảm thêm. | **Paradigm breakthrough (meta analysis)** | **[4]** *POP: The Art of Cutting Optimization Problems Down to Size* |

---

## Nhận xét tổng quan

- Hai improvement đầu (CK1, CK3) là **improve from solution** với improvement nhỏ (+0.9%).
- Ba bước tiếp theo đều do **paradigm breakthrough**: CK17 có bước nhảy lớn nhất (+36.8%) với Spectral Clustering.
- Cả hai paradigm thành công (Spectral Clustering và POP-based) đều lấy ý tưởng từ paper cụ thể.
- Final best total cost: **646** (giảm 35.6% so với baseline ~1003), stuck từ CK34 đến hết run.
