# flash_attn
Về hình dáng, điểm số có mức độ dao động cao, không có đường điểm kiểu tịnh tiến mà ở các new best score đều là điểm tăng đột ngột.
Task này dễ bị failed (điểm = 0) do sai sót về coding.
### flash_attn_0614_222725_ds_medium
Ite 0-34 có dấu hiệu chạy failed, combined score = 0
Đây là lỗi **biên dịch Triton thật**, nội dung lặp đi lặp lại:
```Python
FAILED: ... unsupported AST node type: Break
        if CAUSAL and start_n > q_block_start + BLOCK_M - 1:
            break          ←  Triton KHÔNG hỗ trợ `break` trong @triton.jit
```
cộng vài lỗi phụ như `name 'math' is not defined` (quên import).
Nguyên nhân gốc: chính dòng docstring trong initial program _"skip fully-future key blocks under causal masking"_ đã dụ LLM hiện thực bằng `break` để nhảy khỏi vòng lặp — nhưng Triton phiên bản này cấm `break`/`continue` trong kernel. Nên hàng loạt child đầu compile fail → score 0 → best kẹt ở **1.996x** suốt nhiều iteration.
Evaluator config sai error feedback nên các prompt đều không chứa feedback error, do đó LLM chỉ có thể đoán và nâng cấp dựa vào feedback score.

Initial program:
```python
for n in range(0, N):          # duyệt TỪNG key, mỗi vòng đúng 1 key
    score = tl.sum(q * k_row)  # nhân tay query với 1 key
    ... cập nhật softmax ...
```
- Như cộng một dãy số bằng cách **bấm máy tính từng số một**.
- **Không** dùng _tensor cores_ — phần cứng đặc biệt của GPU chuyên nhân nguyên khối ma trận cùng lúc.
- Đúng kết quả, nhưng **chậm** vì bỏ phí sức mạnh GPU. Đó là lý do chỉ đạt 1.996x.

Ite 35: 1.9959 → 19.4295 (~10x) parent là 91246a01 = chính seed (program đầu tiên)
```python
for start_n in range(0, max_key_idx, BLOCK_N):   # duyệt theo KHỐI 64 key
    s = tl.dot(q, k) * scale                      # nhân CẢ KHỐI query × khối key trong 1 phát
    ...
    acc = acc * alpha + tl.dot(p.to(fp16), v)     # lại nhân nguyên khối
```
- `tl.dot` chạy trên **tensor cores** — phần cứng nhân nguyên mảng 64×64 **trong một thao tác**.
- Thuật toán softmax/causal **vẫn y như cũ** (kế thừa từ seed), chỉ thay phần "nhân từng cái" thành "nhân từng khối".
- Thêm: bỏ qua hẳn các khối key hoàn toàn ở tương lai (`max_key_idx = min(...)`) → đỡ tính thừa với causal.
=> Phần lớn là do docstring guide trong parent code (batch keys into blocks and use tl.dot (tensor cores)) & kiến thức Flash-Attention sẵn có trong model LLM để thêm idea phụ. Paradigm có kích hoạt và code có implement idea nhưng không phải nhân tố chính (num_stages=2 => giúp việc tận dụng GPU load & calculate giữa mỗi vòng lặp qua block key mượt hơn, tăng khoảng 15-30% hiệu suất).

Ite 54: 21.11 → 34.03, program be949f66, parent eaa29da6 (21.11x)
Parent eaa29da6 (21.11x) — đã là một flash-attention block-tiled hoàn chỉnh (hậu duệ của ite35). Child giữ gần như nguyên và chỉ chỉnh vài chỗ. (+21 dòng).
Các context program vẫn không có tác dụng như thường. Thậm chí dù paradigm có bật nhưng model gần như phớt lờ idea đó. Chỉ thêm vài chữ từ idea của paradigm vào docstring cho giống, còn code vẫn giữ core như cũ.
Thay đổi:
```python
# 1) Ép fp16 cho Q,K trước tl.dot → chạy đúng đường tensor core tốc độ cao
- s = tl.dot(q, tl.trans(k)) * scale
+ s = tl.dot(q.to(tl.float16), tl.trans(k.to(tl.float16))) * scale

# 2) num_stages 3 → 2 ("cân bằng tốt hơn với tensor core")
- num_stages=3
+ num_stages=2
```
### flash_attn_0614_180701_ds_medium
Từ ite 59 - 100 có dấu hiệu chạy failed, combined score = 0
Trên tổng 100 ite có 63 child bị score = 0 (fail), nguyên nhân chính: `CUDA error: an illegal instruction was encountered` (87 lần), thêm `out of resource: shared memory` và `Conflicting meta-parameters BLOCK_N/BLOCK_M`.
Khi kernel ở eval #60 thực thi một lệnh GPU bất hợp lệ (truy cập bộ nhớ ngoài biên do BLOCK config/con trỏ sai), nó **làm hỏng CUDA context của cả tiến trình**. Mà lỗi `illegal instruction`/`illegal memory access` trong CUDA là **không thể phục hồi và "dính"**: một khi đã xảy ra, **mọi lời gọi CUDA tiếp theo trong cùng tiến trình đều trả về đúng lỗi đó** cho tới khi restart tiến trình. Nên 43 kernel sau — kể cả kernel hoàn toàn đúng — đều chết ở score 0.
Các child fail hoặc không vượt được best (lúc này đã rất cao) → bị loại khỏi archive → code bị prune.

Ite 1:program 453b970b, score 15.81, parent 16504717 (seed)
Đây là ite đầu tiên, chưa có breakthrough idea (chưa stagnation), chưa có previous attempts nhưng thực hiện nâng cấp y hệt ite 35 ở log trước. Lí do là vì nó nâng cấp y nguyên những gì guide từ docstring trong code parent.

Ite 6: 15.81 → 40.21 (~2.5x), program a44cdcaa, parent 16504717 (seed)
Kiểm tra cho thấy cùng seed, khác prompt LLM lại ra kết quả child program y hệt nhau nhưng kết quả benchmark lại rất khác biệt???

Ite 32: 40.21 → 55.95 (~1.39x), parent là ite6
Có paradigm nhưng không thực hiện sửa đề xuất của paradigm mà chỉ comment cho giống thật, diff changes chỉ là thay đổi nhỏ:
```python
# 1) Ép fp16 trước tl.dot (Y HỆT thủ thuật ite54)
- scores = tl.dot(q, tl.trans(k)) * scale
+ scores = tl.dot(q.to(fp16), tl.trans(k.to(fp16))).to(fp32) * scale

# 2) num_stages 2 → 3   ← CHÚ Ý: ngược hẳn ite54 (3→2)!
- num_stages=2
+ num_stages=3

# 3) "Fused epilogue": chỉ là đổi chia thành nhân nghịch đảo (gần như vô nghĩa về tốc độ)
- acc = acc / l_i[:, None]
+ l_i_recip = 1.0 / l_i;  o = acc * l_i_recip[:, None]
```
Khả năng cao là nhiễu, cần xem xét lại giống Ite 6
### flash_attn_0615_002324_glm47_medium
Ite 3 (2.03 → 15.32): tương tự các bước đầu của log khác, tận dụng gợi ý từ docstring của parent (parent là seed)

Ite 19 (16.47 → 25.72): sử dụng idea từ paradigm (_"Use FP16 arithmetic in tl.dot to save register pressure — keep Q and K tiles in float16"_) (tương tự idea các log trước), thực hiện một số thay đổi nhỏ: giữ fp16 cho tensor core, config num_warps/num_stages.

Ite 24 (25.72 → 32.38): breakthrough idea chỉ là 	"Software pipelining with num_stages > 2 — increase to 3 or 4". Code diff chỉ là `num_warps 8→4, num_stages 4→3` (+ docstring)

![[Capture (1).png]]
# quant_dot_int4
- GLM: 
- Deepseek
![[Pasted image 20260615185632.png]]
![[Pasted image 20260615185658.png]]
![[Pasted image 20260615185902.png]]
Do bài toán này yêu cầu khả năng coding cao nên bị sai rất nhiều ở đoạn đầu, cũng như config feedback error chưa đúng. GLM không thể thoát khỏi và điểm dao động khoảng 0,13 tới 0,19. Còn Deepseek sau khoảng 60 ite thì bắt đầu tìm được syntax code đúng 
![[Capture.png]]