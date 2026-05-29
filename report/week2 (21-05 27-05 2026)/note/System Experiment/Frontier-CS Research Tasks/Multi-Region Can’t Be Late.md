Bài CBL gốc (NSDI'24) chỉ xử lý **một region duy nhất** - job chạy ở một zone cố định, chỉ chọn giữa spot/on-demand trong zone đó.

Nhưng thực tế cloud, đặc biệt với GPU đắt và khan hiếm:
- **Mỗi region/zone có pattern availability khác nhau**.
- **Giá spot cũng khác giữa các region** (paper [49] SkyServe: Serving ai models across regions and clouds with spot instances của Ion Stoica đã chứng minh).
- Khi job đang chờ trong region A mà spot không khả dụng, có thể region B đang dư spot.

Khi mở rộng sang multi-region, không gian quyết định của policy phức tạp hơn nhiều. Policy giờ phải trả lời:
1. **Dùng spot hay on-demand?** (như trước)
2. **Dùng region nào?** (mới)
3. **Khi nào migrate job sang region khác?** (mới)
4. **Có đáng trả migration cost để chuyển sang region rẻ hơn không?** (mới)

Object & Metric Evaluate:
- Minimize **total cost** = chi phí spot + on-demand + migration (công thức này không được nhắc đến rõ ràng trong bài báo này, vì đây là phần mở rộng sơ lược, cần định nghĩa lại công thức nếu tiến hành thử)
- Constraint: tất cả deadline phải đáp ứng (bắt buộc)

**Baseline** (vì không có SOTA public): Mở rộng "Uniform Progress" của bài gốc thành multi-region
- Đầu tiên thử lấy spot ở region hiện tại
- Nếu không có → thử các region khác theo **round-robin**
- Nếu không region nào có → on-demand

**Ngoài lề**: output của evolution đã học được từ những lần failure do quá tham và học cách logic hoá các quyết định rất clean như:
- **Deadline assessment** (job khẩn cấp hay không) là một quyết định
- **Resource provisioning** (dùng region nào, spot hay on-demand) là quyết định khác