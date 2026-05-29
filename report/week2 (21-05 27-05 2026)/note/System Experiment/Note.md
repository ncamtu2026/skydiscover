# SkyDiscover
## Introduction
A Flexible Framework for AI-Driven Scientific and Algorithmic Discovery

SkyDiscover hỗ trợ các framework nổi tiếng (OpenEvolve, GEPA, ShinkaEvolve) theo 2 cách:
- Wrapper: framework được gọi qua chính source code gốc của chúng. Ở đây SkyDiscover chỉ bọc một lớp adapter để gọi vào framework gốc rồi đọc kết quả ra.
- Modular (native): OpenEvolve và GEPA còn được cài lại từ đầu thành `openevolve_native` và `gepa_native`, dùng đúng kiến trúc 4+1 thành phần của SkyDiscover.

![[Pasted image 20260523130131.png]]

Mỗi framework (OpenEvolve, GEPA, ShinkaEvolve) đều có 5 thành phần trên, và SkyDiscover định nghĩa loop như sau: sample → prompt → LLM → evaluate → add.

Ở hướng Modular (native) SkyDiscover cố định 3 trong 5 thành phần (Context Builder, Solution Generator gọi LLM, Evaluator) thành hạ tầng dùng chung.
→ Chênh lệch hiệu năng phản ánh đúng _bản chất thuật toán_, chứ không phải do framework này gọi LLM khéo hơn framework kia.

Về mức độ tuỳ biến, có thể sửa đổi những thành phần sau:
- Solution Database: thuật toán chỉ cần định nghĩa lại `add()` (lưu thế nào) và `sample()` (chọn parent nào để tiến hóa tiếp). Vòng lặp mặc định lo phần còn lại. Ví dụ: Top-K (56 dòng), Best-of-N (85 dòng).
- Solution Database + Controller: thuật toán cần can thiệp vào hành vi _xuyên suốt nhiều vòng lặp_ — phản ứng với trì trệ, xoay vòng island, lọc kết quả trước khi nạp vào pool. Ví dụ: AdaEvolve, GEPA_native, EvoX.

Các bài test system sẵn có:
- Prism
- TXN Scheduling
- LLM SQL
- EPLB
- Cloudcast
## Experiment

Bài test LLM SQL, với config xem tại [[config_deepseek.yaml]]
Command to run experiment:
```bash
uv run skydiscover-run \
  benchmarks/ADRS/llm_sql/initial_program.py \
  benchmarks/ADRS/llm_sql/evaluator/evaluator.py \
  -c benchmarks/ADRS/llm_sql/config_deepseek.yaml \
  -s adaevolve \
  -i 2
```
Các thuật toán search (`-s`) gồm:
- evox: Evolutionary optimization — tiến hóa kiểu genetic, giữ lại những solution tốt
- best_of_n: Sinh N solution độc lập, chọn cái tốt nhất
- beam_search: Tìm kiếm theo chùm (beam), cân bằng độ rộng và sâu
- adaevolve: Evox có adaptive — điều chỉnh chiến lược dựa trên lịch sử
- openevolve: Port của thuật toán OpenEvolve (AlphaCode style)

Đối với task LLM SQL, tốc độ eval chậm (~150s) và đã tối ưu code eval, eval sau tối ưu chỉ cần ~50s.
Đối với task Cloudcast tốc độ eval rất nhanh (~5s)

