# Phân tích Improvement — LLM SQL `ke_parent_0608_005937`

> **Run:** `benchmarks/ADRS/llm_sql/outputs/reproduce/ke_parent_0608_005937`
> **Metric chính:** `combined_score` — prefix cache hit rate (cao hơn = tốt hơn).
> **Tổng checkpoints:** 41 | **Tổng improvement events:** 9

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|
| **CK 1** | None → **0.6880** | — (baseline) | Column reorder greedy dựa trên stability + length | Giải pháp ban đầu với stability score và avg_len_sq kết hợp để ưu tiên column. Baseline cao 0.688, tốt hơn ke_both ban đầu nhờ KE parent cung cấp context tốt hơn. | Improve from solution | None |
| **CK 7** | 0.6880 → **0.6882** | ~0.0% | Simplified stability metric — loại bỏ sqrt transformation | Bỏ phép sqrt trong tính stability score, dùng metric trực tiếp phản ánh đúng hơn giá trị prefix reuse. Metric đơn giản hơn lại capture được pattern tốt hơn metric phức tạp. | Improve from solution | **[2]** *Beyond LRU and Zipf* |
| **CK 11** | 0.6882 → **0.6882** | ~0.0% | Refined column statistics computation | Điều chỉnh nhỏ cách tính combined score cho column stats. Marginal improvement cực nhỏ, về thực tế không đổi. | Improve from solution | None |
| **CK 13** | 0.6882 → **0.6960** | +1.1% | Adaptive threshold — dynamic threshold thay vì binary classification | Thay hard binary threshold bằng dynamic critical score threshold — column có score cao đủ được ưu tiên dù không match hoàn toàn. Tránh mất mát các column có tiềm năng cao nhưng bị cut bởi threshold cứng. | Improve from solution | **[3]** *The dLoRA System* |
| **CK 16** | 0.6960 → **0.6966** | +0.1% | Transition probability metric cho column ordering | Đổi metric sang transition probability (xác suất một column xuất hiện sau column khác), phản ánh co-occurrence pattern tốt hơn stability đơn thuần. Cải thiện nhỏ nhưng ổn định. | Improve from solution | None |
| **CK 17** | 0.6966 → **0.6973** | +0.1% | Dynamic scheduling — cân bằng giữa current match và future potential | Kết hợp immediate match score với high-stability signal để balance giữa "chắc chắn ngay" và "tiềm năng tương lai". Tương tự load prediction trong scheduler, tránh greedy myopic. | Improve from solution | **[2]** *Llumnix* |
| **CK 20** | 0.6973 → **0.6973** | ~0.0% | Full rewrite — marginal variant | Rewrite hoàn toàn nhưng improvement cực nhỏ, hệ thống thử hướng khác nhưng không đột phá. | Improve from solution | None |
| **CK 22** | 0.6973 → **0.6983** | +0.1% | Full rewrite — incremental improvement | Tiếp tục full rewrite với cải thiện nhỏ. Hệ thống đang dần tiến đến plateau của improve-from-solution approach. | Improve from solution | None |
| **CK 24** | 0.6983 → **0.6986** | +0.0% | Full rewrite — marginal final improvement | Improvement rất nhỏ, thực tế là cuối chuỗi cải thiện. Không có paradigm breakthrough nào xuất hiện trong toàn bộ run. | Improve from solution | None |

---

## Nhận xét tổng quan

- **Tất cả 9 improvement** đều là **improve from solution** — không có paradigm breakthrough nào trong ke_parent run.
- KE parent cung cấp context từ solution tốt → baseline cao (0.688) nhưng thiếu paradigm KE nên không có bước nhảy lớn.
- Improvement lớn nhất là CK13 (+1.1%) nhờ paper [3] dLoRA adaptive threshold.
- Final best score **0.6986** — thấp hơn ke_paradigm (0.715) nhưng cao hơn ke_both (0.646).
- Kết quả cho thấy ke_parent giúp bắt đầu từ baseline tốt hơn, nhưng thiếu paradigm breakthrough để thoát khỏi local optimum.
