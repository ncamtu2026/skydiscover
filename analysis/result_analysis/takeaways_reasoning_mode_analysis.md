# Phân tích Reasoning Mode — DeepSeek vs GLM4.7 (CloudCast & LLM SQL)

> **Dữ liệu:** 16 full runs (8 modes × 2 tasks), không có KE  
> **Models:** DeepSeek-V4-Pro, GLM-4.7  
> **Reasoning levels:** `high`, `medium`, `low`, `off` (không có reasoning)  
> **Không có KE** trong bất kỳ run nào — baseline thuần model capability

---

## 1. Bảng kết quả tổng hợp

### CloudCast (`combined_score = 1/total_cost`)

| Mode | Baseline | Final Score | Total Gain | First Big Jump | Tail Waste | #Impr |
|---|---|---|---|---|---|---|
| ds_high | 0.001353 | 0.001575 | +16.4% | CK 13 | 2.8% | 8 |
| ds_medium | 0.001202 | 0.001592 | +32.5% | CK 4 | 0.0% | 5 |
| ds_low | 0.001256 | 0.001614 | +28.5% | CK 2 | 9.7% | 7 |
| **ds_off** | 0.000965 | **0.001615** | +67.4% | CK 2 | 24.2% | 7 |
| glm47_high | 0.000973 | 0.001577 | +62.1% | CK 4 | 7.1% | 10 |
| **glm47_medium** | 0.001000 | **0.001577** | +57.7% | CK 8 | 12.9% | 6 |
| glm47_low | 0.000979 | 0.001511 | +54.3% | **CK 66** | 35.9% | 4 |
| glm47_off | 0.001005 | 0.001475 | +46.8% | CK 12 | 28.4% | 4 |

### LLM SQL (`combined_score` = prefix cache hit rate)

| Mode | Baseline | Final Score | Total Gain | First Big Jump | Tail Waste | #Impr |
|---|---|---|---|---|---|---|
| ds_high | 0.6505 | 0.7136 | +9.7% | CK 2 | 42.6% | 6 |
| ds_medium | 0.6356 | 0.6763 | +6.4% | None | 28.6% | 11 |
| **ds_low** | 0.7091 | **0.7222** | +1.8% | None | 59.5% | 4 |
| ds_off | 0.6697 | 0.6937 | +3.6% | None | 10.4% | 10 |
| glm47_high | 0.6582 | 0.7131 | +8.3% | CK 3 | 10.3% | 6 |
| glm47_medium | 0.6897 | 0.7199 | +4.4% | None | 16.5% | 16 |
| glm47_low | 0.6719 | 0.7181 | +6.9% | None | 21.4% | 12 |
| **glm47_off** | 0.6652 | **0.7302** | +9.8% | None | 59.8% | 13 |

---

## 2. "Nhiều reasoning hơn = tốt hơn" — Sai, theo cả 2 hướng

Rank 1=best, 4=worst theo từng level:

| Task | Model | high | medium | low | off | Trend |
|---|---|---|---|---|---|---|
| CloudCast | DeepSeek | 4 | 3 | 2 | **1** | ↓ nghịch chiều — off tốt nhất |
| CloudCast | GLM4.7 | **2** | **1** | 3 | 4 | ↑ thuận chiều (đến medium) |
| LLM SQL | DeepSeek | 2 | 4 | **1** | 3 | ↔ non-monotone, low tốt nhất |
| LLM SQL | GLM4.7 | 4 | 2 | 3 | **1** | ↓ nghịch chiều — off tốt nhất |

**Kết luận:**
- **DeepSeek CloudCast:** Càng nhiều reasoning càng tệ — ds_off (0.001615) vượt ds_high (0.001575) 2.5%.
- **GLM4.7 LLM SQL:** Tương tự — glm47_off (0.730) vượt glm47_high (0.713) 2.4%.
- **GLM4.7 CloudCast:** Ngược lại — medium/high tốt hơn off rõ rệt (+6.9% spread).
- **DeepSeek LLM SQL:** Non-monotone — ds_low tốt nhất nhưng chủ yếu do baseline cao (0.709), không phải do reasoning giúp ích.

> **Insight:** Hiệu quả của reasoning là model-dependent VÀ task-dependent, không có quy luật universal. Không nên mặc định "high reasoning = best".

---

## 3. Robustness qua các reasoning mode

| Task | Model | Max Score | Min Score | Spread (abs) | Spread (%) |
|---|---|---|---|---|---|
| CloudCast | DeepSeek | 0.001615 | 0.001575 | 0.000040 | **2.5%** ← robust |
| CloudCast | GLM4.7 | 0.001577 | 0.001475 | 0.000102 | **6.9%** ← sensitive |
| LLM SQL | DeepSeek | 0.722 | 0.676 | 0.046 | **6.8%** ← sensitive |
| LLM SQL | GLM4.7 | 0.730 | 0.713 | 0.017 | **2.4%** ← robust |

**Pattern chéo (cross-pattern):**
- DeepSeek **robust** trên CloudCast nhưng **sensitive** trên LLM SQL.
- GLM4.7 **sensitive** trên CloudCast nhưng **robust** trên LLM SQL.

Mỗi model có task phù hợp riêng — và trên task phù hợp thì cũng ổn định hơn về reasoning mode choice.

---

## 4. Model-task fit: ai mạnh hơn ở đâu?

| Task | Best DS score | Best GLM47 score | Winner |
|---|---|---|---|
| CloudCast | **0.001615** (ds_off) | 0.001577 (glm47_med) | **DeepSeek** +2.4% |
| LLM SQL | 0.7222 (ds_low*) | **0.7302** (glm47_off) | **GLM4.7** +1.1% |

> *ds_low có baseline cao nhất (0.709) — final score cao một phần do khởi điểm tốt, chỉ improve thêm +1.8%.

- **DeepSeek phù hợp CloudCast hơn** — task graph algorithm, cần insight thuật toán cụ thể.
- **GLM4.7 phù hợp LLM SQL hơn** — task heuristic ordering, cần grinding incremental improvements.

---

## 5. Behavioral pattern: DeepSeek "burst" vs GLM4.7 "grind"

### DeepSeek: front-loaded, burst pattern

- Cải thiện lớn xuất hiện sớm (CK2–4), sau đó plateau dài.
- CloudCast: ds_off tăng +32.5% ở CK2, rồi +18.2% ở CK5 — 80% tổng gain trong 5 iteration đầu.
- LLM SQL ds_high: +9% jump ở CK2, sau đó toàn các cải thiện dưới 0.1%.
- Số improvement events ít hơn nhưng mỗi event impact lớn hơn.

### GLM4.7: spread-out, grinding pattern

- Cải thiện rải đều hơn qua nhiều iteration.
- LLM SQL glm47_medium: **16 improvement events** trải dài 121 checkpoints — nhiều nhất trong tất cả.
- CloudCast glm47_high: 10 improvements từ CK2 đến CK93 — duy trì tìm kiếm đến cuối run.
- Một số trường hợp cực đoan: glm47_low CloudCast stagnate hoàn toàn đến CK67 rồi +46.6% burst.

| Characteristic | DeepSeek | GLM4.7 |
|---|---|---|
| Pattern | Burst (lớn sớm) | Grind (nhỏ đều) |
| Avg #improvements | 7.5 | 8.5 |
| First big jump (CCs) | CK2–13 | CK4–66 |
| Tail efficiency (CCs) | 9.2% waste | 21.1% waste |
| Tail efficiency (SQL) | 35.3% waste | 27.0% waste |

> GLM4.7 giữ được search momentum lâu hơn, ít stagnate đột ngột — nhưng cũng có thể bị kẹt lâu trước khi tìm ra solution tốt (glm47_low CK67).

---

## 6. Paradigm Breakthrough: triggered nhưng gần như tất cả FAIL

Paradigm breakthrough được **bật trong tất cả** 16 runs, nhưng kết quả rất kém so với reproduce runs (Claude):

| Task/Mode | #Paradigm tried | #Marginally improved | Became global best |
|---|---|---|---|
| CloudCast DS (all modes) | 6–10 | 0–3 | ~0 |
| CloudCast GLM47 (all modes) | 10 | 0–3 | ~0 |
| LLM SQL DS | 6–10 | 0–3 | ~0 |
| LLM SQL GLM47 | 10 | 0–4 | ~0 |

**Contrast với Claude reproduce runs:**
- CloudCast: 65–98% tổng gain đến từ paradigm breakthrough
- DS/GLM47: 0% tổng gain từ paradigm breakthrough — toàn bộ là regular solution evolution

**Lý do có thể:**
1. DS/GLM47 generate được paradigm ideas (LP, Steiner Tree, Min-Cost Flow, Simulated Annealing...) nhưng implementation thực tế của ideas phức tạp này có lỗi hoặc không hiệu quả.
2. Không có KE context → paradigm ideas không được grounded bằng paper knowledge → giải pháp sinh ra không đủ chất lượng.
3. Baseline solution đã đủ tốt từ regular evolution → PB không cần thiết và không beat được.

---

## 7. Validation: hệ thống không robust

### Variance trong baseline score (cùng model, khác reasoning mode):

| Task | Model | Min Baseline | Max Baseline | Spread |
|---|---|---|---|---|
| CloudCast | DeepSeek | 0.000965 | 0.001353 | **+40%** |
| CloudCast | GLM4.7 | 0.000973 | 0.001005 | +3.3% |
| LLM SQL | DeepSeek | 0.636 | 0.709 | **+11.5%** |
| LLM SQL | GLM4.7 | 0.658 | 0.690 | +4.8% |

- DeepSeek baseline CloudCast dao động **40%** chỉ do thay đổi reasoning mode → hệ thống khởi đầu rất khác nhau mỗi lần.
- GLM4.7 baseline ổn định hơn (~3–5% spread).

### Cùng reasoning mode → cùng cách nghĩ không?

So sánh cùng level, khác model:

| Level | DS CloudCast | GLM47 CloudCast | DS LLM SQL | GLM47 LLM SQL |
|---|---|---|---|---|
| high | 0.001575 | 0.001577 | 0.714 | 0.713 |
| medium | 0.001592 | 0.001577 | 0.676 | 0.720 |
| low | 0.001614 | 0.001511 | 0.722 | 0.718 |
| off | 0.001615 | 0.001475 | 0.694 | 0.730 |

- Ở `high`: DS và GLM47 **gần như bằng nhau** cả 2 task (diff < 0.3%) → cùng reasoning level → cùng "quality ceiling"?
- Ở `off` (no reasoning): DS tốt hơn GLM47 rõ rệt trên CloudCast (+9.5%), GLM47 tốt hơn DS trên LLM SQL (+5.3%) → model identity rõ hơn khi không có reasoning constraint.
- Kết luận: **high reasoning level đồng nhất hóa output** giữa các model, off/low cho thấy sự khác biệt bản chất giữa DS và GLM47.

---

## 8. Stagnation patterns

### Early stagnation: glm47_low CloudCast là worst case

- Không có improvement nào > 5% cho đến CK66 (67% budget đã dùng).
- Sau đó bùng nổ +46.6% ở CK67 → nhưng về final score vẫn thấp nhất (0.001511).
- Khi "burst" đến muộn quá, hệ thống không còn đủ budget để tiếp tục sau đó.

### Mối quan hệ: reasoning cao → early stagnation rõ hơn (CloudCast DeepSeek)

| Mode | First big jump | Comment |
|---|---|---|
| ds_off | CK 2 | Ngay lập tức tìm được approach tốt |
| ds_low | CK 2 | Tương tự |
| ds_medium | CK 4 | Nhanh |
| ds_high | CK 13 | **Chậm nhất** — nhiều reasoning → cân nhắc quá nhiều trước khi commit |

Hiện tượng: high reasoning DeepSeek có thể bị **"overthinking"** — generate các solution thận trọng hơn nhưng incremental hơn, mất nhiều iteration để tìm được approach đột phá.

---

## 9. Tổng kết take-aways

| # | Take-away | Evidence |
|---|---|---|
| **R1** | More reasoning ≠ better: DS CloudCast nghịch chiều (off>low>med>high), GLM4.7 LLM SQL cũng nghịch chiều | Section 2 |
| **R2** | Cross-pattern robustness: DS robust trên CloudCast (2.5%), sensitive trên LLM SQL (6.8%). GLM4.7 ngược lại | Section 3 |
| **R3** | Model-task fit: DS phù hợp CloudCast (+2.4%), GLM4.7 phù hợp LLM SQL (+1.1%) | Section 4 |
| **R4** | DS = burst pattern (ít events, impact lớn, sớm), GLM4.7 = grind pattern (nhiều events, nhỏ, đều) | Section 5 |
| **R5** | Paradigm breakthrough gần như vô hiệu với DS/GLM47 (0% gain từ PB) — contrast với Claude (65–98%) | Section 6 |
| **R6** | Baseline không ổn định: DS CloudCast baseline spread 40% chỉ do thay reasoning mode → non-robust | Section 7 |
| **R7** | High reasoning đồng nhất hóa output giữa DS và GLM47; off/low mới bộc lộ bản sắc riêng mỗi model | Section 7 |
| **R8** | High reasoning DS → early stagnation dài hơn (first big jump CK13 vs CK2 cho off/low) | Section 8 |
