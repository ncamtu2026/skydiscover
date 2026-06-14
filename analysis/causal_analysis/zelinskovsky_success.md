Giờ tôi đã có đủ data để phân tích toàn diện. Câu trả lời ngắn: có rất nhiều thừa thãi, và con đường đến Zelikovsky có thể ngắn hơn 5-6 lần.

Phân tích con đường đến Zelikovsky
1. Bản đồ 13 breakthrough generations
Khi nhìn vào toàn bộ sequence, có thể phân ra 3 loại idea rõ ràng:


G1  09:57  [1] MCF (network_simplex)      ← FLOW ❌
           [2] K-Means Clustering         ← CLUSTER ❌
           [3] KMB Steiner Tree           ← STEINER ✓ → trở thành current best 0.00151

G2  10:31  [1] MCF variant               ← FLOW ❌ (lặp G1[1])
           [2] Hierarchical Partitioning  ← CLUSTER ❌
           [3] MST Arborescence          ← MST variant ❌

G3  11:09  [1] networkx.steiner_tree     ← STEINER ❌ (quá generic, lỗi)
           [2] MCF + linprog             ← FLOW/LP ❌ (lặp)
           [3] Edge Betweenness          ← CENTRALITY ❌

G4  11:25  [1] LP linprog               ← LP ❌ (lặp G3[2])
           [2] Successive SP            ← PATH ❌
           [3] Capacity Steiner         ← STEINER ❌ (vague)

G5  11:52  [1] LP linprog               ← LP ❌ (lặp G4[1])
           [2] Hierarchical Clustering  ← CLUSTER ❌ (lặp G1[2])
           [3] Greedy Path Packing      ← PATH ❌

G6  12:18  [1] 2-Opt Local Search       ← STEINER variant ❌
           [2] Throughput Metric        ← MST variant ❌
           [3] K-Shortest Paths         ← PATH ❌

G7  12:40  [1] MCF + LP                 ← FLOW/LP ❌ (lặp)
           [2] Successive SP            ← PATH ❌ (EXACT REPEAT of G4[2]!)
           [3] K-Means                  ← CLUSTER ❌ (EXACT REPEAT of G1[2]!)

G8  13:08  [1] Successive SP            ← PATH ❌ (3rd time!)
           [2] LP linprog               ← LP ❌ (4th time!)
           [3] K-Shortest Diversif.     ← PATH ❌

G9  13:28  [1] Max-Flow Min-Cost        ← FLOW ❌
           [2] Reverse-Delete Pruning   ← MST variant ❌ ← NÀY LÀ NGU NGƠ NHẤT
           [3] Community Detection      ← GRAPH CLUSTER ❌ ← NÀY CŨNG VẬY

G10 14:02  [1] Network Simplex          ← FLOW ❌
           [2] Shadow Pricing           ← ??? ❌ ← HOÀN TOÀN KHÔNG LIÊN QUAN
           [3] Centrality Partitioning  ← CENTRALITY ❌ (lặp G3[3])

G11 14:26  [1] Takahashi-Matsuyama     ← STEINER ❌ (score không đổi)
           [2] Hierarchical Clustering  ← CLUSTER ❌ (lặp G1[2], G5[2])
           [3] LP Relaxation            ← LP ❌ (lặp G3[2], G4[1], G5[1], G7[1], G8[2])

G12 14:44  [1] Adaptive Metric Closure  ← MST variant ❌ ← SAU KHI TM FAIL, VẪN QUAY LẠI!
           [2] Greedy Capacity Path     ← PATH ❌
           [3] Diversified K-Shortest   ← PATH ❌ (lặp lần thứ 4!)

G13 15:07  [1] ZELIKOVSKY               ← STEINER ✓✓✓ BREAKTHROUGH
           [2] Beam Search              ← SEARCH ❌
           [3] Edge Replacement Local   ← LOCAL SEARCH ❌
2. Những chỗ thừa thãi thực sự
Thừa thãi cấp độ 1: Lặp hoàn toàn

LP / linprog: G3, G4, G5, G7, G8, G11 → 6 lần cùng 1 concept, không lần nào cải thiện
Successive Shortest Path: G4, G7, G8 → 3 lần exact repeat
K-Shortest Paths: G6, G8, G12 → 3+ lần
K-Means Clustering: G1, G5, G7 → 3 lần
MCF/Flow: G1, G2, G7, G9, G10 → 5 lần cùng nhóm thuật toán
Tổng: khoảng 22/39 idea slots (55%) là lặp lại concept đã fail.

Thừa thãi cấp độ 2: "Ngu ngơ" — ý tưởng clearly sẽ fail mà vẫn generate

G9[2] Reverse-Delete Pruning: Đây là một biến thể của MST — thuật toán xóa edge khỏi MST. Nhưng MST/arborescence đã là current best rồi, làm sao 1 MST variant tệ hơn lại có thể cải thiện?
G9[3] Community Detection: Dùng greedy_modularity_communities để phân vùng broadcast tree. Community detection là thuật toán phát hiện cụm trong mạng xã hội — hoàn toàn không liên quan đến min-cost spanning.
G10[2] Shadow Pricing: Khái niệm từ lý thuyết game/pricing, dùng để balance load. Broadcast tree optimization không có "price signal" nào để exploit.
G12 toàn bộ: Đây là gen thừa thãi nhất về mặt logic. TM vừa fail xong ở G11. Đáng lẽ hệ thống phải nghĩ "TM không cải thiện được vì nó cũng chỉ operate trong không gian terminal — cần thử thuật toán Steiner tree khác xét intermediate nodes." Thay vào đó G12 generate: Adaptive Metric Closure (MST variant), Greedy Capacity Path (path-based), K-Shortest (lặp lần 4). Zelikovsky lẽ ra phải xuất hiện ở G12.
3. Con đường tối thiểu cần thiết
Nhìn lại, chỉ cần 3 breakthrough generations là đủ để đến Zelikovsky:


G1: KMB (Steiner tree) → success → current best 0.00151
G2: TM (greedy Steiner SPH) → fail, same score → chứng minh "terminal-only search không đủ"
G3: Zelikovsky (intermediate Steiner nodes) → SUCCESS 0.00160
Thay vào đó hệ thống đi qua 13 generations. 10 generations thừa = khoảng 60+ iterations bị mất.

4. Tại sao có sự thừa thãi — root cause
Root cause 1: approach_type track theo library-function, không theo conceptual family

Hệ thống track failures theo key như scipy.optimize.linprog hay networkx.algorithms.flow.network_simplex. Khi network_simplex failed, nó không mark "MCF/Flow đã fail" — nó chỉ block cái tên library cụ thể đó. Nên max_flow_min_cost (G9), network_simplex dưới alias khác (G10, G15, G16) đều được generate thoải mái dù cùng 1 concept.

Nếu thay bằng conceptual category tracking: sau G1 fail MCF, toàn bộ FLOW approaches bị block. After G3 fail LP, toàn bộ LP approaches bị block. Kết quả: by G4, system phải generate ideas thuộc nhóm hoàn toàn khác — và Steiner tree family là lựa chọn logic nhất.

Root cause 2: Diversity requirement ép 3 ideas từ 3 TYPES khác nhau

Diversity requirement có ý tốt: tránh generate 3 ideas cùng loại. Nhưng side effect là: ngay cả khi system đang "gần" với answer (e.g., G11 vừa thử TM), 2 trong 3 slots phải dành cho category KHÁC. Kết quả: G11 = [TM, Clustering, LP] — Zelikovsky bị đẩy ra.

Nếu không có diversity requirement, G12 có thể là [TM (failed), Zelikovsky, Robins-Zelikovsky] — focus hoàn toàn vào Steiner tree family.

Root cause 3: RAG papers hoàn toàn không liên quan

Papers được retrieve: GNN system optimization, ByteScheduler, distributed ML. Không một paper nào về Steiner tree approximation algorithms. Nếu RAG đã có Zelikovsky 1993 hay Robins-Zelikovsky 2000, idea sẽ xuất hiện ở G1 hoặc G2.

Root cause 4: LLM "thoái lui" ra khỏi Steiner domain sau mỗi lần fail

Đây là cái thú vị nhất. Sau khi networkx.algorithms.approximation.steiner_tree fail ở G3, LLM không nghĩ "cần implement Steiner algorithm tốt hơn thủ công." Nó nghĩ "Steiner tree approach đã fail, thử cái khác." Rồi 8 generations sau G11 (TM) mới quay lại Steiner.

Và sau G11 fail, G12 lại thoái lui thêm lần nữa. LLM không có mechanism để nhận ra "TM fail ≠ Steiner algorithms fail — TM chỉ là 1 trong nhiều Steiner algorithms, tôi cần thử cái khác trong family."

5. Description của Zelikovsky — có phải sản phẩm tất yếu của tiến hóa không?
Câu trả lời: Đúng, nhưng không phải vì tất cả 13 generations — chỉ cần 2 bước trước là đủ.

Zelikovsky description cụ thể và đúng vì:

Khi gen 13 prompt được gửi, context chứa:

Current best: KMB (builds metric closure over terminals → MST → map back) = 0.00151
Failed: TM (iteratively add terminal closest to current tree via shortest path) = same score
Cả KMB và TM đều hoạt động trong terminal-only space. Từ pattern này, LLM có thể rút ra insight: "cả hai approach đều tốt như nhau vì cả hai đều giới hạn trong không gian terminal, cần thuật toán mở rộng không gian tìm kiếm sang non-terminal nodes."

Và đó chính xác là điều Zelikovsky làm: enumerate ALL nodes (không chỉ terminals) như potential Steiner points, calculate gain của việc insert từng node vào tree.

Nếu không có TM trong failed list, LLM có thể describe Zelikovsky vaguely (giống như nó đã describe TM vaguely ở G11 — chỉ nói "find closest terminal" mà không mention intermediate nodes). Chính việc TM fail với SAME SCORE đã tạo ra tín hiệu "terminal-only search đã saturated" → LLM phải explicitly mention intermediate non-terminal nodes trong Zelikovsky description.

Vậy cái "tất yếu" là:

KMB succeed → chứng minh Steiner tree direction đúng
TM fail (same score) → chứng minh terminal-only search không đủ
→ Zelikovsky với intermediate nodes là sự khác biệt cốt lõi
Cái KHÔNG tất yếu là 10 generations lạc đường giữa 1 và 2.

6. Tóm tắt
Loại iteration	Số lượng	Đánh giá
G1 (KMB): Steiner discovery	~6 iter	Tất yếu
G3[1], G4[3], G6[1]: Steiner variants trying & failing	~9 iter	Gần như tất yếu — cần exhaust "basic Steiner"
G11 (TM): fail cùng score KMB	~6 iter	Tất yếu — establishes "terminal-only saturated"
G13 (Zelikovsky)	~6 iter	Tất yếu
G2, G5, G7, G8, G9, G10, G12 (LP×6, MCF×5, Clustering×4, Centrality×3, K-Shortest×4, Community Detection, Shadow Pricing, Reverse-Delete)	~42 iter	Thừa thãi hoàn toàn
Khoảng 70% iterations sau stagnation là wasted. Và cái wasted không phải là kiểu "đi thăm dò hướng lạ thú vị" — mà là kiểu "LP đã fail 2 lần rồi vẫn generate LP lần 3, 4, 5, 6," và "Community detection cho broadcast tree routing."

Cốt lõi của vấn đề: hệ thống không có category-level memory. Mỗi lần generate breakthrough, nó chỉ nhớ "cái tên library cụ thể này đã fail" — không nhớ "cái category thuật toán này đã fail." Và khi mỗi generation bị ép ra 3 ideas từ 3 types khác nhau, tự nhiên nhiều slots sẽ rơi vào các category cũ dưới tên mới.