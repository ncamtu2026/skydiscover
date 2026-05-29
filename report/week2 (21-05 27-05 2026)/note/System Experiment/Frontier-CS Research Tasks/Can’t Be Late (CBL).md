Vấn đề gốc: Các công việc thực hiện trên cloud có định nghĩa thời gian cần thực hiện và deadline. Các nhà cung cấp dịch vụ đám mây cung cấp các máy chủ dạng "spot" (spot instances) có giá thành rẻ hơn từ 3 đến 10 lần so với các máy chủ theo yêu cầu (on-demand instances). 

CBL được phát biểu trong NSDI ‘24

Tuy nhiên, một số vấn đề như sau:
- Các spot instances có đặc tính là khả năng sẵn sàng (availability) rất khó dự đoán và có thể bị nhà cung cấp thu hồi (preempted) đột ngột bất cứ lúc nào
- Việc chuyển luồng công việc giữa các máy chủ cũng tốn một khoảng delay
- Tùy tình trạng thực tế mà có thể không có instance spot chẳng hạn

Cách giải quyết SOTA (NSDI): Uniform Progress

Thay vì chơi trò mạo hiểm đợi đến sát nút mới nhảy sang On-demand, tác giả đề xuất: Hãy vạch ra một **đường tiến độ lý tưởng**. Ví dụ: Trong vòng 8 tiếng, mỗi tiếng trôi qua bắt buộc phải hoàn thành xong 1/8 công việc.
- Nếu dùng Spot và làm nhanh hơn tiến độ này, hệ thống sẽ tiếp tục tiết kiệm tiền.
- Nếu dùng Spot bị đuổi và tiến độ thực tế bắt đầu bị tụt lại phía sau so với mục tiêu, thuật toán sẽ **chủ động bắt dùng On-demand ngay từ sớm** để làm bù cho kịp tiến độ. Khi tiến độ đã quay lại mức an toàn, có thể cân nhắc sử dụng spot tiếp.

**Simulator**: dùng Python simulator mô phỏng:
- Một job có deadline chạy trên một node trong một cloud region.
- Tính khả dụng (availability) ngẫu nhiên của spot instance.
- Chi phí khi dùng spot vs on-demand.
- Thời gian setup (changeover delay) khi phải đổi instance type.

Bài báo CBL NSDI công khai repo `skypilot-org/spot-traces` chứa traces (file JSON), gồm `availability/`,`preemption/` . Bài báo cũng có nói “We implemented the policies on top of a real multi-cloud system, SkyPilot."

Format của trace như sau:
```javascript
{
  "metadata": {
    "gap_seconds": 300  // khoảng thời gian giữa 2 data point (ở đây là 5 phút)
  },
  "data": [0, 1, 1, 1, 0, 0, 1, ...]  
  // mỗi entry = số instance spot khả dụng tại tick đó
  // single-node: chỉ là 0 hoặc 1
  // multi-node (4 hoặc 16 instances): từ 0 đến N
}
```

Availability là trace mỗi 10p check instace một lần (đỡ tốn kém)
Preempttion là trace mà thực sự instance sống cho đến khi bị preempt (thực tế hơn)
⇒ Cả 2 đều không có thông tin cụ thể instance nào bị preempt, instance nào avail lại, hơi thiếu thực tế.

Các trace có sẵn:
- **2-week availability** (10/2022): V100/K80, AWS us-west-2
- **2-month availability** (02/2023): V100, AWS us-east-1, us-east-2, us-west-2 (9 zones)
- **2-week 16-node availability** (08/2023)
- **1-week preemption** (04/2023): V100 cho ML workload
- **2-day preemption** (04/2023): c3-highcpu-88 cho Bioinformatics
- **1-week preemption** (05/2023): r5.16xlarge cho Data Analytics
- **2-week 4-node preemption** (08/2023

**Simulator design**
**Inputs:**
- `availability_trace`: list[int] — từ file JSON
- `gap_seconds`: int — từ metadata (300s = 5 phút mỗi tick)
- `C(0)`: float — computation time (giờ), ví dụ 48
- `R(0)`: float — deadline (giờ), ví dụ 60
- `d`: float — changeover delay (giờ), ví dụ 0.2
- `k`: float — tỷ lệ giá on-demand/spot, ví dụ 3.0
- `policy`: hàm `policy(state, has_spot, env, task) → SPOT|ON_DEMAND|IDLE`

**State variables** mỗi tick:
- `current_state ∈ {IDLE, SPOT, ON_DEMAND}`
- `C(t)`: remaining computation time
- `R(t)`: remaining time-to-deadline
- `cost`: tổng chi phí tích lũy
- `in_changeover`: bool — có đang trong delay không
- `changeover_remaining`: float

**Main loop**:
```python
for tick in range(num_ticks):
    has_spot = (availability_trace[tick] >= 1)
    decision = policy(current_state, has_spot, env, task)
    
    if decision != current_state:
        # incur changeover delay
        in_changeover = True
        changeover_remaining = d
        current_state = decision
    
    # tính cost
    if current_state == SPOT:    cost += 1 * dt
    elif current_state == ON_DEMAND: cost += k * dt
    
    # tính progress (chỉ tiến triển nếu không trong changeover)
    if not in_changeover and current_state in (SPOT, ON_DEMAND):
        C(t) -= dt
    R(t) -= dt
    
    # kiểm tra preemption: nếu đang SPOT mà has_spot=False
    if current_state == SPOT and not has_spot:
        current_state = IDLE  # forced
```

**Outputs:**
- `total_cost`: tổng chi phí
- `deadline_met`: bool (`C(t) ≤ 0` tại `t ≤ R(0)`)
- `spot_time`, `ondemand_time`, `idle_time`: breakdown
- `decision_trace`: để vẽ Figure 4, 7, 9

**Validity check** (Safety Net Rule): cần đảm bảo policy luôn switch sang ON_DEMAND khi `R(t) < C(t) + 2d`, nếu không thì deadline sẽ miss.

**Cấu hình tập dataset**: chạy thử trên nhiều **configurations** khác nhau, biến thiên theo bốn trục:
- **Job fractions**: tỷ lệ giữa thời gian job và deadline (ví dụ job dài 6h với deadline 10h → fraction 0.6).
- **Changeover delays**: thời gian phải bỏ ra khi đổi instance.
- **Regions**: các region khác nhau có pattern availability khác nhau.
- **Accelerator types**: như 1xK80, 1xV100, 8xK80, 8xV100 (thấy trong Figure 8).

Với mỗi configuration, có nhiều **trace** (mỗi trace là một chuỗi sự kiện availability/preemption cụ thể). Chỉ **30% trace** được dùng làm "feedback subset", đảm bảo policy không overfit những trace đã thấy.

Kết quả sẽ được đánh giá:
- **Tất cả deadline phải được đáp ứng**. Đây là hard constraint. Nếu policy bỏ lỡ bất kỳ deadline nào, nó bị coi là invalid bất kể tiết kiệm được bao nhiêu.
- Metric chính là **average cost savings so với baseline Uniform Progress**.