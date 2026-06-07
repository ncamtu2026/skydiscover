# Checkpoint Analyzer

Web UI để quan sát trực quan quá trình tìm kiếm của SkyDiscover qua từng checkpoint.

## Cài đặt & chạy

```bash
cd skydiscover/analysis

# Cài dependencies (chỉ cần lần đầu)
pip install flask openai
# hoặc nếu dùng uv:
uv pip install flask openai

# Chạy server
python3 app.py
```

Mở trình duyệt tại **http://localhost:5050**

---

## Cách dùng

### 1. Load checkpoints

Nhập đường dẫn vào ô input — mỗi dòng một thư mục — rồi nhấn **Load**.

Tool tự nhận 3 dạng path:

| Path bạn nhập | Tool tìm checkpoints ở |
|---|---|
| `/path/to/txn_output` | `/path/to/txn_output/checkpoints/checkpoint_N/` |
| `/path/to/txn_output/checkpoints` | `/path/to/txn_output/checkpoints/checkpoint_N/` |
| Thư mục chứa `checkpoint_N` trực tiếp | Ngay trong thư mục đó |

Ví dụ nhập nhiều benchmark cùng lúc:

```
/Users/iscrea/Projects/BigVault/Code/skydiscover/benchmarks/ADRS/txn_scheduling/txn_output
/Users/iscrea/Projects/BigVault/Code/skydiscover/benchmarks/ADRS/cloudcast/cloudcast_output
/Users/iscrea/Projects/BigVault/Code/skydiscover/benchmarks/ADRS/eplb/eplb_output
```

> Nếu một benchmark chạy nhiều lần và checkpoint tiếp tục từ chỗ dừng, nhập lần lượt các thư mục output theo đúng thứ tự — tool sẽ ghép và sắp xếp theo iteration number.

---

### 2. Score chart

Sau khi load, biểu đồ hiện ở trên cùng:
- **Trục X**: iteration number
- **Trục Y**: metric được chọn (mặc định `combined_score`)
- Click vào bất kỳ điểm nào trên biểu đồ để nhảy tới checkpoint đó
- Đổi metric hiển thị bằng dropdown bên cạnh tiêu đề chart

---

### 3. Xem chi tiết checkpoint

Click vào một checkpoint trong danh sách bên trái.

**Tab "Best Program Diff"**
- So sánh side-by-side code của best program giữa checkpoint hiện tại và checkpoint liền trước
- Các dòng thêm vào màu xanh, dòng xóa đi màu đỏ

**Tab "Candidates"**
- Danh sách toàn bộ candidate programs được sinh ra tại iteration này, sort by score
- Click vào một candidate:
  - **Sub-tab Solution**: full code với syntax highlighting
  - **Sub-tab Reasoning & Diff**: reasoning của LLM + từng thay đổi SEARCH/REPLACE được render thành diff riêng

---

### 4. AI Analysis

Nhấn vào **AI Analysis** ở thanh dưới cùng để mở panel.

| Field | Mô tả |
|---|---|
| Start / End iteration | Giới hạn range checkpoint để phân tích |
| Interval | Chỉ lấy mẫu mỗi N checkpoint trong range (tránh gửi quá nhiều token) |
| API base URL | Base URL của LLM API (tương thích OpenAI) |
| Model | Tên model |
| API key | API key tương ứng |
| Custom prompt | Câu hỏi phân tích tuỳ chỉnh, để trống sẽ dùng prompt mặc định |

**Ví dụ config API:**

| Provider | API base URL | Model |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-pro` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| Anthropic (proxy) | URL proxy tương thích OpenAI | tuỳ |

Nhấn **Preview sample** để xem trước danh sách checkpoint sẽ được gửi, rồi nhấn **Analyse** để gửi và nhận kết quả streaming.

> API settings (base URL, model, key) được lưu tự động vào `localStorage` của trình duyệt.

---

## Cấu trúc file

```
analysis/
├── app.py          # Flask backend (đọc file, tính diff, gọi LLM API)
├── index.html      # Frontend (single-page app, không cần build)
├── requirements.txt
└── README.md
```
