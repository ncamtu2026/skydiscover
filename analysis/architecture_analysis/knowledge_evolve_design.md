# KnowledgeEvolve — Design Plan

## 1. Tổng quan

KnowledgeEvolve là module RAG (Retrieval-Augmented Generation) độc lập, cung cấp
**kiến thức từ paper** như là context bổ trợ cho quá trình sinh solution của AdaEvolve
(và sau này các module khác).

Mỗi iteration, dựa trên state hiện tại của search (mode, stage), KnowledgeEvolve:
1. Sinh queries phù hợp với context
2. Retrieve paper knowledge từ ChromaDB
3. Sample kết quả (score-weighted + random)
4. Trả về context dạng `raw_text` hoặc `digest`

---

## 2. Cấu trúc thư mục

```
skydiscover/knowledge/
├── __init__.py
├── config.py              ← tất cả hyperparams + embedding config
├── ingest.py              ← JSONL → ChromaDB (ingestion pipeline)
├── embedder.py            ← abstraction layer: Gemini / HuggingFace
├── retriever.py           ← query generation + ChromaDB search + sampling
└── knowledge_evolve.py    ← main class, output modes (raw_text / digest)
```

---

## 3. Data Schema (Input JSONL)

Mỗi dòng trong JSONL:
```json
{
  "paper_path": "/path/to/paper.pdf",
  "summary_dict": {
    "summary":              "# Tên paper\n**TL;DR:** ...",
    "motivation_questions": "### Research Motivation\n...",
    "all_solutions":        "### Sub-question: RQ1...",
    "all_results":          "...",
    "contributions":        "### 1. Core Contributions..."
  }
}
```

5 content fields được index: `summary`, `motivation_questions`, `all_solutions`,
`all_results`, `contributions`.

---

## 4. ChromaDB Schema

**1 collection duy nhất**: `knowledge_base`

Mỗi document = 1 field của 1 paper:
```
id:       "{paper_id}_{field_type}"   e.g. "abc123_all_solutions"
document: content string của field đó
metadata:
  paper_id:    "abc123"               ← hash/slug từ paper_path
  paper_path:  "/path/to/paper.pdf"
  field_type:  "all_solutions"        ← filter theo cái này khi query
  title:       "Paper title"          ← extract từ summary nếu có
  # + tất cả các field còn lại dưới dạng metadata để return cùng
  summary:              "..."
  motivation_questions: "..."
  all_results:          "..."
  contributions:        "..."
```

Lý do 1 collection + metadata filter thay vì 6 collections riêng:
- Operationally đơn giản hơn nhiều
- ChromaDB `where` filter rất nhanh
- Dễ query cross-field khi cần

---

## 5. Embedding Abstraction

Config-driven, hỗ trợ 2 backend:

```python
# config.py
EMBEDDING_BACKEND = "gemini"  # hoặc "huggingface"

GEMINI_CONFIG = {
    "model": "models/text-embedding-004",
    "api_key_env": "GEMINI_API_KEY",
}

HUGGINGFACE_CONFIG = {
    "model": "BAAI/bge-small-en-v1.5",  # hoặc bất kỳ sentence-transformers model
    "device": "cpu",                     # hoặc "cuda"
}
```

`embedder.py` expose interface đồng nhất:
```python
class Embedder:
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

**Quan trọng**: embedding model lúc ingest và lúc query phải giống nhau.
Config được lưu cùng collection metadata để detect mismatch.

---

## 6. Ingestion Pipeline (`ingest.py`)

```
Input: path đến 1 hoặc nhiều JSONL files

for each line in JSONL:
    paper_id = hash(paper_path)
    for each field in [summary, motivation_questions, all_solutions,
                       all_results, contributions]:
        text = summary_dict[field]
        vector = embedder.embed([text])[0]
        chromadb.add(
            id        = f"{paper_id}_{field}",
            embedding = vector,
            document  = text,
            metadata  = {paper_id, paper_path, field_type, ...other fields}
        )
```

Upsert (không duplicate nếu chạy lại). Progress bar với tqdm.

---

## 7. Retrieval & Sampling (`retriever.py`)

### 7.1 Ba cấp độ Search

Toàn bộ pipeline (query tone, LLM temperature, retrieval top_k, sampling temperature)
đều scale theo 3 cấp:

| Cấp | Stage | Query tone | LLM temp | top_k | Softmax temp |
|---|---|---|---|---|---|
| **L1 — Paradigm** | paradigm | Abstract, task-level, không reference current solution. Include failed paradigm history để tránh lặp | High (e.g. 1.2) | 100 | High (≈ uniform) |
| **L2 — Parent+Explore** | parent + explore | Loosely tied to parent (1-line summary). Hướng đến diverse / novel methods | Med (e.g. 0.9) | 50 | Med |
| **L3 — Parent+Exploit** | parent + exploit | Specific: include parent metrics + key bottleneck. Hướng đến targeted optimizations | Low (e.g. 0.3) | 30 | Low (sharp) |

Unified bằng softmax temperature thay vì 2 code path riêng:
```
temperature cao → distribution phẳng gần uniform   (diversity)
temperature thấp → winner-takes-most               (precision)
```

### 7.2 Query Generation

1 LLM call với temperature theo cấp, structured output sinh 5 queries cùng lúc:

```python
# Input context cho query generation:
{
  "task_description": "...",
  "current_best_score": 0.85,
  "evaluator_feedback": "...",        # artifact feedback nếu có
  "level": "L1" | "L2" | "L3",       # xác định từ (stage, mode)
  "parent_summary": "...",            # chỉ có ở L2, L3
  "parent_metrics": {...},            # chỉ có ở L3
  "failed_paradigms": [...],          # chỉ có ở L1
}

# Output (structured JSON):
{
  "summary":              "query for summary field",
  "motivation_questions": "query for motivation field",
  "all_solutions":        "query for solutions field",
  "all_results":          "query for results field",
  "contributions":        "query for contributions field",
}
```

### 7.3 Retrieval

Với mỗi field query → ChromaDB `query()` với `where={"field_type": field}`,
`n_results = top_k[level]` (L1=100, L2=50, L3=30).

Gộp tất cả results từ 5 fields → dedup theo `paper_id + field_type`.

### 7.4 Sampling

Từ pool candidates sau dedup:

**6 score-weighted samples**:
```
scores = cosine similarity từ ChromaDB (đã có sẵn)
weights = softmax(scores / softmax_temperature[level])
sample 6 without replacement theo weights
```

**1 random sample**:
```
query ChromaDB không có filter, lấy 1 random document
(đảm bảo không trùng với 6 samples trên)
```

**Dedup check**: so sánh `paper_id + field_type` trước khi add vào final list.

**Total**: 7 samples.

---

## 8. Output Modes (`knowledge_evolve.py`)

### Mode `raw_text`
Trả về content của từng sample, format trực tiếp vào prompt:
```
=== Knowledge Reference 1 ===
[Field: all_solutions | Paper: ...]
{content of field}

=== Knowledge Reference 2 ===
...
```

### Mode `digest`
Thêm 1 LLM call để "digest" 7 samples thành actionable hints:
```
Input: 7 raw samples + task context + mode/stage
Output: 3-5 bullet points dạng:
  "• From paper X: technique Y showed Z improvement by doing ..."
  "• Consider approach A (seen in papers X, Y) which addresses ..."
```

Config default: `output_mode = "raw_text"` cho v1.

---

## 9. Integration với AdaEvolve

### 9.1 Enable flags

**Integration flags nằm trong `AdaEvolveDatabaseConfig`** — vì đây là quyết định
của AdaEvolve về cách dùng knowledge, không phải của module knowledge.
`KnowledgeEvolveConfig` chỉ chứa params nội tại (embedding, ChromaDB, retrieval).

```python
# Trong AdaEvolveDatabaseConfig:
use_knowledge_evolve: bool = False    # master toggle cho AdaEvolve
knowledge_use_parent: bool = True     # inject khi stage = parent
knowledge_use_paradigm: bool = True   # inject khi stage = paradigm
```

Các search method khác (OpenEvolve, GEPA, ...) tự thêm flags tương tự vào config
của họ khi muốn tích hợp KnowledgeEvolve.

Trong YAML config:
```yaml
search:
  type: adaevolve
  database:
    use_knowledge_evolve: true
    knowledge_use_parent: true
    knowledge_use_paradigm: true
    ...

knowledge:                          # standalone config của module
  embedding_backend: gemini
  chroma_persist_dir: ./chroma_db
  ...
```

### 9.2 Luồng tích hợp

KnowledgeEvolve được gọi trong `AdaEvolveController._generate_child()`, **trước**
`build_prompt()`. Kết quả được đưa vào `context["knowledge"]`.

```python
# Trong _generate_child():
if self.knowledge_evolve:
    stage = "paradigm" if paradigm else "parent"
    should_use = (
        (stage == "parent"   and ke_config.use_in_parent)
        or (stage == "paradigm" and ke_config.use_in_paradigm)
    )
    if should_use:
        context["knowledge"] = await self.knowledge_evolve.get_context(
            task_description   = self.config.context_builder.system_message,
            current_best_score = self.database.get_program_proxy_score(best_program),
            evaluator_feedback = parent.artifacts.get("feedback"),
            stage              = stage,
            search_mode        = sampling_mode,
            parent_code        = parent.solution,
            parent_metrics     = parent.metrics,
            failed_paradigms   = self.database.get_previously_tried_ideas(),
        )
```

`AdaEvolveContextBuilder._build_search_guidance()` đọc `context["knowledge"]` và
append vào sections (sau paradigm, trước error retry).

KnowledgeEvolve không biết gì về AdaEvolve internals — chỉ nhận context dict thuần
và trả về string.

---

## 10. Config (`config.py`)

```python
# --- skydiscover/knowledge/config.py ---
@dataclass
class KnowledgeEvolveConfig:
    # Embedding
    embedding_backend: str = "gemini"       # "gemini" | "huggingface"
    gemini_model: str = "models/text-embedding-004"
    huggingface_model: str = "BAAI/bge-small-en-v1.5"
    huggingface_device: str = "cpu"

    # ChromaDB
    chroma_persist_dir: str = "./chroma_db"
    collection_name: str = "knowledge_base"

    # Retrieval — per level (L1=paradigm, L2=parent+explore, L3=parent+exploit)
    top_k: dict = field(default_factory=lambda: {"L1": 100, "L2": 50, "L3": 30})

    # Sampling softmax temperature — per level
    softmax_temperature: dict = field(default_factory=lambda: {"L1": 5.0, "L2": 1.5, "L3": 0.5})

    # LLM temperature for query generation — per level
    query_llm_temperature: dict = field(default_factory=lambda: {"L1": 1.2, "L2": 0.9, "L3": 0.3})

    # Sampling counts
    n_weighted_samples: int = 6
    n_random_samples: int = 1

    # Output
    output_mode: str = "raw_text"           # "raw_text" | "digest"
    max_tokens_per_sample: int | None = None  # None = no truncation

    # Fields để index/query
    content_fields: list = field(default_factory=lambda: [
        "summary", "motivation_questions", "all_solutions",
        "all_results", "contributions"
    ])

# --- skydiscover/config.py (AdaEvolveDatabaseConfig, thêm vào cuối) ---
    use_knowledge_evolve: bool = False
    knowledge_use_parent: bool = True
    knowledge_use_paradigm: bool = True
```

---

## 11. Dependencies mới

```
chromadb
google-generativeai   # nếu dùng Gemini embedding
sentence-transformers # nếu dùng HuggingFace embedding
```

---

## 12. Thứ tự implement

1. `knowledge/config.py` — KnowledgeEvolveConfig với enabled + use_in_parent/paradigm flags
2. `knowledge/embedder.py` — Gemini + HuggingFace backends
3. `knowledge/ingest.py` — JSONL → ChromaDB
4. `knowledge/retriever.py` — query gen + search + sampling
5. `knowledge/knowledge_evolve.py` — main class, 2 output modes
6. `knowledge/__init__.py` — exports
7. `config.py` (main) — thêm `knowledge: KnowledgeEvolveConfig` vào `Config`
8. `context_builder/adaevolve/builder.py` — thêm section 5 (knowledge context)
9. `search/adaevolve/controller.py` — gọi knowledge_evolve trước build_prompt
