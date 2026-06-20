### Thông tin cơ bản về GPU
Một GPU có rất nhiều lõi so với CPU (vài nghìn), tuy nhiên kém thông minh hơn lõi CPU. Bình thường viết kernel cho GPU phải dùng CUDA (rất khó, sát phần cứng). Triton là một thư viện Python của OpenAI cho phép viết kernel bằng Python dễ hơn nhiều, nhưng vẫn chạy nhanh trên GPU.

Các task liên quan GPU trong Frontier CS đều yêu cầu viết kernel bằng Triton.

Nhiệm vụ chung của các tasks này đều là viết một kernel Triton chạy ra cùng kết quả nhưng nhanh hơn baseline. Baseline là những phép cơ bản như nhân ma trận (`A @ B`) sử dụng PyTorch.

Các tasks đều triển khai program theo cùng một form: viết một class tên Solution, trong đó có hàm solve() trả về đoạn code kernel.

### Phân tích các tasks liên quan tới GPU trong Frontier CS
1. `gemm_optimization` - nhân ma trận (cơ bản nhất)
	GEMM = "General Matrix-Matrix Multiplication" = nhân 2 ma trận: C = A × B. Đây là phép tính chiếm phần lớn thời gian của mọi mô hình AI. Nó có 6 biến thể chỉ khác nhau ở kích thước ma trận đem ra test — vuông, dẹt, dài... nhưng bản chất phép toán y nhau.
2. `mixed_gemm` - nhân ma trận + vài bước phụ, gộp làm một
	Trong mạng neural, sau khi nhân ma trận thường phải: cộng thêm "bias", rồi chạy một hàm gọi là GELU (một kiểu "kích hoạt", uốn cong con số). Bình thường làm 3 bước = 3 lần đụng vào bộ nhớ (chậm). Bài này: gộp cả 3 vào 1 kernel để đỡ tốn. Khó hơn bài 1 một chút vì phải làm nhiều việc trong một lần.
3. `quant_dot_int4` - Nhân ma trận với số bị "nén"
	Để mô hình AI chạy nhẹ hơn, người ta nén trọng số từ số 16-bit xuống chỉ 4-bit (gọi là lượng tử hoá int4) — nhét 8 số vào một ô. Bài này: viết kernel vừa "giải nén" 4-bit ra số thật, vừa nhân ma trận, gộp lại. Đây đúng kiểu kernel dùng khi chạy LLM tiết kiệm. Khó vì phải xử lý "bóc tách bit".
4. `gdpa_attention` - Phép "attention" của Transformer
	Attention là trái tim của mọi mô hình kiểu GPT: nó quyết định "từ nào nên chú ý tới từ nào". Bài này là một biến thể attention có thêm "cổng" (gate) điều tiết. Viết kernel attention nhanh là một trong những việc khó và giá trị nhất trong HPC AI (Flash-Attention nổi tiếng chính là việc này). Khó nhất nhóm.
5. `mamba2_scan` - Phép "quét tuần tự" (Mamba)
	Mamba là một kiến trúc AI mới, thay thế attention. Cốt lõi là phép tính kiểu dây chuyền: kết quả ô thứ t phụ thuộc ô thứ t-1 (y_t = a·y_{t-1} + b·x_t). Khó song song hoá vì bản chất tuần tự (phải biết ô trước mới tính ô sau). Bài này: tìm cách chia khúc để vẫn chạy song song trên GPU được. Khó theo kiểu riêng, không giống nhân ma trận.
6. 