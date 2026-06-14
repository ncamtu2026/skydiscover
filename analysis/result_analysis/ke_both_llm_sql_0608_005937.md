# Phân tích Improvement — LLM SQL `ke_both_0608_005937`

> **Run:** `benchmarks/ADRS/llm_sql/outputs/reproduce/ke_both_0608_005937`
> **Metric chính:** `combined_score` — prefix cache hit rate (cao hơn = tốt hơn).
> **Tổng checkpoints:** 84 | **Tổng improvement events:** 6

---

## Bảng tổng hợp

| Checkpoint | Score (prev → new) | % Improve | Method | Lý do improve (2 câu) | Chế độ sinh | Paper Attribution |
|---|---|---|---|---|---|---|
| **CK 1** | None → **0.4690** | — (baseline) | Dynamic column prioritization dựa trên contribution đến prefix hit rate | Giải pháp đầu tiên áp dụng dynamic resource allocation: ưu tiên column theo contribution đến prefix hit rate, và khai thác cấu trúc lặp lại giữa các query. Đặt baseline ở mức 0.469. | Improve from solution | **[5]** *RobinHood*, **[1]** *Parrot* |
| **CK 2** | 0.4690 → **0.4690** | ~0.0% (marginal) | Full rewrite — minor variant | Cải tiến cực nhỏ, về thực tế không đổi so với CK1. Hệ thống thử variant khác của cùng ý tưởng. | Improve from solution | None |
| **CK 3** | 0.4690 → **0.6218** | +32.6% | Full rewrite — major algorithm change | Bước nhảy lớn nhất: thay đổi hoàn toàn cách reorder columns, có thể chuyển sang approach greedy/frequency-based mạnh hơn. Chưa có paper attribution rõ ràng, LLM tự sinh thuật toán mới. | Improve from solution | None |
| **CK 6** | 0.6218 → **0.6358** | +2.2% | Full rewrite — refinement | Tinh chỉnh thuật toán từ CK3, cải thiện cách tính score cho từng column. Marginal improvement nhưng ổn định qua các test case. | Improve from solution | None |
| **CK 7** | 0.6358 → **0.6445** | +1.4% | Full rewrite — refinement | Tiếp tục tinh chỉnh, cải thiện thêm tiêu chí ưu tiên column. Chuỗi improve from solution ngắn hạn. | Improve from solution | None |
| **CK 12** | 0.6445 → **0.6456** | +0.2% | Full rewrite — minor refinement | Cải thiện nhỏ cuối cùng trước khi stuck. Hệ thống đã gần plateau, các full rewrite tiếp theo không tạo ra đột phá mới. | Improve from solution | None |

---

## Nhận xét tổng quan

- Tất cả 6 improvement đều là **improve from solution** — không có paradigm breakthrough nào thành công trong run này.
- Bước nhảy lớn nhất là CK3 (+32.6%) nhưng không có paper attribution và không phải paradigm breakthrough.
- KE both (cả parent lẫn paradigm KE) nhưng run này stuck sớm ở CK12 (score 0.6456) và không cải thiện thêm trong 72 checkpoint còn lại.
- So sánh với ke_paradigm (0.715) và ke_parent (0.699), run ke_both này có final score thấp hơn đáng kể — có thể do interference giữa hai KE mode.
- Final best score: **0.6456**.
