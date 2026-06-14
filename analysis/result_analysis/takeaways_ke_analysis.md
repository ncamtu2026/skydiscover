# Take-aways: Phân tích KE Modes — CloudCast & LLM SQL

> **Dữ liệu:** 8 runs (4 CloudCast + 4 LLM SQL), 2 task types  
> **Modes so sánh:** `ke_both`, `ke_paradigm`, `ke_parent`, `no_ke`  
> **Metric CloudCast:** `combined_score = 1/total_cost` (cao hơn = tốt hơn)  
> **Metric LLM SQL:** `combined_score` = prefix cache hit rate (cao hơn = tốt hơn)

---

## 1. Bảng hiệu suất tổng hợp

| Task | Run | Baseline | Final Score | Total Gain | #Checkpoints | Rank |
|---|---|---|---|---|---|---|
| CloudCast | **ke_both** | 0.001125 | **0.001602** | +42.4% | 87 | 🥇 1 |
| CloudCast | ke_paradigm | 0.000997 | 0.001548 | +55.3% | 98 | 2 |
| CloudCast | ke_parent | 0.000965 | 0.001511 | +56.6% | 126 | 3 (tie) |
| CloudCast | no_ke | 0.001005 | 0.001511 | +50.4% | 93 | 3 (tie) |
| LLM SQL | **ke_paradigm** | 0.6556 | **0.7154** | +9.1% | 54 | 🥇 1 |
| LLM SQL | no_ke | 0.6723 | 0.7025 | +4.5% | 127 | 2 |
| LLM SQL | ke_parent | 0.6881 | 0.6986 | +1.5% | 41 | 3 |
| LLM SQL | ke_both | 0.4690 | 0.6456 | +37.7% | 84 | 4 |

> **Quan sát nhanh:** `ke_paradigm` là mode duy nhất đứng #1 hoặc #2 ở **cả hai task**. `ke_parent` bị no_ke vượt qua trong LLM SQL dù bắt đầu từ baseline cao hơn.

---

## 2. ke_parent có gây khó phát triển không?

### Kết luận: **Có — rõ ràng ở LLM SQL, mờ ở CloudCast**

#### CloudCast: ke_parent không bị block nhưng khởi động chậm

| Run | Baseline | EarlyPlat (iters trước cải thiện đầu) | #PB | Final |
|---|---|---|---|---|
| ke_parent | 0.000965 (thấp nhất) | **10** | 4 | 0.001511 |
| no_ke | 0.001005 | 5 | 4 | 0.001511 |

- ke_parent mất **10 iterations** trước khi có improvement đầu tiên (so với 5 của no_ke).
- Tuy nhiên cả hai đều **tạo được 4 paradigm breakthroughs** và kết thúc cùng final score.
- **Kết luận CloudCast:** ke_parent *khởi động chậm hơn* nhưng không bị block — vẫn thoát ra được nhờ paradigm breakthrough.

#### LLM SQL: ke_parent bị kẹt trong local optimum

| Run | Baseline | EarlyPlat | #PB | AvgImprovement/event | Total Gain | Final |
|---|---|---|---|---|---|---|
| ke_parent | 0.6881 (cao nhất) | **6** | **0** | **+0.19%** | **+1.5%** | 0.6986 |
| no_ke | 0.6723 | 2 | 0 | +1.13% | +4.5% | **0.7025** |

- ke_parent bắt đầu **cao nhất** (0.688) nhưng chỉ tăng được +1.5% trong 41 checkpoints.
- no_ke bắt đầu thấp hơn 0.688 nhưng **overtake ke_parent** và đạt 0.703 — cao hơn 0.003 điểm.
- ke_parent tạo ra **8 improvement events** nhưng trung bình mỗi lần chỉ +0.19% — toàn bộ là incremental steps.
- **Không có một paradigm breakthrough nào** trong toàn bộ run ke_parent LLM SQL.
- no_ke mặc dù ít improvement hơn (5 events) nhưng average per event cao hơn 5.8× (+1.13% vs +0.19%).

> **Giải thích cơ chế:** Trong LLM SQL, ke_parent cung cấp context từ parent solution → LLM bị "anchor" vào paradigm hiện tại, chỉ fine-tune thay vì thay đổi cấu trúc. Kết quả là chuỗi dài các incremental improvements nhỏ, không thoát ra được local optimum. Trong CloudCast, cùng cơ chế nhưng paradigm breakthroughs vẫn xảy ra — có thể do problem space của CloudCast (graph algorithm) có signal rõ ràng hơn để trigger paradigm shift.

---

## 3. Paradigm Breakthrough — đóng góp bao nhiêu?

### Kết luận: **Dominant ở CloudCast, marginal ở LLM SQL — task-dependent**

| Task | Run | #PB events | % gain từ PB | % gain từ solution | AvgPB/event |
|---|---|---|---|---|---|
| **CloudCast** | ke_both | 3 | **65.5%** | 34.5% | +8.2% |
| **CloudCast** | ke_paradigm | 4 | **98.3%** | 1.7% | +12.2% |
| **CloudCast** | ke_parent | 4 | **78.1%** | 21.9% | +9.5% |
| **CloudCast** | no_ke | 4 | **88.1%** | 11.9% | +9.5% |
| LLM SQL | ke_both | 0 | 0% | 100% | — |
| LLM SQL | ke_paradigm | 2 | 38.1% | 61.9% | +1.7% |
| LLM SQL | ke_parent | 0 | 0% | 100% | — |
| LLM SQL | no_ke | 0 | 0% | 100% | — |

#### CloudCast: PB là động lực chính

- **65–98% tổng gain đến từ paradigm breakthrough** ở mọi CloudCast run.
- Mỗi PB event trung bình mang lại **+9.5–12.2%** cải thiện — cao hơn nhiều so với solution improvement (+2.6–10.6%).
- Ngay cả no_ke (không có KE) cũng tự generate ra 4 paradigm breakthroughs — tức là paradigm breakthrough là *cơ chế cần thiết* cho task này, không phụ thuộc vào có KE hay không. Tuy nhiên, no_ke cite paper nhưng toàn bộ là **hallucination** — LLM "tự bịa" paper name để justify ý tưởng của mình.

#### LLM SQL: PB không phải yếu tố quyết định

- Chỉ ke_paradigm có PB (2 events), đóng góp 38% gain — nhưng vẫn thấp hơn solution improvement (62%).
- Final score cao nhất (ke_paradigm = 0.715) phần lớn đến từ solution improvements, PB chỉ là fine-tuning ở cuối run.
- Điểm mấu chốt: ke_paradigm thắng không phải vì PB mạnh hơn, mà vì **baseline cao và solution improvements dày đặc ở early phase** (CK1–CK12).

> **Giải thích:** CloudCast đòi hỏi chuyển đổi thuật toán căn bản (Dijkstra → Steiner Tree → Spectral Clustering) — cần paradigm shift thực sự. LLM SQL là bài toán heuristic ordering với solution space liên tục — cải thiện từng bước hoạt động tốt hơn.

---

## 4. Xu hướng stagnation — khi nào rõ nhất?

### 4.1 Early stagnation (trước improvement đầu tiên sau baseline)

| Task | Run | Iters chờ trước cải thiện đầu |
|---|---|---|
| CloudCast | ke_both | 1 |
| CloudCast | ke_paradigm | 2 |
| CloudCast | **ke_parent** | **10** ← worst |
| CloudCast | no_ke | 5 |
| LLM SQL | ke_both | 1 |
| LLM SQL | ke_paradigm | 4 |
| LLM SQL | **ke_parent** | **6** ← worst |
| LLM SQL | no_ke | 2 |

- **ke_parent có early stagnation dài nhất ở cả hai task** (10 iters và 6 iters).
- Runs có KE context dày (ke_both, ke_paradigm) khởi động nhanh hơn.

### 4.2 Late stagnation (% checkpoints lãng phí sau improvement cuối)

| Task | Run | Last Impr. | #CKs | Tail Waste | % Waste |
|---|---|---|---|---|---|
| CloudCast | **ke_both** | CK 78 | 87 | 9 | **10.3%** ← best |
| CloudCast | **ke_parent** | CK 112 | 126 | 14 | **11.1%** ← best |
| CloudCast | ke_paradigm | CK 34 | 98 | 64 | 65.3% |
| CloudCast | no_ke | CK 31 | 93 | 62 | 66.7% |
| LLM SQL | **ke_paradigm** | CK 40 | 54 | 14 | **25.9%** ← best |
| LLM SQL | ke_parent | CK 24 | 41 | 17 | 41.5% |
| LLM SQL | **ke_both** | CK 12 | 84 | 72 | **85.7%** ← worst |
| LLM SQL | no_ke | CK 23 | 127 | 104 | **81.9%** ← worst |

**Nhận xét:**
- **ke_both CloudCast và ke_parent CloudCast** hiệu quả nhất: cải thiện đến tận cuối run, lãng phí chỉ ~10%.
- **ke_paradigm LLM SQL** là run hiệu quả nhất LLM SQL: tiếp tục improve đến CK40 (74% budget sử dụng).
- **no_ke LLM SQL** lãng phí nhất: stuck từ CK23, bỏ phí 104/127 checkpoints (82%) — hệ thống không có KE không tự thoát ra được plateau sau khi hết ideas.
- **ke_both LLM SQL** bị stagnate sớm nhất (CK12/84 = 86% waste) — kết quả tệ nhất mặc dù có nhiều KE nhất.

---

## 5. Phát hiện bất ngờ: ke_both LLM SQL — "quá nhiều thông tin" gây hại?

- **ke_both LLM SQL** có final score **thấp nhất** (0.646), bị no_ke (0.703) và ke_parent (0.699) vượt qua.
- Baseline thấp nhất (0.469 vs 0.655–0.688 của các runs khác) — từ đầu đã generate ra solution kém hơn.
- Stuck hoàn toàn sau CK12, không tạo được paradigm breakthrough nào trong 72 checkpoints còn lại.
- **Trái ngược:** ke_both CloudCast lại đạt final score cao nhất (0.001602).

| | CloudCast ke_both | LLM SQL ke_both |
|---|---|---|
| Final score rank | **#1** | **#4 (worst)** |
| Tail waste | 10.3% | 85.7% |
| #PB events | 3 | 0 |

> **Giả thuyết:** Ở LLM SQL — task có solution space "smoother" — việc combine cả parent context lẫn paradigm context tạo ra xung đột signal trong early iterations, khiến LLM không commit được vào một hướng cải thiện cụ thể. Ở CloudCast — task có "cliff" rõ giữa các paradigm — cùng sự kết hợp lại cho phép LLM nhảy sang paradigm mới sớm và hiệu quả hơn.

---

## 6. Tổng kết các take-aways

| # | Take-away | Evidence |
|---|---|---|
| **T1** | `ke_paradigm` là mode ổn định nhất — top 2 ở cả hai task | #1 LLM SQL (0.715), #2 CloudCast (0.001548) |
| **T2** | `ke_parent` gây early stagnation ở cả hai task (EarlyPlat: 10 vs 5 CCs, 6 vs 2 LLMs) | Table 4.1 |
| **T3** | `ke_parent` bị overtake bởi `no_ke` trong LLM SQL (+1.5% vs +4.5% gain, 0 PB vs cuối cùng tự thoát) | Table 2 |
| **T4** | Paradigm Breakthrough quyết định kết quả ở CloudCast (65–98% gains từ PB), marginal ở LLM SQL (0–38%) | Table 3 |
| **T5** | Late stagnation là phổ biến — tệ nhất ở `no_ke` LLM SQL (82%) và `ke_both` LLM SQL (86%) | Table 4.2 |
| **T6** | `ke_both` có performance bất ổn: best ở CloudCast nhưng worst ở LLM SQL — nhạy cảm với task type | Tables 1 & 5 |
| **T7** | Ngay cả `no_ke` cũng tự generate 4 PB ở CloudCast — PB là cơ chế cần thiết cho task này, không phụ thuộc KE | Table 3 |
| **T8** | `no_ke` cite paper trong PB nhưng **100% hallucination**; ke_parent CloudCast cũng hallucinate 3/4 paper citation (CK11, CK35, CK112). Chỉ ke_both/ke_paradigm và CK34 của ke_parent cite paper thực từ knowledge base | Detail files |
