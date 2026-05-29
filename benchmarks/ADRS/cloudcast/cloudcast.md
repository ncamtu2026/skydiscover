# Cloudcast — Phân tích chi tiết

## Mục lục
1. [Bài toán là gì](#1-bài-toán-là-gì)
2. [Cấu trúc dữ liệu và đồ thị](#2-cấu-trúc-dữ-liệu-và-đồ-thị)
3. [Pipeline evaluate hoạt động như nào](#3-pipeline-evaluate-hoạt-động-như-nào)
4. [Cách tính score](#4-cách-tính-score)
5. [Baseline hiện tại làm gì và tại sao fail](#5-baseline-hiện-tại-làm-gì-và-tại-sao-fail)
6. [Các solution tiềm năng](#6-các-solution-tiềm-năng)
7. [Trade-off cốt lõi](#7-trade-off-cốt-lõi)

---

## 1. Bài toán là gì

**Mục tiêu:** Broadcast một dataset (mặc định **4 GB**) từ một cloud region nguồn đến nhiều cloud region đích với **tổng chi phí thấp nhất**.

Mạng lưới là đồ thị có hướng gồm các region thực của AWS, GCP, Azure. Mỗi cạnh trong đồ thị có:
- `cost` — giá egress ($/GB)
- `throughput` — băng thông tối đa (Gbps)

Dataset được chia thành `num_partitions` phần (partition), mỗi partition có thể đi đường khác nhau.

**Input của algorithm:**
```python
def search_algorithm(src, dsts, G, num_partitions):
    # src:            string — region nguồn, vd: "aws:us-east-1"
    # dsts:           list   — các region đích
    # G:              DiGraph — đồ thị cloud network
    # num_partitions: int    — số phần chia của file
```

**Output phải trả về:** một `BroadCastTopology` với cấu trúc:
```python
paths[destination][partition_id] = [
    (node_A, node_B, edge_data),   # cạnh 1
    (node_B, node_C, edge_data),   # cạnh 2
    ...                            # phải liên tục và kết thúc tại destination
]
```

---

## 2. Cấu trúc dữ liệu và đồ thị

### Xây dựng đồ thị

```python
G = make_nx_graph(num_vms=2)
```

Đọc 2 file CSV thực tế (download từ HuggingFace):
- `profiles/cost.csv` — giá egress thực tế giữa từng cặp region
- `profiles/throughput.csv` — băng thông đo được, nhân với `num_vms` (mặc định 2)

Kết quả là `networkx.DiGraph` với hàng chục node region. Ví dụ:
```
node: "aws:us-east-1", "gcp:us-central1", "azure:eastus", ...
edge aws:us-east-1 → gcp:us-central1: {cost: 0.08, throughput: 10.0}
```

### Giới hạn bandwidth theo provider

Mỗi cloud provider có giới hạn ingress/egress tại mỗi node:

| Provider | Ingress (Gbps) | Egress (Gbps) |
|----------|---------------|--------------|
| AWS      | 10            | 5            |
| GCP      | 16            | 7            |
| Azure    | 16            | 16           |

Khi tổng flow vào/ra node vượt giới hạn, simulator **chia đều** cho các cạnh:
```
flow_thực = min(flow_gốc, limit / số_cạnh_tại_node)
```

### BroadCastTopology

Class đại diện cho kết quả routing:
```python
class BroadCastTopology:
    src:            str              # region nguồn
    dsts:           List[str]        # danh sách destination
    num_partitions: int
    paths:          dict             # paths[dst][str(partition_id)] = list of edges
```

Mỗi edge trong paths có dạng `[src_node, dst_node, edge_data_dict]`.

---

## 3. Pipeline evaluate hoạt động như nào

### 5 scenario test

Sau khi `bash download_dataset.sh`, có 5 file JSON:

| File | Mô tả |
|------|-------|
| `intra_aws.json`   | Broadcast trong nội bộ AWS |
| `intra_azure.json` | Broadcast trong nội bộ Azure |
| `intra_gcp.json`   | Broadcast trong nội bộ GCP |
| `inter_agz.json`   | Cross-cloud: AWS + GCP + Azure |
| `inter_gaz2.json`  | Cross-cloud: variation khác |

Mỗi file JSON chứa:
```json
{
  "source_node": "aws:us-east-1",
  "dest_nodes": ["gcp:us-central1", "azure:eastus", "aws:eu-west-1"],
  "num_partitions": 4,
  "data_vol": 4.0,
  "ingress_limit": {"aws": 10, "gcp": 16, "azure": 16},
  "egress_limit":  {"aws": 5,  "gcp": 7,  "azure": 16}
}
```

### Luồng xử lý từng config

```
config JSON
    ↓
make_nx_graph() → đồ thị cloud network
    ↓
search_algorithm(src, dsts, G, num_partitions)  ← CODE CỦA BẠN
    ↓
validate_broadcast_topology()  → fail → score = 0 ngay
    ↓
BCSimulator.__construct_g()
    → enforce ingress/egress limits
    ↓
__transfer_time()  → tính bottleneck, max transfer time
    ↓
__total_cost()  → egress_cost + instance_cost
    ↓
Cộng dồn qua 5 configs
```

**Lưu ý quan trọng:** Nếu **bất kỳ** config nào fail (validation error hoặc exception) → `combined_score = 0.0` ngay lập tức, không tính các config còn lại.

### Bước validate (5 điều kiện)

1. Danh sách destination phải khớp với config
2. Source node phải đúng
3. Tất cả partition phải có đường đi (không được `None` hay rỗng)
4. Đường đi phải liên tục — mỗi cạnh nối tiếp cạnh trước, kết thúc đúng tại destination
5. Tổng số partition = `len(dsts) × num_partitions`

### Bước simulate — BCSimulator

**Xây dựng simulation graph:**

Từ paths trả về, dựng lại đồ thị với flow ban đầu = throughput max. Sau đó enforce bandwidth limits:

```python
# Nếu 3 paths đi ra khỏi aws:us-east-1, tổng egress = 15 Gbps > giới hạn 5 Gbps
# → mỗi cạnh chỉ còn 5/3 = 1.67 Gbps thực tế
flow_proportion = 1 / số_cạnh_tại_node
g[src][dst]["flow"] = min(flow_gốc, limit × flow_proportion)
```

**Tính transfer time:**

Với mỗi destination, mỗi partition:
```
bottleneck = min(flow) dọc theo tất cả cạnh của partition đó
partition_time = (data_vol / num_partitions) / bottleneck
dst_time = max(partition_time của tất cả partition)  # partitions chạy song song
```

Transfer time tổng:
```
max_t = max(dst_time của tất cả destination)
```

---

## 4. Cách tính score

### Total cost = 2 thành phần

**Egress cost — tiền data:**
```
Với mỗi cạnh trong simulation graph:
    egress_cost += số_partition_đi_qua × (data_vol / num_partitions) × cost_$/GB
```

Đây là phần **relay sharing tác động trực tiếp**: nếu 3 destination cùng share một cạnh A→B, thì chỉ có `num_partitions` partition đi qua (không phải `3 × num_partitions`).

**Instance cost — tiền thuê VM:**
```
Với mỗi node xuất hiện trong simulation graph:
    instance_cost += num_vms × ($0.54/3600) × max_t (giây)
```

Mỗi node trung gian thêm vào đường đi sẽ làm tăng instance cost.

**Tổng:**
```python
total_cost = egress_cost + instance_cost
```

### Combined score

```python
# Chạy qua 5 configs, cộng dồn total_cost
combined_score = 1.0 / (1.0 + total_cost)   # càng gần 1 càng tốt
```

---

## 5. Baseline hiện tại làm gì và tại sao fail

### Baseline — Dijkstra độc lập

```python
for dst in dsts:
    path = nx.dijkstra_path(h, src, dst, weight="cost")  # tìm đường rẻ nhất
    for i in range(0, len(path) - 1):
        for j in range(num_partitions):
            bc_topology.append_dst_partition_path(dst, j, ...)  # tất cả partition đi cùng đường
```

### Vấn đề 1 — Trả egress nhiều lần cho cùng một cạnh

```
3 destinations đều cần đi qua relay R:

Dijkstra (độc lập):                 Solution tốt hơn:
  S → R → dst1  (trả S→R lần 1)      S → R → dst1
  S → R → dst2  (trả S→R lần 2)           └→ dst2
  S → R → dst3  (trả S→R lần 3)           └→ dst3
  Egress S→R = 3 × 4GB × $/GB        Egress S→R = 1 × 4GB × $/GB
```

Tiền data tăng tuyến tính theo số destination cùng đi qua một cạnh.

### Vấn đề 2 — Tất cả partition đi cùng một đường

```python
# Baseline: partition 0, 1, 2, 3 đều đi cùng path → không tận dụng multi-path
for j in range(bc_topology.num_partitions):
    bc_topology.append_dst_partition_path(dst, j, [s, t, G[s][t]])
```

Nếu có 2 đường song song mỗi cái 5 Gbps:
- Baseline: tất cả đi 1 đường → bottleneck 5 Gbps
- Multi-path: chia đều 2 đường → effective 10 Gbps, nhanh gấp đôi → instance cost giảm một nửa

### Vấn đề 3 — Tối ưu cost/hop, không tính throughput

Dijkstra tìm đường rẻ nhất theo cost/GB, nhưng đường rẻ đôi khi có bandwidth thấp → transfer chậm → instance cost cao hơn. Tổng cost cuối có thể đắt hơn đường nhanh hơn một chút.

### Vấn đề 4 — Không tính congestion khi lập kế hoạch

Khi nhiều destination đi qua cùng một node có bandwidth thấp, node đó bị congestion. Dijkstra chạy độc lập từng destination nên không biết các destination khác đang làm gì.

---

## 6. Các solution tiềm năng

### Solution 1 — Steiner Tree (Cây phân phối chung)

**Ý tưởng:** Thay vì gửi data riêng lẻ, tìm **cây phủ nhỏ nhất** kết nối source đến tất cả destination. Data đi theo cây — mỗi cạnh chỉ trả tiền một lần dù nhiều destination dùng chung.

```
Giống đường ống nước:
  Nguồn → phân nhánh tại relay → đến từng đích
  Mỗi đoạn ống chỉ tốn tiền một lần
```

**Ví dụ tiết kiệm:**
```
Không relay:  S→A ($5), S→B ($5), S→C ($5)  → tổng $15
Có relay R:   S→R ($3), R→A ($1), R→B ($1), R→C ($1) → tổng $6
```

**Cách implement (heuristic đơn giản):**
1. Chạy Dijkstra từ source đến tất cả destination
2. Lấy **union** của tất cả các đường — tự nhiên tạo thành cây chung
3. Các cạnh chung giữa các đường chỉ xuất hiện một lần trong topology

**Cách implement chính xác hơn:**
- Metric closure: tính shortest path giữa mọi cặp node
- Xây MST trên metric closure
- Mở rộng về đồ thị gốc

**Hạn chế:** Bài toán Steiner Tree là NP-hard, phải dùng xấp xỉ. Thêm relay node → tăng instance cost. Relay chỉ có lợi khi tiết kiệm egress lớn hơn tiền VM thêm.

---

### Solution 2 — Multi-path Routing (Chia luồng qua nhiều đường)

**Ý tưởng:** Thay vì tất cả partition đi một đường, **chia partition qua nhiều đường song song** để tăng throughput.

```
Baseline (1 đường):
  Partition 0,1,2,3 → đường A (5 Gbps) → 4 GB / 5 Gbps = 6.4 giây

Multi-path (2 đường song song):
  Partition 0,1 → đường A (5 Gbps)   ↘
                                        chạy song song → 3.2 giây ✅
  Partition 2,3 → đường B (5 Gbps)   ↗
```

Nhanh gấp đôi → `max_t` giảm một nửa → `instance_cost` giảm một nửa.

**Cách implement:**
```python
# Tìm k đường ngắn nhất (k-shortest paths)
from networkx.algorithms.simple_paths import shortest_simple_paths

paths = list(islice(shortest_simple_paths(G, src, dst, weight="cost"), k))

# Chia partition cho từng đường
partitions_per_path = num_partitions // k
for i, path in enumerate(paths):
    for p in range(i * partitions_per_path, (i+1) * partitions_per_path):
        bc_topology.set_dst_partition_paths(dst, p, path_to_edges(path))
```

**Lưu ý:** Phải kiểm tra bandwidth limits — nếu 2 đường đều đi qua một node, node đó có thể bị congestion và cả 2 đường đều chậm lại.

---

### Solution 3 — Cost-aware Relay Selection (Chọn relay thông minh)

**Ý tưởng:** Không cần Steiner Tree phức tạp — heuristic đơn giản: **nhóm các destination theo vị trí địa lý/mạng, tìm relay tốt nhất cho mỗi nhóm**.

```
Nhóm 1 (các region châu Á):  gcp:asia-east1, aws:ap-northeast-1
Nhóm 2 (các region châu Âu): azure:westeurope, aws:eu-west-1

Source → Relay_Asia  → [gcp:asia-east1, aws:ap-northeast-1]
Source → Relay_Europe → [azure:westeurope, aws:eu-west-1]
```

**Cách tìm relay tốt nhất cho một nhóm:**
```python
best_relay, min_cost = None, float('inf')
for candidate in G.nodes:
    relay_cost = shortest_path_cost(src, candidate) + \
                 sum(shortest_path_cost(candidate, dst) for dst in group)
    if relay_cost < min_cost:
        min_cost = relay_cost
        best_relay = candidate
```

**Ưu điểm:** Đơn giản hơn Steiner Tree, dễ implement, thường cho kết quả đủ tốt (80-90% optimal).

**Thách thức:** Cần quyết định cách nhóm destination — theo provider? Theo địa lý? Theo chi phí?

---

### Solution 4 — Min-cost Flow (Tối ưu phân phối luồng)

**Ý tưởng:** Sau khi chọn topology, thay vì greedy phân phối bandwidth, dùng bài toán **min-cost flow** để tìm phân phối tối ưu toàn cục.

**Vấn đề greedy giải quyết kém:**
```
S cần gửi đến A và B, cả 2 có thể đi qua R2:
  S → R1 → A  (5 Gbps, $1/GB)
  S → R2 → A  (3 Gbps, $0.5/GB)
  S → R2 → B  (3 Gbps, $0.5/GB)

Greedy: cả A và B đều chọn R2 (rẻ hơn)
  → R2 bị chia đôi → mỗi đường chỉ còn 1.5 Gbps → chậm

Min-cost flow: A đi R1, B đi R2
  → A: 5 Gbps, B: 3 Gbps → nhanh hơn → instance cost thấp hơn
```

**Cách implement với networkx:**
```python
import networkx as nx

# Formulate as min cost flow problem
flow_dict = nx.min_cost_flow(flow_graph)
```

**Ưu điểm:** Tìm phân phối tối ưu toàn cục, không bị local minima.

**Hạn chế:** Cần formulate đúng bài toán (capacity, demand, cost). Phức tạp hơn các approach khác.

---

### Solution 5 — Hybrid: Steiner Tree + Multi-path

**Ý tưởng:** Kết hợp 2 cách bổ sung nhau:

```
Bước 1 — Steiner Tree:
  Tìm cây relay tốt để minimize egress cost
  S → R → [dst1, dst2, dst3]

Bước 2 — Multi-path:
  Với mỗi đoạn (S→R) và (R→dst),
  tìm thêm đường song song
  Partition 0,1 → đường chính
  Partition 2,3 → đường dự phòng

Kết quả: ít trả tiền egress (Steiner) + transfer nhanh (multi-path)
```

**Tại sao hybrid mạnh hơn:**
- Steiner Tree tối ưu **chi phí data egress**
- Multi-path tối ưu **thời gian transfer → instance cost**
- Hai cái bổ sung cho nhau

---

## 7. Trade-off cốt lõi

Hai mục tiêu kéo nhau theo **hướng ngược nhau**:

| Muốn giảm | Cần làm gì | Hệ quả |
|-----------|-----------|--------|
| **Egress cost** | Relay sharing, Steiner tree, ít gửi lại cùng data | Thêm node trung gian → instance cost tăng |
| **Instance cost** | Transfer nhanh, ít node, đường thẳng | Không share → egress cost tăng |

**Bẫy thường gặp — relay không phải lúc nào cũng có lợi:**

```
Relay chỉ tốt khi:
  tiết_kiệm_egress > tiền_VM_relay_thêm

Tiết kiệm egress = (số_dst - 1) × data_vol × cost_cạnh_chia_sẻ
Tiền VM relay    = num_vms × $0.54/3600 × transfer_time

Nếu cost cạnh chia sẻ thấp hoặc chỉ có 2 destination → relay không đáng
```

**Quy tắc thực hành:**
- Với `intra_*` (cùng cloud): egress rẻ hơn nhiều → relay ít lợi hơn
- Với `inter_*` (cross-cloud): egress đắt → relay share rất có giá trị
- Bandwidth limit càng thấp → multi-path càng quan trọng

---

## Tham khảo code

| File | Vai trò |
|------|---------|
| [initial_program.py](Code/skydiscover/benchmarks/ADRS/cloudcast/initial_program.py) | Baseline Dijkstra — phần code cần evolve |
| [Code/skydiscover/benchmarks/ADRS/cloudcast/evaluator/evaluator.py](Code/skydiscover/benchmarks/ADRS/cloudcast/evaluator/evaluator.py) | Orchestrate 5 configs, validate, tính score |
| [simulator.py](simulator.py) | BCSimulator — enforce limits, tính time và cost |
| [broadcast.py](broadcast.py) | BroadCastTopology class |
| [Code/skydiscover/benchmarks/ADRS/cloudcast/evaluator/utils.py](Code/skydiscover/benchmarks/ADRS/cloudcast/evaluator/utils.py) | make_nx_graph, helper functions |
| [evaluate.py](evaluate.py) | Các baseline khác: N_direct, Min_Steiner_Tree |
| [config.yaml](Code/skydiscover/benchmarks/ADRS/cloudcast/config.yaml) | Config chạy adaevolve/skydiscover |
