### Quan điểm đánh giá
Hình dáng của đường điểm tăng đều hay dốc & ngang
Explore & exploit thể hiện như thế nào trong quá trình evolve

Phân loại mỗi bước cải tiến (iteration) một **mức độ nhận thức**:
1. Tham số - đổi hằng số/trọng số, cấu trúc y nguyên.
2. Refactor cục bộ (cùng cách tiếp cận): nâng cấp về cấu trúc dữ liệu, loop,...
3. Thay thành phần (đổi 1 subroutine bằng kỹ thuật biết trước)
4. Tái tổ hợp (gộp ý từ 2 parent / 2 island)
5. Tái định khung (đổi _cách phát biểu bài toán_ — vd greedy → ILP, per-destination → global Steiner tree)
6. Chuyển giao loại suy (mượn khái niệm từ lĩnh vực khác)
7. Insight nguyên lý (nhận ra tính chất cấu trúc cốt lõi): kho cấu trúc sâu giàu + thói quen tìm invariant + dám chống lại cái hiển nhiên

**Giả thuyết trung tâm:** con người tạo đột phá chủ yếu nhờ loại **5–6–7**; hệ thống evolve hiện tại chủ yếu kẹt ở **1–2–3**. Khi đó:
- Vẽ **phân bố loại nước đi** cho mỗi setting → nếu gần như không có 5/6/7 → đó chính là **điểm yếu lõi của AdaEvolve**: nó hill-climb chứ không reframe.
- Kiểm tra **cú nhảy điểm lớn nhất đến từ loại nào** → nếu đột phá chỉ tình cờ từ tinh chỉnh, hệ thống không có khả năng tư duy đột phá _có chủ đích_.
- reasoning_effort có dịch phân bố sang 5/6/7 không? Đây là phát hiện đắt giá về việc reasoning có giúp "tư duy ở tầng cao hơn" hay không.

Quy mọi quan sát về 3 nguồn để biết _sửa ở đâu_:
- **Core method** (AdaEvolve): cơ chế chọn parent, island, prompt có khóa hệ thống vào hill-climbing không?
- **Model**: GLM vs DeepSeek khác nhau ở _loại_ nước đi hay chỉ ở chất lượng code?
- **Config** (reasoning/temperature): có thực sự mở ra exploration không?
### Trực quan hoá
Từ quan điểm trên kết hợp với phân tích về cách hoạt động của [[Code/skydiscover/report/week5 (05-06 08-06)/note/Ada evolve]], cần cải tiến website trực quan hoá dữ liệu tại /analysis từ các nguồn dữ liệu sau:
1. **`adaevolve_iteration_stats_*.jsonl`** — mọi _quyết định adaptive_ (intensity, mode, island, G, UCB, paradigm, spawn). 1 dòng = 1 iteration. **Nguồn giàu nhất cho quyết định.**
2. **`checkpoints/checkpoint_N/programs/<id>.json`** — _prompt thực tế_ gửi LLM + _response_ (reasoning + code) + code parent (tra theo `parent_id`).
3. **`logs/adaevolve_*.log`** — _sự kiện cấp hệ thống_ dạng người-đọc-được (paradigm sinh ra, "new best", stagnation).

Tuy nhiên có điểm khuyết không lộ rõ trong log là migration, cần phải sửa code để log thêm nếu muốn biết.

### Nhận định chung
Cấu trúc một prompt:
```
# Current Solution Information      ← metrics của parent
# Program Generation History
  ## Previous Attempts              ← siblings (con khác cùng parent)
  ## Other Context Solutions        ← Program 1-4 (full code + combined_score)
# Current Solution                  ← code parent đầy đủ
## PARENT SELECTION CONTEXT
  ### EXPLORATION GUIDANCE          ← label explore/exploit fix cứng
## BREAKTHROUGH IDEA - IMPLEMENT THIS  ← paradigm text (nếu active)
## PREVIOUS ATTEMPTS ON THIS PARENT
## RETRY CONTEXT                   ← lỗi nếu có
# Task                             ← hướng dẫn + format diff
```
Có thể thấy feedback duy nhất về chất lượng là `combined_score` . Không có bất kì tri thức nào đi kèm, lí do chậm,... Trong khi phân tích ở trên cho thấy cần tập trung vào việc lưu trữ và tiến hoá vốn kiến thức.

Phân loại iteration vào một trong 7 mức độ cải tiến bên trên, phụ thuộc vào:
- diff parent→child
- response reasoning (đoạn prose đầu) 
- mode + paradigm_active + score parent vs child

### Đánh giá log benchmark

/home/team/skydiscover/benchmarks/ADRS/cloudcast/outputs/adaevolve/cloudcast_0607_041411_ds_high
Ite 1: 0.0009 -> 0.001353 (loại 5)
Parent: Bài toán được nhìn như **N bài unicast độc lập**: mỗi đích tự tìm đường rẻ nhất, không chia sẻ cạnh giữa các đích, không quan tâm capacity.
Child: Bài toán giờ được nhìn như **multicast / Steiner-tree packing có ràng buộc capacity**: các đích **chia sẻ chung một cây** (giảm transfer dư thừa), và capacity quyết định mỗi cây gánh được bao nhiêu partition.
Sinh ra từ **một bước exploration bình thường** — đòn bẩy duy nhất của hệ thống ở đây là cái `EXPLORE_LABEL` nhét vào prompt, còn cú nhảy khung là **do bản thân LLM**

Ite 13: 0.001353 -> 0.001488 (loại 3)
Parent: parent đưa khung Steiner packing tối ưu, được 4 context programs confirm với cùng điểm số 0.0013
Liên hệ với reference: mạnh với parent (kế thừa nguyên khung + giữ code cũ làm fallback), yếu với 3 context (chỉ gợi ý "ngẫu nhiên hoá")
LLM đóng góp cái gì: cơ chế cụ thể — randomized multi-start: nhiễu cost → pool cây Steiner đa dạng → chọn greedy theo cost — là kỹ thuật metaheuristic LLM tự mang vào, không lấy từ reference nào.

Ite 19: 0.001488 -> 0.001503 (loại 3)
Thay đổi: greedy allocation → Simulated Annealing trên gán partition↔cây
Idea này không liên quan gì các ref, vẫn lấy khung steiner tree, thay đổi nhỏ giúp tiến tới cận của hướng steiner này.
Idea này đến từ paradigm

Ite 22: 0.001561, +15%
Reference (context 4aa912fa) cấp toàn bộ kiến trúc (cand-tree + SA-over-tree).
LLM cấp phần đột phá: efficiency-ratio sort + ngân sách SA 6× → chính 2 thứ này đẩy lên new best +15%.
Hệ thống adaptive cấp cơ hội: UCB chọn parent từ nhánh A nhưng global-context-sampling nhét program nhánh B vào prompt → LLM thấy được nhánh tốt hơn và "nhảy" sang. 