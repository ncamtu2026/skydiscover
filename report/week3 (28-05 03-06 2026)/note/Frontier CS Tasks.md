## Problem
Các tasks trong Frontier CS chia thành 2 loại:
- Algorithmic
	- Runner: skydiscover-run
	- Evaluator: evaluate(program_path)
- Research
	- Runner: frontier eval research
	- Evaluator: evaluate.sh trong Docker

Trong `benchmarks/frontier-cs-eval/README.md` có đề cập rõ ràng chỉ support các bài toán algorithmic track với evaluator chia thành 3 loại:
- Harbor (instruction.md + tests/ + Dockerfile)
- Containerized (Dockerfile + evaluate.sh)
- Plain Python (evaluate() function)

Hiện tại luồng hoạt động của 2 framework rất khác biệt như sau:
- SkyDiscover:
	- Load config.yaml, initial_program.py
	- create_evaluator: kiểm tra thuộc loại nào trong 3 loại đề cập ở trên (harbor, plain,…)
	- Runner.run() → AdaEvolveController.run_discovery() → loop iterations
- Frontier CS:
	- Đọc config.yaml của variant (variant ở đây là một trong các dòng dataset của một bài toán nào đó)
	- Build Docker Image
	- Cài simulator tương ứng bài toán đang chọn trong container
	- Extract dataset trong container
	- Inject solution.py từ ngoài vào container
	- Docker container chạy evaluate.sh → run_evalutor.sh → evaluator.py --solution solution.py → stage 1 (nếu có) → stage 2 → score
	- Frontier CLI bên ngoài đọc score từ file stdout JSON
	- Kết thúc - ==không có evolve loop==

## Solution
Frontier-CS Python API (SingleEvaluator) cho phép gọi evaluate từ code Python mà không cần tự manage Docker.
```python
from frontier_cs import SingleEvaluator

evaluator = SingleEvaluator()
result = evaluator.evaluate(
    "research",
    problem_id="cant_be_late/mixed_availability_loose_deadline_small_overhead",
    code=solution_code,
    backend="docker"   # framework tự build image, inject, lấy score
)
score = result.score
```

Có thể viết một skydiscover evaluator wrapper gọi SingleEvaluator.evaluate() — Frontier-CS tự lo Docker, mình chỉ cần truyền code và lấy score về:

note thêm ở đây
so sánh hiệu năng vs cs frontier eval gốc

Bài toán CBL và MCBL có nhiều dòng dataset, được gọi là variant, hiện tại thử nghiệm trên 2 variant dưới với mục tiêu nhanh, dễ tối ưu (không có thông tin paper barbarian dùng variant nào)
- CBL: mixed_availability_loose_deadline_small_overhead
- MCBL: high_availability_loose_deadline_small_overhead

Với từng variant sẽ có evaluator_sd.py riêng, lí do là vì PROBLEM_ID khác nhau giữa các variant. Nếu làm file chung thì sẽ phải set env var, toàn bộ process đều thấy, không phân biệt được khi chạy nhiều bài cùng lúc.

Sau đó thực hiện link (`ln`) datasets/cant_be_late/real → cant-be-late-simulator/real/
Lí do là khi khởi tạo Docker container sẽ mount folder dataset ở bên ngoài vào, và `set_up_env.sh` bên trong Docker kỳ vọng đường dẫn sẽ có dạng như dưới.
```
datasets_dir/
└── cant_be_late/
    └── real/
```
Trong khi thực tế trông như sau:
`cant-be-late-simulator/real/ddl=.../...`
Đây là cách tốt nhất vì nếu sửa trực tiếp cấu trúc thư mục sẽ khiến code Frontier CS ở đoạn khác hardcode không thực thi được.