# Phân tích Improvement — LLM SQL `ke_paradigm_0608_005937`

> **Run:** `benchmarks/ADRS/llm_sql/outputs/reproduce/ke_paradigm_0608_005937`
> **Metric chính:** `combined_score` — prefix cache hit rate (cao hơn = tốt hơn).
> **Tổng checkpoints:** 54 | **Tổng improvement events:** 8

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|
| **CK 1** | None → **0.6556** | — (baseline) | Greedy reorder — maximize prefix hit count | Giải pháp ban đầu dùng greedy reorder column theo tần suất xuất hiện ở prefix. Đặt baseline ở mức 0.656, cao hơn nhiều so với ke_both ban đầu. | Improve from solution | None |
| **CK 5** | 0.6556 → **0.6716** | +2.4% | Vectorized column statistics computation | Chuyển sang tính stats column bằng vectorized operations, cho kết quả chính xác và nhanh hơn. Accuracy tốt hơn trong scoring → reorder đúng hơn → prefix hit cao hơn. | Improve from solution | None |
| **CK 8** | 0.6716 → **0.6877** | +2.4% | Adaptive greedy — cập nhật state sau mỗi column được chọn | Adaptive greedy cập nhật context sau mỗi lần chọn column, thay vì tính score tĩnh một lần. Phản ánh chính xác hơn prefix gain thực tế khi columns đã được sắp xếp. | Improve from solution | None |
| **CK 9** | 0.6877 → **0.6908** | +0.4% | Optimized greedy — tinh chỉnh scoring function | Tinh chỉnh hàm score để tính prefix contribution chính xác hơn. Cải thiện nhỏ nhưng ổn định. | Improve from solution | None |
| **CK 10** | 0.6908 → **0.6916** | +0.1% | Optimized greedy — minor refinement | Tiếp tục tinh chỉnh marginal, hệ thống đang tiến đến plateau của greedy approach. | Improve from solution | None |
| **CK 12** | 0.6916 → **0.6920** | +0.1% | Code simplification — loại bỏ redundant computation | Đơn giản hóa code giảm overhead tính toán, đồng thời làm rõ logic → tránh một số edge case. Improvement cực nhỏ nhưng ổn định hơn. | Improve from solution | None |
| **CK 32** | 0.6920 → **0.6984** | +0.9% | Modularity-based Column Grouping (community detection) | Dùng `greedy_modularity_communities` để nhóm các column hay xuất hiện cùng nhau, ưu tiên cả nhóm thay vì từng column riêng lẻ. Nhóm cohesive columns tăng prefix hit vì chúng thường đi kèm nhau trong query. | **Paradigm breakthrough (meta analysis)** | **[4]** *RobinHood Caching* |
| **CK 40** | 0.6984 → **0.7154** | +2.4% | Markov Chain-based Column Ordering | Xây Markov chain từ lịch sử query để model conditional dependency giữa các column — chọn column tiếp theo theo xác suất transition cao nhất. Markov model nắm bắt được pattern co-occurrence động thay vì chỉ frequency tĩnh. | **Paradigm breakthrough (meta analysis)** | **[1]** *Parrot: How Application-Centric Design Unlocks Massive Efficiency Gains* |

---

## Nhận xét tổng quan

- 6 improvement đầu đều là **improve from solution**, cải thiện dần dần thuật toán greedy.
- Hai paradigm breakthrough (CK32, CK40) đến muộn nhưng tạo ra improvement ổn định nhờ paper-inspired ideas.
- CK40 là bước nhảy cuối cùng và đạt **final best score: 0.7154** — cao nhất trong tất cả các LLM SQL runs.
- Markov Chain approach (CK40) hiệu quả nhất vì nắm bắt được dynamic co-occurrence thay vì static frequency.
- Sau CK40 (iteration 40/54), hệ thống stuck — 14 checkpoint cuối không cải thiện thêm.
