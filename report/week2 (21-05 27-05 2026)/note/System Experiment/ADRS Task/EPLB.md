Expert Parallelism Load Balancing (MoE)

Experts được phân tán trên nhiều GPU, không phải expert nào cũng được dùng đều - có expert popular bị nhiều token route đến, expert ít được dùng. Khi đó GPU chứa expert hot bị quá tải, GPU chứa expert cold ngồi không
→ Latency của cả batch bị bottleneck bởi GPU chậm nhất → load imbalance giảm throughput nghiêm trọng

EPLB (Expert Parallelism Load Balancer) giải quyết imbalance bằng cách nhân bản và phân phối expert hot lên nhiều GPU để chia tải, load balance tốt nhất.

Bài toán: Trong mô hình Mixture-of-Experts (MoE), mỗi token chỉ kích hoạt vài "experts". Khi một số experts quá phổ biến, GPU chứa chúng bị overload. Hãy **quyết định số lượng bản sao (replicas) cho mỗi expert** và **gán chúng lên GPUs** sao cho load cân bằng nhất.

Hai mục tiêu song song:
1. **Balancedness score** (GPU-level & expert-level): `avg_load / max_load` → càng gần 1 càng tốt
2. **Speed score**: thuật toán `rebalance_experts()` phải chạy **nhanh** vì được gọi định kỳ trong serving

`combined_score = (avg_balancedness_score_expert + speed_score) / 2`

Workload trace (token routing)
Tại mỗi MoE layer, log xem mỗi token được route đến expert nào. Lưu lại thông tin đó cho mỗi time window.
```python
trace = [
    # Window 0: simulate workload tại thời điểm t=0
    {
        "timestamp": 0,
        "expert_load": tensor([
            [120, 450, 80, 30, ...],   # layer 0: load mỗi expert
            [200, 50, 380, 90, ...],   # layer 1
            # ... mỗi layer của model
        ])  # shape [num_layers, num_experts]
    },
    
    # Window 1: distribution đã shift (vì batch chuyển từ ShareGPT sang GSM8K chẳng hạn)
    {
        "timestamp": 1,
        "expert_load": tensor([
            [50, 100, 600, 20, ...],   # expert 2 giờ rất hot
            [...],
        ])
    },
    # ...
]
```

Policy Design:
- Stage 1: distribute expert groups to nodes
- Stage 2: decide replica counts per expert
- Stage 3: assign items to GPUs