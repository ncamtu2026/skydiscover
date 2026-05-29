Model Placement trên GPU cluster

Bài toán: Cho một tập các LLM models (mỗi model có `model_size`, `req_rate`, `slo`) và `gpu_num` GPU (mỗi GPU 80 GB VRAM), hãy **phân bổ models vào GPUs** sao cho **KV-cache pressure (KVPR) tối thiểu**.

`KVPR = Σ(req_rate / slo) / (80 GB − Σmodel_size)

Mục tiêu: Minimize `max(KVPR)` trên tất cả GPUs

Score: `1.0 / avg_KVPR` + `success_rate` → cao hơn = tốt hơn.