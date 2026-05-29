Tối thiểu makespan giao dịch DB

Trong database, nhiều transaction chạy đồng thời. Khi hai transaction cùng truy cập một data item (và ít nhất một là write) → **conflict**. Conflict gây ra:
- Locking (transaction phải chờ nhau)
- Rollback/retry (nếu dùng optimistic concurrency)
→ giảm throughput

**Ý tưởng**: Nếu **sắp xếp thứ tự thực thi** transaction khéo léo — tách các transaction hay conflict ra xa nhau — thì giảm conflicts → tăng throughput.

```sql
Transaction A: write x, write y
Transaction B: write x          ← conflict với A trên x
Transaction C: write z          ← không conflict với ai

Thứ tự tệ:  A, B, C  → A và B conflict, phải chờ nhau
Thứ tự tốt: A, C, B  → chèn C vào giữa, giảm contention
```

Paper xem xét 2 biến thể của bài toán trên:
- Online setting (ràng buộc chặt)
    - Thứ tự transaction **cố định một khi đã quyết định** — committed transactions không rollback được
    - Thuật toán phải chạy trong **O(n)** (n = số transaction) — phải nhanh
    - **Không biết trước read/write operations** — chỉ đoán được hot keys
    - Đây là setting thực tế của database online (phải quyết định ngay khi transaction đến)
- Offline setting (ràng buộc lỏng)
    - Biết toàn bộ batch transaction trước
    - Có thời gian tính toán nhiều hơn (O(n²) chấp nhận được)
    - Relevant cho **deterministic databases** (Calvin, SLOG) — schedule cả batch transactions
    - **Chưa có kết quả published nào** cho setting này

Mục tiêu (cả 2 biến thể trên): minimize makespan (tổng thời gian thực thi tất cả transaction)

Bài toán: Cho một tập 100 database transactions, mỗi transaction là một chuỗi thao tác đọc/ghi (`r-key`, `w-key`) trên các shared keys. Tìm **thứ tự thực thi** các transactions sao cho **makespan (tổng thời gian) nhỏ nhất**.
`workloadW = '{"txn1": "r-x * * * w-z", "txn2": "r-z * * * w-x"}'`

Initial Program: random scheduler

Score: `1_000_000 / (1 + makespan)` → makespan nhỏ = score cao.