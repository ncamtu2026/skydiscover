## eplb_output (Run A)

| Iter  | Score  | Ý tưởng                                                                             |
| ----- | ------ | ----------------------------------------------------------------------------------- |
| 1     | 0.1452 | Thuật toán gốc DeepSeek — hierarchical 3 tầng (group→node→GPU), greedy packing      |
| 2     | 0.1462 | Bỏ tầng, xử lý global trực tiếp. GPU balance tệ hơn nhưng nhanh hơn                 |
| 5     | 0.1479 | Dùng Python list thay tensor trong inner loop → nhanh hơn 3.5x                      |
| 7-10  | 0.1483 | Micro-optimize vòng lặp                                                             |
| 19    | 0.1519 | **Round-robin vectorized** thay greedy packing → **100x nhanh hơn** (0.085s→0.002s) |
| 21    | 0.1525 | **Snake round-robin** — đảo chiều mỗi vòng để balance tốt hơn                       |
| 22    | 0.1526 | Bỏ packing hoàn toàn (identity) + chuyển sang numpy → **0.001s**                    |
| 49-52 | 0.1528 | Clean code, không đổi thuật toán                                                    |

**Định hướng:** Đơn giản hóa tối đa, đánh đổi balance lấy tốc độ.

---

## eplb_0601_2322 (Run B)

| Iter | Score  | Ý tưởng                                                                                                 |
| ---- | ------ | ------------------------------------------------------------------------------------------------------- |
| 1    | 0.1295 | Thuật toán gốc, khởi đầu yếu hơn Run A                                                                  |
| 26   | 0.1429 | **Joint optimization** — quyết định replicate và assign GPU đồng thời. Đúng về lý thuyết nhưng 7.5 giây |
| 28   | 0.1436 | **Binary search** tìm λ tối ưu cho số replica mỗi expert → toán học chính xác hơn, 0.21s                |
| 29   | 0.1438 | Kết hợp binary search + round-robin assign                                                              |
| 31   | 0.1441 | Tiếp tục refine, không breakthrough                                                                     |

**Định hướng:** Giải đúng bài toán về mặt toán học, nhưng bị penalty vì chậm hơn Run A.

---

**Kết quả:** Run A thắng (0.1528 vs 0.1441) vì metric thưởng tốc độ đủ mạnh để bù đắp cho việc balance kém hơn một chút.