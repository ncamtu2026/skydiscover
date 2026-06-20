# Thiết kế search policy trên experience graph (paradigm → formulation → mechanism)

Tài liệu này tổng hợp thiết kế đã thảo luận cho tầng quyết định điều khiển vòng lặp evolve: chọn action, chọn solution direction, sinh solution, cập nhật graph, lặp lại. Mỗi phần gồm: thiết kế cụ thể, vì sao chọn thiết kế đó (đối chiếu paper), và kỳ vọng/rủi ro.

---

## 0. Bức tranh tổng thể

```
Vòng lặp chính:
  loop:
    a = chọn_action_type()                      # Tầng 1: bandit 3-trọng-số
    if a == EXPLOIT:
        dir_k = chọn_direction_UCB()             # Tầng 2a
        parent = sample_parent_power_law(dir_k)
        child = LLM_mutate(parent)
    elif a == CROSSOVER_EXPLORE:
        S = chọn_5_solution_MMR()                # Tầng 2b (không có "base")
        child = LLM_crossover(S)
    elif a == SPACE_EXPLORE:
        target = chọn_formulation_hay_direction() # Tầng 2c: bandit 2-trọng-số
        child = LLM_generate_new(target, graph_summary)

    score = evaluate_on_simulator(child)
    insert_into_graph(child, score)              # luôn dùng abstract() + insert() có sẵn
    update_all_stats(a, score)                   # cập nhật mọi tầng vừa dùng
```

Nguyên tắc xuyên suốt rút ra được trong quá trình thiết kế: **bandit chỉ dùng cho thực thể sống lâu, được thử lại nhiều lần qua thời gian** (action-type, solution direction, formulation-vs-direction). Quyết định *tại chỗ, không tích lũy* (chọn 1 parent cụ thể, chọn 5 solution cụ thể cho 1 lần crossover) thì dùng sampling theo phân phối tính lại mỗi lần, không phải bandit. Đây là bài học rút ra trực tiếp từ cách AdaEvolve tách Level 1 (không bandit) khỏi Level 2 (bandit).

---

## 1. Tầng 1 — chọn action-type

Kiến trúc **2 cấp**, bám sát đúng cách AdaEvolve tách Level 2 (bandit) khỏi Level 3 (Meta-Guidance, kích hoạt bởi stagnation, đứng ngoài bandit). Space-explore KHÔNG phải một arm ngang hàng trong bandit — nó là một "circuit breaker" chỉ kích hoạt khi toàn hệ thống bão hòa.

### 1.1. Cấp ngoài — circuit breaker theo stagnation (không bandit)

Track một signal toàn cục, giống $G_t^{(k)}$ của AdaEvolve nhưng tính trên toàn hệ thống thay vì 1 island:

$$\delta_t^{\text{global}} = \max\left(\frac{f' - f^*_{\text{global}}}{f^*_{\text{global}}}, 0\right), \qquad G_t^{\text{global}} = \rho\, G_{t-1}^{\text{global}} + (1-\rho)(\delta_t^{\text{global}})^2$$

Khi $G_t^{\text{global}}$ tụt dưới ngưỡng $\tau_{\text{stag}}$ (toàn hệ thống không còn đẩy được global best lên) → kích hoạt **space-explore** cho vòng này, bỏ qua bandit cấp trong.

```
function choose_action(t):
    if G_global < τ_stag:
        return SPACE_EXPLORE          # circuit breaker
    else:
        return bandit_2arm()          # exploit vs crossover
```

Tùy chọn mềm hơn ngưỡng cứng on/off: kích hoạt space-explore với xác suất tăng dần khi $G_t^{\text{global}}$ giảm (vd $P(\text{space}) = \text{sigmoid}(\lambda(\tau_{\text{stag}} - G_t^{\text{global}}))$) — tránh dao động bật/tắt quanh ngưỡng.

### 1.2. Cấp trong — bandit 2-arm (exploit vs crossover)

Giờ chỉ còn đúng 2 action → generalize trực tiếp công thức gốc DecentMem (arxiv 2605.22721), **không sửa gì**:

$$\alpha_E = \frac{w_{\text{exploit}}}{w_{\text{exploit}} + w_{\text{crossover}}}, \qquad P(\text{exploit}) = \alpha_E$$

Tín hiệu nhị phân $\Delta_t = \mathbb{1}[f' > f_{\text{parent}}]$ (so với solution cha trực tiếp, KHÔNG so global best). Update — **giữ $w_{\text{crossover}} = 1.0$ cố định** đúng như paper giữ $w_{X\text{-pool}}=1.0$ cố định:

$$w_{\text{exploit}} \leftarrow \begin{cases} w_{\text{exploit}} + \alpha, & \Delta_t = 1 \\ \max(1.0,\ \beta \cdot w_{\text{exploit}}), & \Delta_t = 0 \end{cases} \qquad w_{\text{crossover}} = 1.0$$

### Vì sao thiết kế này (đã sửa từ bản 3-arm trước)

**Vì sao bỏ bandit 3-arm**: bản nháp trước gộp cả 3 action vào 1 bandit 3-trọng-số. Hai lỗi: (1) **$w$ tăng vô hạn** — với 3 action đều động, không action nào cố định nên không có "mỏ neo", trọng số action thắng liên tục tăng không chặn, gây hại thực tế (độ nhạy giảm: $w$ quá lớn thì decay nhân $\beta$ mất rất nhiều vòng mới hạ về mức hợp lý khi action đó hết hiệu quả). (2) **Lệch kiến trúc nguồn**: AdaEvolve không coi "explore-space" là arm ngang hàng — nó là Level 3 Meta-Guidance, một circuit breaker kích hoạt bởi điều kiện stagnation rõ ràng, đứng ngoài bandit.

**Vì sao 2-arm thoát được tăng vô hạn**: paper gốc giữ $w_{X\text{-pool}}=1.0$ cố định làm mỏ neo. Tuy $w_{\text{exploit}}$ vẫn có thể lớn, nhưng (a) chỉ 1 đại lượng động thay vì nhiều, dễ kiểm soát/clip nếu cần; (b) quan trọng hơn — giữ đúng 100% cấu trúc 2-pool nên **chứng minh Theorem 1 & 2 áp dụng nguyên vẹn**, không phải suy diễn tự chế. (Vẫn nên clip $w_{\text{exploit}} \le w_{\max}$ trong cài đặt thực tế để giữ độ nhạy phản ứng.)

**Vì sao stagnation đo trên global, khác với $\Delta_t$ của bandit đo trên cha**: hai tín hiệu phục vụ 2 mục đích khác nhau. Circuit breaker hỏi "toàn hệ thống đã kịch trần chưa" → phải đo so global best (đúng điều kiện spawning của AdaEvolve: "across all islands"). Bandit cấp trong hỏi "hành động cục bộ này có đẩy được tiến trình không" → đo so cha để tránh nhiễu vị trí. Không mâu thuẫn — chúng ở 2 cấp khác nhau.

### Kỳ vọng / rủi ro

- Kỳ vọng: exploit/crossover tự cân bằng theo địa hình; space-explore chỉ tốn budget khi thực sự cần (toàn hệ thống bão hòa), không lãng phí khi đang còn tiến triển.
- Rủi ro: $\tau_{\text{stag}}$ là ngưỡng cần tinh chỉnh — quá cao thì space-explore kích hoạt quá thường (lãng phí), quá thấp thì hệ thống kẹt lâu trong local optimum mới chịu nhảy. Bản mềm (sigmoid) giảm rủi ro này.
- Rủi ro: $\alpha,\beta=0.5$ và $w_{\max}$ là giá trị mượn từ domain khác, cần thử nghiệm.

---

## 2. Tầng 2a — Exploit: chọn solution direction, rồi chọn parent

### 2.1. Chọn solution direction (mechanism node) — bandit thật

Mỗi solution direction $k$ (node tầng mechanism) giữ 4 thống kê: $n_k$ (visit count), $\mu_k$ (mean score), $\sigma_k^2$ (variance score), $f^*_k$ (best score).

UCB chuẩn:
$$\text{UCB}(k) = \mu_k + c\sqrt{\frac{\ln t}{n_k}}, \qquad n_k = 0 \Rightarrow \text{UCB} = \infty$$

Hoặc UCB1-Normal (khuyến nghị, dùng variance thực thay proxy đếm số lần):
$$\text{UCB}_{\text{normal}}(k) = \mu_k + \sqrt{16\,\sigma_k^2 \cdot \frac{\ln(t-1)}{n_k}}$$

```
function choose_direction(directions, t):
    cold = [k for k in directions if n[k] == 0]
    if cold:
        return uniform_random(cold)
    return argmax_k( mu[k] + sqrt(16 * var[k] * log(t-1) / n[k]) )
```

### 2.2. Chọn parent trong direction đã chọn — KHÔNG phải bandit

Power-law / rank-based sampling (ShinkaEvolve):
$$p_i = \frac{r_i^{-\alpha}}{\sum_j r_j^{-\alpha}}, \quad r_i = \text{rank của solution } i \text{ (1 = tốt nhất)}$$

$\alpha=0$: uniform. $\alpha \to \infty$: luôn chọn tốt nhất (hill-climbing).

```
function sample_parent(direction, alpha):
    ranked = sort(direction.solutions, by=score, desc=True)
    weights = [rank^(-alpha) for rank in 1..len(ranked)]
    return weighted_sample(ranked, weights)
```

### Vì sao thiết kế này

**Vì sao UCB cho direction nhưng không cho parent**: phân biệt mấu chốt là direction là thực thể **sống lâu, được thử lại nhiều lần** — giá trị thật của nó chỉ lộ dần qua nhiều lần exploit, đúng setup bandit cổ điển. Một solution cụ thể thì có điểm cố định ngay khi sinh ra, không có gì để "học thêm" về riêng nó qua thời gian — bandit ở đây dư thừa. Đây đúng theo cách AdaEvolve tách Level 2 (bandit cho island) khỏi Level 1 (sampling tĩnh cho parent trong island).

**Vì sao UCB1-Normal được khuyến nghị hơn UCB chuẩn**: bạn đã chủ động đề xuất thêm variance vào 4 thống kê cần track. UCB chuẩn chỉ coi "độ tin cậy" là hàm của *số lần thử*, giả định mọi direction nhiễu giống nhau. Nhưng các solution direction trong domain LLM-evolve chắc chắn không đồng nhất về độ "may rủi" giữa các lần generate — có direction ổn định (LLM dễ tinh chỉnh, ít biến động điểm), có direction hỗn loạn (biến động mạnh theo từng prompt). UCB1-Normal phản ánh đúng: direction ổn định (variance thấp) được tin tưởng nhanh hơn dù mới thử ít lần, direction hỗn loạn cần nhiều lần thử hơn mới dám tin số trung bình.

**Vì sao cold-start không cần optimistic init phức tạp hay LLM prior**: $n_k=0 \Rightarrow$ UCB $=\infty$ là tính chất toán học tự nhiên của công thức, không cần thiết kế thêm. AdaEvolve dùng đúng quy tắc này ("Any island with $V(k)=0$ must be visited at least once").

### Kỳ vọng / rủi ro

- Kỳ vọng: budget tự động dồn vào direction đang "có gradient" (theo nghĩa cải thiện liên tục), tự nhiên rút khỏi direction đã bão hòa — đúng cơ chế đã chứng minh hiệu quả trong AdaEvolve qua 185 benchmark.
- Rủi ro: $c$ (hệ số exploration trong UCB) là siêu tham số cần tinh — AdaEvolve không cần tham số này vì họ dùng cơ chế khác (signal $G_t$ liên tục), còn UCB cổ điển luôn cần $c$. Cần thử nghiệm.

---

## 3. Tầng 2b — Crossover-explore: chọn 5 solution để lai

### Thiết kế (đã chỉnh sau thảo luận — không có "base" riêng)

Quyết định ban đầu (1 base UCB + $m$ inspiration MMR) đã bị thay bằng thiết kế đơn giản hơn, đúng với quan sát của bạn về cách AdaEvolve tách biệt *migration* (định kỳ, không cần base, không cần điều kiện stagnation) khỏi *dynamic spawning* (phản ứng stagnation). Crossover-explore của bạn gần với migration hơn: không cần phân vai base/inspiration trước — coi mọi solution ngang hàng khi sample, để LLM tự tổng hợp, rồi solution mới sinh ra được phân loại thuộc direction nào *sau đó*, qua đúng cơ chế `abstract()` + `insert()` đã có trong graph.

Chọn 5 solution (số cố định) bằng Maximal Marginal Relevance — cân bằng 50/50 giữa chất lượng và đa dạng:

$$\text{dir}_i = \arg\max_{d \in \mathcal{D} \setminus S} \Big[ 0.5 \cdot \bar{F}(d) - 0.5 \cdot \max_{d' \in S} \text{sim}_{\text{code}}(d, d') \Big]$$

lặp lại 5 lần ($S$ là tập đã chọn, bắt đầu rỗng).

$\bar{F}(d)$: chất lượng chuẩn hóa (vd best hoặc mean score của solution đại diện cho $d$, scale về $[0,1]$).

$\text{sim}_{\text{code}}(d, d')$: cosine similarity giữa embedding của phần *mutable code* (chỉ phần trong vùng EVOLVE-BLOCK, không phải toàn file) của 1 solution đại diện mỗi direction — đúng kỹ thuật ShinkaEvolve dùng cho novelty rejection sampling, áp lại ở đây cho mục đích đo đa dạng.

```
function choose_5_for_crossover(directions, embed_fn):
    candidates = [representative_solution(d) for d in directions]
    embeddings = {c: embed_fn(extract_mutable_code(c)) for c in candidates}
    quality   = {c: normalize_score(c.score) for c in candidates}

    S = []
    for _ in range(5):
        best, best_score = None, -inf
        for c in candidates if c not in S:
            div_penalty = 0 if not S else max(cosine_sim(embeddings[c], embeddings[s]) for s in S)
            mmr = 0.5 * quality[c] - 0.5 * div_penalty
            if mmr > best_score:
                best, best_score = c, mmr
        S.append(best)
    return S

function on_crossover_child_created(child, score):
    insert_into_graph(child, score)   # abstract() tự gán paradigm/formulation/mechanism
                                        # không cần biết "base" là gì trước đó
```

### Vì sao thiết kế này

**Vì sao bỏ khái niệm base/inspiration**: bạn chỉ ra khó nói rạch ròi "solution nào tốt/tệ mới đáng base" — đúng, vì việc ép 1 direction phải đóng vai "chính" trước khi sinh là một giả định cứng không cần thiết. Để LLM tự quyết cách tổng hợp 5 nguyên liệu, rồi *post-hoc* xác định solution mới thuộc về đâu, đúng tinh thần graph là `read-only` và `LLM xử lý mọi quyết định ngữ nghĩa` đã chốt từ buổi thiết kế graph trước — không thêm trường dữ liệu hay logic riêng cho crossover trong graph.

**Vì sao MMR**: đây là bài toán "chọn 1 tập con tốt" (subset selection), khác hẳn "chọn 1 arm tốt nhất" — không có thuật toán bandit nào giải trực tiếp bài toán chọn tập. MMR là kỹ thuật chuẩn cho đúng lớp bài toán này (cân bằng quality vs diversity), và literature cùng domain (CodeEvolve, DeepEvolve dùng MAP-Elites cho "structurally distinct high-performing solutions") xác nhận hướng đi này phù hợp, dù không ai trong số đó học $m$ động — tất cả dùng số cố định, nên quyết định "5 cố định" của bạn khớp với thực hành phổ biến, tránh việc thêm một tầng học không cần thiết cho một con số nhỏ.

**Vì sao đo similarity trên code embedding, không trên text summary của graph**: bạn chỉ ra đúng — solution đều ở dạng code, nên đa dạng "thật" cần đo trên chính code, không qua trung gian text. Dùng cùng kỹ thuật ShinkaEvolve (embed mutable code, cosine similarity) tận dụng được: (1) chỉ đo phần code thực sự có thể thay đổi (EVOLVE-BLOCK), tránh boilerplate giống nhau làm nhiễu điểm similarity; (2) đã qua ablation thực nghiệm trong ShinkaEvolve chứng minh proxy hiệu quả mà không cần thêm LLM-judge.

### Kỳ vọng / rủi ro

- Kỳ vọng: giảm hẳn độ phức tạp thiết kế (bỏ 2 sub-quyết-định: chọn base bằng UCB, chọn $m$ động) trong khi vẫn giữ đúng mục tiêu cân bằng quality/diversity.
- Rủi ro: cần 1 "solution đại diện" cho mỗi direction để embed — nên dùng best-score solution trong direction đó, vì đây thường là bản phản ánh đúng "tinh hoa kỹ thuật" của direction nhất.
- Điểm cần thử nghiệm: số 5 cố định có thể không tối ưu cho mọi quy mô graph (5 direction thì chọn 5/5 = toàn bộ, mất hết ý nghĩa "chọn"). Cần ràng buộc $m = \min(5, |\mathcal{D}|)$ tối thiểu.

---

## 4. Tầng 2c — Space-explore: formulation mới hay solution direction mới

Kích hoạt bởi circuit breaker (mục 1.1), không phải lựa chọn ngang hàng trong bandit. Khi đã kích hoạt, cần quyết định: tạo **formulation mới** (cách nhìn bài toán khác hẳn) hay **solution direction mới** trong formulation hiện có (cùng cách nhìn, hướng giải mới). Đây là 2 lựa chọn → bandit 2-trọng-số y hệt mục 1.2:

$$P(\text{new-formulation}) = \frac{w_{\text{new-form}}}{w_{\text{new-form}} + w_{\text{new-dir}}}, \quad w_{\text{new-dir}} = 1.0 \text{ (cố định)}$$

$\Delta_t = \mathbb{1}[f' > f_{\text{seed}}]$ — solution đầu tiên sinh ra trong formulation/direction mới có tốt hơn solution-seed (lấy từ archive làm điểm khởi đầu để "nhảy") không.

### Delayed reward — KHÔNG phải vấn đề (đã làm rõ)

Lo ngại ban đầu: formulation/direction mới sinh ra chưa có solution nào để biết tốt/tệ ngay, reward bị trễ. Kết luận: **không cần xử lý đặc biệt**, vì trách nhiệm được tách sạch giữa 2 tầng:

- Tầng 2c chỉ hỏi: "lần sinh-mới vừa rồi có cải thiện tức thời so với seed không" → đo được ngay tại chỗ qua $\Delta_t$, không trễ.
- "Giá trị lâu dài của thực thể mới" được tầng 2a (UCB) lo: ngay khi thực thể mới được track như 1 arm, $n_k=0 \Rightarrow$ UCB$=\infty$ đảm bảo nó được pull tiếp ở các vòng sau, lộ dần giá trị thật. Chính cơ chế "visit count thấp thì tự được ưu tiên" đã hấp thụ trọn vẹn vấn đề delayed reward — không cần thiết kế thêm gì.

---

## Tổng hợp thống kê cần track trên mỗi node

| Thực thể | Thống kê cần track | Dùng ở đâu |
|---|---|---|
| Action-type (3 cái) | $w_a$ | Tầng 1 |
| Solution direction (mechanism node) | $n_k, \mu_k, \sigma_k^2, f^*_k$ | Tầng 2a (UCB), tầng 2b (quality cho MMR) |
| Solution (leaf) | score, embedding của mutable code | Tầng 2a (rank cho power-law), tầng 2b (sim cho MMR) |
| Formulation node | (chưa cần thống kê riêng — chỉ là điểm trung chuyển trong cây, không phải arm) | — |

---

## 5. Phân tích lý thuyết: thiết kế này có chứng minh được "tìm ra solution" như DecentMem không?

Câu hỏi: DecentMem chứng minh (Theorem 1) global reachability + (Theorem 2) $O(\log T)$ regret. Thiết kế của ta thừa hưởng được gì?

### 5.1. Hai loại đảm bảo, cần tách bạch

**(A) Global reachability** — "search không bao giờ bị khóa cứng khỏi bất kỳ vùng nào của không gian nghiệm; với vô hạn thời gian, mọi nghiệm đều có xác suất được chạm tới." Đây là đảm bảo *định tính*, dễ đạt.

**(B) $O(\log T)$ regret** — "tốc độ hội tụ về lựa chọn tối ưu là tối ưu bậc, sai khác hằng số so với chặn dưới của bandit." Đây là đảm bảo *định lượng*, khó hơn nhiều, và **đây là chỗ thiết kế của ta KHÔNG kế thừa trực tiếp được** (lý do ở 5.3).

### 5.2. Reachability — kế thừa được, nhưng cần điều kiện rõ ràng

DecentMem Theorem 1 dựa trên: ma trận chuyển $M = \alpha T + (1-\alpha) h\mathbf{1}^\top$ là *strictly positive* (mọi phần tử > 0), nhờ (i) $\alpha < 1$ luôn đúng vì $w_X > 0$ cố định, và (ii) prior teleportation $h_i > 0$ cho mọi state khả thi. Khi đó chuỗi Markov irreducible + aperiodic ⇒ reachable toàn cục.

Map sang thiết kế của ta — đảm bảo này **giữ được**, với điều kiện:

1. **Bandit cấp trong không bao giờ khóa cứng exploit hoặc crossover về 0.** Đúng: vì $w_{\text{crossover}}=1.0$ cố định và $w_{\text{exploit}} \ge 1$ (do `max(1.0, ...)`), nên $P(\text{crossover}) = 1/(w_{\text{exploit}}+1) > 0$ luôn — đây chính là vai trò "mỏ neo $w_X$ cố định" của paper, ta giữ nguyên.
2. **Circuit breaker đảm bảo space-explore luôn có cơ hội kích hoạt.** Đúng nếu dùng bản mềm (sigmoid): $P(\text{space}) > 0$ với mọi giá trị $G^{\text{global}}$ hữu hạn. Bản ngưỡng cứng thì KHÔNG đảm bảo điều này (khi $G^{\text{global}} > \tau$, $P(\text{space}) = 0$ tuyệt đối) → **để giữ reachability, nên dùng bản mềm.** Đây là một lý do lý thuyết cụ thể để chọn sigmoid thay vì ngưỡng cứng.
3. **LLM mutation operator có "support" phủ toàn không gian** — tức từ bất kỳ solution nào, LLM có xác suất khác 0 sinh ra bất kỳ solution nào khác. Đây là điều kiện "variation operator completeness" trong lý thuyết EA cổ điển (Theorem 3.1, arxiv 2411.15008: *"EA với elitist selection + variation operator hoàn chỉnh hội tụ tiệm cận về global optimum"*). Với LLM, đây là **giả định không kiểm chứng được** (không ai chứng minh được temperature-sampling của LLM phủ toàn không gian code), nhưng là giả định chuẩn mà *mọi* paper LLM-evolve đều ngầm dùng — không phải điểm yếu riêng của thiết kế ta.

Kết luận (A): **reachability kế thừa được**, với 2 điều kiện ta kiểm soát được (dùng sigmoid; giữ $w_{\text{crossover}}$ cố định) + 1 giả định chung của cả ngành (LLM completeness). Cần thêm điều kiện elitism — graph là read-only, không xóa node, nên best solution không bao giờ mất → elitism thỏa mãn tự nhiên.

### 5.3. Regret $O(\log T)$ — KHÔNG kế thừa trực tiếp, và cần trung thực về điều này

DecentMem Theorem 2 dựa trên **Assumption 1**: hàm reward $r(\alpha)$ là *strictly concave, khả vi 2 lần, có nghiệm tối ưu duy nhất $\alpha^* \in (0.5,1)$*. Đây là giả định rất mạnh, và nó **vỡ** trong thiết kế của ta vì mấy lý do:

1. **Reward landscape của ta non-stationary và phi lõm.** $r(\alpha)$ của DecentMem giả định môi trường tĩnh (mỗi pool có expected reward cố định). Trong hệ của ta, "reward của exploit" thay đổi theo thời gian (lúc đầu exploit kém vì chưa có gì để refine, về sau exploit tốt khi đã có direction mạnh) — landscape dịch chuyển, không có $\alpha^*$ cố định. Bản thân AdaEvolve cũng không chứng minh regret bound vì lý do này — họ chỉ chứng minh empirically qua 185 benchmark.

2. **Số arm tăng dần (ballooning) ở tầng 2a.** Lý thuyết ballooning bandit (Ghalme et al. 2021, arxiv 2501.14314) chứng minh: **không có thuật toán nào đạt sublinear regret trong ballooning setting tổng quát** — regret tuyến tính trừ khi có thêm giả định (best arm đến sớm, hoặc có cấu trúc similarity giữa arm). Tầng 2a của ta là ballooning (solution direction tăng dần) → **không thể có $O(\log T)$ regret guarantee cho tầng này** trừ khi ta thêm giả định ta không kiểm soát được.

3. **Hệ thống nhiều tầng lồng nhau** — regret của hệ composite (circuit breaker × bandit 2-arm × UCB ballooning × MMR subset selection) không có lý thuyết đóng. Mỗi tầng có thể có bound riêng, nhưng *tích hợp* chúng thành 1 bound thống nhất là bài toán mở.

### 5.4. Kết luận trung thực về mặt lý thuyết

| Đảm bảo | DecentMem | Thiết kế của ta | Điều kiện |
|---|---|---|---|
| Global reachability | Có (Thm 1) | **Kế thừa được** | Dùng sigmoid circuit breaker; $w_{crossover}$ cố định; LLM completeness; elitism (graph read-only) |
| $O(\log T)$ regret | Có (Thm 2) | **KHÔNG** | Vỡ do non-stationarity, ballooning arms, multi-level |
| Asymptotic convergence về global optimum | (không phát biểu) | **Kế thừa từ lý thuyết EA cổ điển** | Elitism + variation completeness (Thm 3.1, arxiv 2411.15008) |

**Phát biểu trung thực nhất có thể claim**: thiết kế đảm bảo *asymptotic global convergence* (với vô hạn budget, tìm ra global optimum với xác suất 1) theo lý thuyết EA elitist cổ điển — đây là claim YẾU HƠN regret bound nhưng VỮNG và đúng. Cụ thể: graph read-only ⇒ elitism; circuit-breaker mềm + $w_{crossover}$ cố định ⇒ mọi action luôn có xác suất dương ⇒ với LLM completeness, mọi vùng được chạm tới trong vô hạn ⇒ elitism giữ lại best ⇒ hội tụ về optimum trong giới hạn.

**Điều KHÔNG nên claim**: $O(\log T)$ regret hay bất kỳ tốc độ hội tụ hữu hạn nào "kế thừa từ DecentMem". DecentMem chứng minh được vì họ ở stochastic stationary 2-arm setting; ta thì non-stationary, ballooning, multi-level. Claim regret bound sẽ là sai về mặt toán học.

### 5.5. Hệ quả thiết kế từ phân tích này

1. **Dùng sigmoid circuit breaker, không dùng ngưỡng cứng** — không chỉ vì tránh dao động, mà vì đây là điều kiện cần để giữ reachability guarantee.
2. **Giữ $w_{\text{crossover}}=1.0$ cố định** — là mỏ neo đảm bảo $P(\text{crossover})>0$, điều kiện cho reachability (và tránh tăng vô hạn).
3. **Mục tiêu lý thuyết nên đặt là reachability + asymptotic convergence, không phải regret** — và nên đo regret/sample-efficiency *bằng thực nghiệm* (như AdaEvolve, ShinkaEvolve đều làm), không hứa hẹn bound lý thuyết không có thật.
4. **Nếu muốn có regret bound cho tầng 2a**: cần thêm giả định similarity giữa các solution direction (Double-UCB-BL, arxiv 2501.14314) — tức tận dụng quan hệ "direction mới sinh ra từ direction cũ" làm cạnh similarity. Đây là hướng mở rộng lý thuyết khả thi NẾU sau này cần claim mạnh hơn, nhưng thêm độ phức tạp.