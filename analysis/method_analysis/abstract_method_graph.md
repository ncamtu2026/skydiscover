# ════════════════════════════════════════════════════════════
# EXPERIENCE GRAPH — full pseudo-code (a) insert + (b) summarize
# Nguyên tắc xuyên suốt:
#   - Mọi quyết định ngữ nghĩa -> LLM. Code chỉ thao tác cây.
#   - Summary là BÁO CÁO, không khuyến nghị. Không tính từ đánh giá.
#   - Nén chỉ làm lúc summarize, trong phạm vi 1 node mechanism.
# ════════════════════════════════════════════════════════════


# ─────────────── DATA STRUCTURES ───────────────

Node:
    id
    type           # "root" | "internal" | "leaf"
    label          # nhãn ngắn do LLM sinh (hướng đi / mô tả solution)
    field_name     # internal: tầng này là gì — "paradigm"|"formulation"|"mechanism"
    children
    # leaf only:
    solution_id
    score
    rationale_ref  # trỏ về rationale/diff gốc, để truy lại khi cần

ExperienceGraph:
    root           # Node(type="root")


# ════════════════════════════════════════════════════════════
# (a) INSERT — để LLM quyết đặt solution mới vào đâu
# ════════════════════════════════════════════════════════════

function insert(graph, solution):
    graph_view = render_for_insert(graph.root)   # cây dạng text, kèm id mỗi node

    decision = LLM_place(
        solution_rationale = solution.rationale,
        solution_diff      = solution.diff,
        current_graph      = graph_view
    )

    apply_decision(graph, solution, decision)


# --- render cây cho prompt insert: đủ id để LLM trỏ tới ---
function render_for_insert(node, depth=0):
    indent = "  " * depth
    if node.type == "leaf":
        line = f"{indent}[{node.id}] (leaf) {node.label} | score={node.score}"
    else if node.type == "root":
        line = f"[{node.id}] ROOT"
    else:
        line = f"{indent}[{node.id}] ({node.field_name}) {node.label}"
    out = [line]
    for c in node.children:
        out += render_for_insert(c, depth+1)
    return join(out, "\n")


# --- thực thi quyết định: thuần thao tác cây ---
function apply_decision(graph, solution, d):
    leaf = Node(type="leaf", label=d.leaf_label,
                solution_id=solution.id, score=solution.score,
                rationale_ref=solution.rationale_ref)

    switch d.action:
        case "ATTACH_TO":
            find(graph, d.target_id).add_child(leaf)

        case "NEW_BRANCH_UNDER":
            parent = find(graph, d.target_id)
            # d.new_path = danh sách (field_name, label) các tầng cần tạo mới
            #   vd [("paradigm","DP"),("formulation","interval"),("mechanism","bottom-up")]
            node = parent
            for (fname, flabel) in d.new_path:
                inter = Node(type="internal", field_name=fname, label=flabel, children=[])
                node.add_child(inter); node = inter
            node.add_child(leaf)

        case "SPLIT":
            old = find(graph, d.target_leaf_id)
            parent = parent_of(graph, old)
            inter = Node(type="internal",
                         field_name=d.split_field_name, label=d.new_label, children=[])
            detach(parent, old)
            inter.add_child(old); inter.add_child(leaf)
            parent.add_child(inter)


PROMPT (LLM_place)

Bạn đang bảo trì một cây phân tầng các HƯỚNG GIẢI cho một bài toán tối ưu.
Cây có đúng ba tầng trừu tượng, từ tổng quát đến cụ thể:
  paradigm  →  formulation  →  mechanism
Lá là từng solution cụ thể, kèm score.

CÂY HIỆN TẠI:
{current_graph}

SOLUTION MỚI:
  rationale: {solution_rationale}
  diff:      {solution_diff}

NHIỆM VỤ: quyết định đặt solution mới vào đâu, chọn ĐÚNG MỘT action:

- ATTACH_TO (target_id):
    Dùng khi solution mới CÙNG HƯỚNG tới tận tầng mechanism với một nhánh đã có.
    Nó sẽ thành một leaf nữa nằm cạnh các leaf cùng mechanism đó.

- NEW_BRANCH_UNDER (target_id, new_path):
    Dùng khi solution rẽ hướng mới ở một tầng nào đó.
    target_id là node cuối cùng còn KHỚP; new_path liệt kê các tầng phải tạo mới
    bên dưới nó, mỗi tầng gồm (field_name, label).
    Nếu paradigm hoàn toàn mới: target_id = ROOT, new_path đủ cả 3 tầng.

- SPLIT (target_leaf_id, split_field_name, new_label):
    Dùng khi solution mới và MỘT leaf đang tồn tại thực ra chung một hướng
    trừu tượng ở tầng split_field_name mà cây CHƯA biểu diễn tách ra.
    Tạo một internal node cha chung (nhãn new_label) bọc cả hai.

QUY TẮC QUAN TRỌNG:
1. Ưu tiên TÁI SỬ DỤNG nhãn đã có trong cây. Nếu solution thuộc paradigm
   "LP" đã xuất hiện, dùng đúng nhãn "LP", TUYỆT ĐỐI không tạo nhãn đồng nghĩa
   ("linear programming", "LP-based"...). Chỉ tạo nhãn mới khi thực sự không
   khớp bất kỳ nhãn cùng tầng nào.
2. Nhãn phải NGẮN, mang tính phân loại (1–4 từ), không phải câu mô tả dài.
3. Phán đoán "cùng hướng" dựa trên Ý TƯỞNG THUẬT TOÁN trong rationale,
   KHÔNG dựa trên độ giống nhau bề mặt của code.

Trả về JSON:
{ "action": ..., "target_id": ..., "new_path": [...],
  "target_leaf_id": ..., "split_field_name": ..., "new_label": ...,
  "leaf_label": "<nhãn ngắn cho solution mới>" }


# ════════════════════════════════════════════════════════════
# (b) SUMMARIZE — render cây phân tầng. Nén leaf TRONG TỪNG node mechanism.
# Không phân cụm lại toàn cục. Không diễn giải.
# ════════════════════════════════════════════════════════════

COMPRESS_THRESHOLD = 4   # mechanism có > ngưỡng leaf thì mới nén

function summarize(graph):
    lines = ["EXPLORATION SUMMARY (experience memory)", ""]
    for paradigm_node in graph.root.children:
        render_summary(paradigm_node, lines, depth=0)
    return join(lines, "\n")


function render_summary(node, lines, depth):
    indent = "   " * depth

    if node.type == "leaf":
        lines.add(f"{indent}- {node.label}  {round(node.score,2)}")
        return

    # internal node
    marker = "▸ " if depth == 0 else f"{node.field_name}: "
    lines.add(f"{indent}{marker}{node.label}")

    # node mechanism với quá nhiều leaf -> nén; còn lại render thường
    leaf_children = [c for c in node.children if c.type == "leaf"]

    if node.field_name == "mechanism" and len(leaf_children) > COMPRESS_THRESHOLD:
        groups = LLM_group_leaves(leaf_children)     # gom các leaf THẬT SỰ trùng hướng
        for g in groups:
            render_compressed_group(g, lines, depth+1)
    else:
        for c in node.children:
            render_summary(c, lines, depth+1)


# --- in một nhóm leaf đã nén: CHỈ dữ kiện thô, không tính từ ---
function render_compressed_group(group, lines, depth):
    indent = "   " * depth
    scores = sorted(g.score for g in group.leaves)
    n = len(scores)
    if n == 1:
        lines.add(f"{indent}- {group.label}  {round(scores[0],2)}")
    else:
        lo, hi, med = scores[0], scores[-1], median(scores)
        lines.add(f"{indent}- {group.label}  "
                  f"({n} mẫu | {round(lo,2)}–{round(hi,2)} | median {round(med,2)})")


PROMPT (LLM_group_leaves)

Dưới đây là các solution nằm CÙNG MỘT mechanism trong cây hướng giải.
Chúng đã được xếp cùng nhóm vì gần giống nhau, nhưng có thể vẫn lẫn vài
biến thể khác hướng nhỏ.

CÁC SOLUTION:
{for each leaf: "[id] label | score"}

NHIỆM VỤ: gom các solution THẬT SỰ cùng một cách làm thành nhóm.
- Hai solution chỉ khác nhau ở chi tiết cài đặt -> cùng nhóm.
- Hai solution khác nhau ở ý tưởng cốt lõi -> tách nhóm riêng.
- Mỗi nhóm đặt một nhãn ngắn (1–4 từ) mô tả cách làm chung.

TUYỆT ĐỐI KHÔNG:
- Không đánh giá tốt/xấu, không nói "đã bão hòa", "mạnh", "yếu",
  "tiềm năng", "gần trần"... Chỉ gom nhóm và đặt nhãn mô tả trung tính.
- Không suy luận về score. Không xếp hạng nhóm.

Trả về JSON: [ { "label": "...", "leaf_ids": [...] }, ... ]