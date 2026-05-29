# SkyDiscover
## Introduction
A Flexible Framework for AI-Driven Scientific and Algorithmic Discovery

SkyDiscover hỗ trợ các framework nổi tiếng (OpenEvolve, GEPA, ShinkaEvolve) theo 2 cách:
- Wrapper: framework được gọi qua chính source code gốc của chúng (cài bằng `uv sync --extra external`, dùng flag `--search openevolve`, `--search gepa`, `--search shinkaevolve`). Ở đây SkyDiscover chỉ bọc một lớp adapter để gọi vào framework gốc rồi đọc kết quả ra. Bản thân framework gốc vẫn chạy với 5 thành phần riêng của nó bên trong — SkyDiscover không mổ xẻ nó.
- Modular (native): OpenEvolve và GEPA còn được cài lại từ đầu thành `openevolve_native` và `gepa_native`, dùng đúng kiến trúc 4+1 thành phần của SkyDiscover.

![[Pasted image 20260523130131.png]]

Mỗi framework (OpenEvolve, GEPA, ShinkaEvolve) đều có 5 thành phần trên, và SkyDiscover định nghĩa loop như sau: sample → prompt → LLM → evaluate → add.

Ở hướng Modular (native) SkyDiscover cố định 3 trong 5 thành phần (Context Builder, Solution Generator gọi LLM, Evaluator) thành hạ tầng dùng chung.
→ Chênh lệch hiệu năng phản ánh đúng _bản chất thuật toán_, chứ không phải do framework này gọi LLM khéo hơn framework kia.

Về mức độ tuỳ biến, có thể sửa đổi những thành phần sau:
- Solution Database: thuật toán chỉ cần định nghĩa lại `add()` (lưu thế nào) và `sample()` (chọn parent nào để tiến hóa tiếp). Vòng lặp mặc định lo phần còn lại. Ví dụ: Top-K (56 dòng), Best-of-N (85 dòng).
- Database + Controller: thuật toán cần can thiệp vào hành vi _xuyên suốt nhiều vòng lặp_ — phản ứng với trì trệ, xoay vòng island, lọc kết quả trước khi nạp vào pool. Ví dụ: AdaEvolve, GEPA_native, EvoX.

Các bài test system sẵn có:
- Prism — Model Placement trên GPU cluster
	Bài toán: Cho một tập các LLM models (mỗi model có `model_size`, `req_rate`, `slo`) và `gpu_num` GPU (mỗi GPU 80 GB VRAM), hãy **phân bổ models vào GPUs** sao cho **KV-cache pressure (KVPR) tối thiểu**.
	`KVPR = Σ(req_rate / slo) / (80 GB − Σmodel_size)
	Mục tiêu: Minimize `max(KVPR)` trên tất cả GPUs
	Score: `1.0 / avg_KVPR` + `success_rate` → cao hơn = tốt hơn.

- TXN Scheduling — Tối thiểu makespan giao dịch DB
	Bài toán: Cho một tập 100 database transactions, mỗi transaction là một chuỗi thao tác đọc/ghi (`r-key`, `w-key`) trên các shared keys. Tìm **thứ tự thực thi** các transactions sao cho **makespan (tổng thời gian) nhỏ nhất**.
	Cơ chế conflict:
	- `write-write` hoặc `read-write` trên cùng một key → transaction sau phải **chờ** transaction trước giải phóng lock
	- Nếu đặt 2 transactions xung đột gần nhau sẽ gây delay, làm tăng makespan
	Score: `1_000_000 / (1 + makespan)` → makespan nhỏ = score cao.

- LLM SQL — Column & Row Reordering cho Prefix Caching
	Bài toán: Cho một DataFrame (bảng dữ liệu), khi serialize từng hàng thành LLM prompt, các hàng liên tiếp có thể dùng chung **prefix cache** nếu các giá trị cột đầu giống nhau. Hãy **sắp xếp lại thứ tự cột và hàng** để tối đa hóa prefix cache hit.
	`hit(row) = Σ len(value)² với mọi cột khớp liên tiếp từ đầu với hàng trước
	Score: `combined = 0.95 × avg_hit_rate + 0.05 × (12 − min(12, runtime)) / 12`

- EPLB — Expert Parallelism Load Balancing (MoE)
	Bài toán: Trong mô hình Mixture-of-Experts (MoE), mỗi token chỉ kích hoạt vài "experts". Khi một số experts quá phổ biến, GPU chứa chúng bị overload. Hãy **quyết định số lượng bản sao (replicas) cho mỗi expert** và **gán chúng lên GPUs** sao cho load cân bằng nhất.
	Hai mục tiêu song song:
	1. **Balancedness score** (GPU-level & expert-level): `avg_load / max_load` → càng gần 1 càng tốt
	2. **Speed score**: thuật toán `rebalance_experts()` phải chạy **nhanh** vì được gọi định kỳ trong serving
	Score: `combined = 0.6×balancedness_gpu + 0.2×balancedness_expert + 0.2×speed_score

- Cloudcast — Multi-Cloud Broadcast tối thiểu chi phí
	Bài toán: Truyền một dataset từ **một source region** đến **nhiều destination regions** trên multi-cloud (AWS/GCP/Azure) với **chi phí egress thấp nhất**. Mạng có bandwidth và cost/GB khác nhau theo từng cặp region.

## Experiment

Bài test LLM SQL, với config xem tại [[config_deepseek.yaml]]
Command to run experiment:
```bash
uv run skydiscover-run \
  benchmarks/ADRS/llm_sql/initial_program.py \
  benchmarks/ADRS/llm_sql/evaluator/evaluator.py \
  -c benchmarks/ADRS/llm_sql/config_deepseek.yaml \
  -s evox \
  -i 10
```
Ngoài evox còn có:
- evox: Evolutionary optimization — tiến hóa kiểu genetic, giữ lại những solution tốt
- best_of_n: Sinh N solution độc lập, chọn cái tốt nhất
- beam_search: Tìm kiếm theo chùm (beam), cân bằng độ rộng và sâu
- adaevolve: Evox có adaptive — điều chỉnh chiến lược dựa trên lịch sử
- openevolve: Port của thuật toán OpenEvolve (AlphaCode style)