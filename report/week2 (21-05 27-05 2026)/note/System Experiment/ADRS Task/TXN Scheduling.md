Tối thiểu makespan giao dịch DB

Bài toán: Cho một tập 100 database transactions, mỗi transaction là một chuỗi thao tác đọc/ghi (`r-key`, `w-key`) trên các shared keys. Tìm **thứ tự thực thi** các transactions sao cho **makespan (tổng thời gian) nhỏ nhất**.

Cơ chế conflict:
- `write-write` hoặc `read-write` trên cùng một key → transaction sau phải **chờ** transaction trước giải phóng lock
- Nếu đặt 2 transactions xung đột gần nhau sẽ gây delay, làm tăng makespan

Score: `1_000_000 / (1 + makespan)` → makespan nhỏ = score cao.