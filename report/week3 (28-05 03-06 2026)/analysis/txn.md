## Bài toán: Transaction Scheduling

### Ví dụ đơn giản

Có 3 transaction (giao dịch database):

```
Txn A: write(X), read(Y)
Txn B: read(X), write(Z)
Txn C: write(Y), read(Z)
```

**Conflict (xung đột):** A write(X) → B read(X) → B phải chờ A xong mới đọc được X.

Thứ tự khác nhau → thời gian chờ khác nhau:

```
Thứ tự A→B→C: B chờ A, C chờ A và B → makespan = 30 giây
Thứ tự B→A→C: A chờ ít hơn → makespan = 22 giây  ← tốt hơn
```

**Mục tiêu:** Tìm thứ tự N transaction sao cho **makespan** (tổng thời gian xử lý) nhỏ nhất.

---

## txn_output — Cải tiến từng bước

| Iter | Score | Makespan | Ý tưởng                                 |
| ---- | ----- | -------- | --------------------------------------- |
| 1    | 3663  | 272      | Greedy + reinsertion hill climbing      |
| 3    | 4081  | 244      | Thêm Simulated Annealing                |
| 7    | 4184  | 238      | SA thêm swap moves                      |
| 13   | 4219  | 236      | Thay greedy bằng Beam Search            |
| 40   | 4310  | 231      | Conflict graph + LNS                    |
| 59   | 4405  | 226      | ALNS với nhiều destroy/repair operators |
| 67   | 4504  | 221      | Tinh chỉnh ALNS                         |
| 82   | 4524  | **220**  | Best                                    |

**Giải thích từng bước:**

**iter 1 — Greedy + Hill Climbing:**

```
Xây schedule: mỗi bước chọn transaction nào thêm vào làm makespan tăng ít nhất
Sau đó: thử rút từng transaction ra, chèn vào vị trí khác xem có tốt hơn không
→ Đơn giản, hiệu quả ban đầu
```

**iter 3 — Simulated Annealing (SA):**

```
Vấn đề: Hill climbing bị kẹt local optimum (không thoát ra được)
Giải pháp SA: đôi khi chấp nhận nước đi XẤU HƠN để thoát ra
              Giống "leo núi trong sương mù" — thỉnh thoảng bước lùi để tìm đường lên cao hơn
→ Makespan 272 → 244
```

**iter 7 — Thêm Swap moves:**

```
Trước: chỉ dùng "reinsert" (rút ra chèn vào chỗ khác)
Thêm: "swap" (hoán đổi vị trí 2 transaction bất kỳ)
→ Tìm kiếm đa dạng hơn trong không gian nghiệm
```

**iter 13 — Beam Search:**

```
Greedy cũ: tại mỗi bước chỉ giữ 1 lựa chọn tốt nhất → dễ đi sai đường
Beam Search: giữ TOP-K lựa chọn tốt nhất → khám phá nhiều hướng hơn

Ví dụ beam_width=3:
Bước 1: [A→?] [B→?] [C→?]  — 3 ứng viên
Bước 2: expand mỗi ứng viên → chọn 3 tốt nhất trong 9
→ Không bỏ lỡ nhiều nghiệm tốt
```

**iter 40 — Conflict Graph + LNS:**

Đây là **breakthrough lớn nhất**. Nhận ra cấu trúc của bài toán:

```
Xây đồ thị xung đột:
  A ←→ B (vì A write(X), B read(X))
  A ←→ C (vì A read(Y), C write(Y))
  B ←─ C (vì B write(Z), C read(Z))

Tìm các thành phần độc lập (independent components):
  Nếu {D, E, F} không conflict với {A, B, C}
  → Tối ưu {D,E,F} riêng, tối ưu {A,B,C} riêng
  → Nhỏ hơn nhiều, nhanh hơn nhiều!
```

Kết hợp với **LNS (Large Neighborhood Search):** thay vì chỉ swap 2 transaction, lấy ra một nhóm 5-7 transaction, thử tất cả hoán vị của nhóm đó.

**iter 59-67 — ALNS (Adaptive LNS):**

```
LNS cũ: lấy ngẫu nhiên 1 nhóm và thử hết hoán vị
ALNS: có nhiều cách "phá" (destroy) và "sửa" (repair) khác nhau:
  - Destroy block: lấy ra một đoạn liên tiếp
  - Destroy random: lấy ngẫu nhiên rải rác
  - Destroy conflict: lấy các transaction có nhiều conflict nhất
  - Repair greedy: chèn lại từng cái vào vị trí tốt nhất
  - Repair conflict_order: chèn theo thứ tự conflict nhiều trước

Và học xem cách nào đang hoạt động tốt → tăng weight → dùng nhiều hơn
```

---

## txn_0601_2325 — Cải tiến từng bước

| Iter  | Score | Makespan | Ý tưởng                              |
| ----- | ----- | -------- | ------------------------------------ |
| 1     | 3333  | 299      | Greedy + adjacent swap               |
| 2     | 3703  | 269      | Swap tất cả cặp (không chỉ kề nhau)  |
| 8     | 3831  | 260      | Beam search + SA nhiều neighborhoods |
| 11-12 | 3921  | 254      | Tăng beam_width, thêm block swap     |
| 88    | 3952  | **252**  | Beam search + Guided Local Search    |
|       |       |          |                                      |

**iter 1-2:** Xuất phát yếu hơn (makespan=299 vs 272). Local search ban đầu chỉ swap kề nhau → iter 2 mở rộng sang tất cả cặp.

**iter 8 — Beam Search + SA:**

```
Tương tự Run A iter 7-13, nhưng Run B phát hiện ra sau ít iterations hơn
Dùng 3 loại moves: pair swap, block swap, reinsert
```

**iter 88 — Guided Local Search (GLS):**

```
Vấn đề: SA thoát local optimum bằng cách ngẫu nhiên chấp nhận nước xấu
GLS: thông minh hơn — phạt các "feature" (cặp transaction kề nhau) 
     hay xuất hiện trong local optimum
     
Ví dụ: nếu cứ bị kẹt ở schedule [A,B,C,...], GLS tăng penalty cho cặp (A,B)
→ lần sau sẽ tránh đặt A trước B → thoát ra
```

---

## So sánh tổng thể

```
txn_output:    272 → 220  (giảm 52, -19%)  ← THẮNG
txn_0601_2325: 299 → 252  (giảm 47, -16%)
```

**Tại sao txn_output thắng?**

Run A phát hiện ra **conflict graph decomposition** ở iter 40 — một insight cốt lõi: bài toán có thể **chia nhỏ thành các bài toán con độc lập**. Thay vì tối ưu 20 transaction cùng lúc, tối ưu 2 nhóm 10 transaction riêng biệt → không gian tìm kiếm nhỏ hơn rất nhiều → tìm được nghiệm tốt hơn.

Run B không tìm ra insight này. Run B vẫn tìm kiếm trên toàn bộ không gian và cải thiện local search (GLS), nhưng không khai thác cấu trúc bài toán → bị giới hạn.

