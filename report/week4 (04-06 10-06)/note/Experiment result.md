Mỗi task chạy sẽ chạy 8 nhánh (2 loại model GLM & DS và 4 loại method reasoning). Mỗi lần chạy với 3 tasks, tổng 24 nhánh. Đã chạy 2 lần nhưng không có lần nào chạy đủ 100 ite. Hiện tại đang chạy với adaevolve only.

Lần đầu chạy với code sai khiến output của các nhánh gộp về một folder (bao gồm programs, log,…)
Có thể check qua được điểm số cuối cùng từng nhánh nhưng không biết được nhánh nào được điểm đó.
![[Pasted image 20260607195247.png]]
![[Pasted image 20260607195256.png]]


Lần thứ 2 đang chạy giở thì deepseek hết tiền.
![[Pasted image 20260607195359.png]]
![[Pasted image 20260607195408.png]]
![[Pasted image 20260607195417.png]]

Thông tin bên lề:
- Đã push code cs frontier và tối ưu tốc độ eval llm_sql, đang chờ chạy nốt code eval cũ (đợt 2 bên trên) để thực hiện pull.
- Task txn khi phân tích có tốc độ eval rất chậm, đang trong quá trình tối ưu.