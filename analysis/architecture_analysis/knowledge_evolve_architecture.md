# KnowledgeEvolve — Architecture & Usage

## 1. Tổng quan

KnowledgeEvolve là module RAG (Retrieval-Augmented Generation) **độc lập**, cung cấp
kiến thức từ academic papers như là context bổ trợ cho quá trình sinh solution của các
search algorithm (AdaEvolve, và sau này các module khác).

**Ý tưởng cốt lõi**: Mỗi iteration, thay vì LLM chỉ dựa vào bộ nhớ pre-training,
KnowledgeEvolve retrieve các đoạn paper liên quan và inject vào prompt — giống như
trao cho LLM một stack tài liệu chuyên ngành ngay tại thời điểm sinh solution.

```
paper corpus (JSONL)
        ↓ ingest
   ChromaDB (vectors)
        ↓ retrieve (mỗi iteration)
  7 relevant excerpts
        ↓ format/digest
  knowledge context string
        ↓ inject
   LLM optimization prompt
```

---

## 2. Cấu trúc module

```
skydiscover/knowledge/
├── __init__.py           ← public exports
├── config.py             ← KnowledgeEvolveConfig (standalone dataclass)
├── embedder.py           ← Gemini / HuggingFace embedding backends
├── ingest.py             ← JSONL → ChromaDB pipeline
├── retriever.py          ← query gen + ChromaDB search + sampling
└── knowledge_evolve.py   ← main class, 2 output modes
```

Module **không import bất kỳ thứ gì từ AdaEvolve** — hoàn toàn độc lập.
Integration flags (`use_knowledge_evolve`, `knowledge_use_parent`, `knowledge_use_paradigm`)
nằm trong config của từng search algorithm, không trong KnowledgeEvolveConfig.

---

## 3. Data Schema

### Input JSONL (mỗi dòng)
```json
{
  "paper_path": "/path/to/paper.pdf",
  "summary_dict": {
    "summary":              "# Paper Title\n**TL;DR:** ...",
    "motivation_questions": "### Research Motivation\n...",
    "all_solutions":        "### Sub-question: RQ1...",
    "all_results":          "...",
    "contributions":        "### 1. Core Contributions..."
  }
}
```

### ChromaDB Schema
1 collection duy nhất (`knowledge_base`), mỗi document = 1 field của 1 paper:

```
id:       "{paper_id_12chars}_{field_type}"
document: content của field đó
metadata:
  paper_id:    "abc123def456"
  paper_path:  "/path/to/paper.pdf"
  field_type:  "all_solutions"         ← filter khi query
  title:       "Paper title"
  summary:     "..."                   ← các field còn lại (để return full context)
  motivation_questions: "..."
  all_results: "..."
  contributions: "..."
```

---

## 4. Ba cấp độ Search (L1 / L2 / L3)

Toàn bộ pipeline — query tone, LLM temperature, top_k, sampling temperature — scale
theo 3 cấp xác định từ `(stage, search_mode)`:

| Cấp | Khi nào | Query tone | LLM temp | top_k | Softmax temp |
|---|---|---|---|---|---|
| **L1** | `stage == paradigm` | Abstract, task-level. Không reference current solution. Include failed paradigm history. | 1.2 (creative) | 100 | 5.0 (≈ uniform) |
| **L2** | `stage == parent` + `mode ∈ {exploration, balanced, None}` | Loose parent tie. Hướng diverse / novel methods. | 0.9 (balanced) | 50 | 1.5 (moderate) |
| **L3** | `stage == parent` + `mode == exploitation` | Specific: include parent metrics + bottleneck. Targeted optimizations. | 0.3 (focused) | 30 | 0.5 (sharp) |

**Lý do dùng softmax temperature thay vì hai distribution riêng:**
```
temperature cao → distribution phẳng gần uniform   → diversity
temperature thấp → winner-takes-most               → precision
```

---

## 5. Pipeline mỗi iteration

```
get_context(stage, search_mode, parent_code, ...)
    │
    ├── _determine_level()   → L1 / L2 / L3
    │
    ├── retriever.retrieve()
    │   │
    │   ├── _generate_queries()          ← 1 LLM call, temp=query_llm_temperature[level]
    │   │   └── 5 queries (1 per field)  ← structured JSON output
    │   │
    │   ├── for each field:
    │   │   ├── embed(query, task_type="query")
    │   │   └── chromadb.query(where={"field_type": field}, n_results=top_k[level])
    │   │
    │   ├── merge all results + dedup by doc_id
    │   │
    │   ├── _softmax_sample(n=6, temp=softmax_temperature[level])
    │   │   └── weights = softmax((1 - distances) / temp)
    │   │
    │   └── _random_sample(n=1, exclude=sampled_ids)
    │       └── total = 7 samples
    │
    └── format output
        ├── output_mode == "raw_text" → _format_raw()   (no extra LLM call)
        └── output_mode == "digest"  → _digest()        (1 extra LLM call → 3-5 bullets)
```

---

## 6. Output Modes

### `raw_text` (default)
Inject trực tiếp các excerpts vào prompt:
```
## KNOWLEDGE REFERENCES
Excerpts from academic papers that may provide relevant techniques or insights.

### [1] Paper Title — all_solutions
{full content of field}

### [2] Another Paper — contributions
{full content of field}
...
```

### `digest`
Thêm 1 LLM call compress 7 samples thành 3-5 actionable bullet points:
```
## KNOWLEDGE INSIGHTS

• From [Paper X]: technique Y showed Z% improvement by doing ...
• Consider approach A (seen in papers X, Y) which directly addresses ...
• [Paper Z] reports that strategy B outperforms baseline by ...
```

`digest` tốt hơn về signal-to-noise nhưng tốn thêm 1 LLM call mỗi iteration.

---

## 7. Configuration

### `KnowledgeEvolveConfig` (trong `Config.knowledge`)

```yaml
knowledge:
  # Embedding
  embedding_backend: gemini          # "gemini" | "huggingface"
  gemini_embedding_model: models/text-embedding-004
  huggingface_embedding_model: BAAI/bge-small-en-v1.5
  huggingface_device: cpu

  # ChromaDB
  chroma_persist_dir: ./chroma_db
  collection_name: knowledge_base

  # Query generation LLM
  # Auto-detects Gemini endpoint nếu model name bắt đầu "gemini-"
  query_model_name: gemini-2.0-flash
  query_api_key: null                # fallback: GEMINI_API_KEY / OPENAI_API_KEY env
  query_api_base: null               # fallback: auto-detect từ model name

  # Per-level retrieval (L1=paradigm, L2=explore, L3=exploit)
  top_k:               {L1: 100, L2: 50, L3: 30}
  softmax_temperature: {L1: 5.0, L2: 1.5, L3: 0.5}
  query_llm_temperature: {L1: 1.2, L2: 0.9, L3: 0.3}

  # Sampling
  n_weighted_samples: 6
  n_random_samples: 1

  # Output
  output_mode: raw_text              # "raw_text" | "digest"
  max_tokens_per_sample: null        # null = no truncation
```

### Integration flags trong `AdaEvolveDatabaseConfig`

```yaml
search:
  type: adaevolve
  database:
    use_knowledge_evolve: true       # master toggle
    knowledge_use_parent: true       # inject khi stage = parent
    knowledge_use_paradigm: true     # inject khi stage = paradigm
```

---

## 8. Ingestion Pipeline

```python
from skydiscover.knowledge import KnowledgeEvolveConfig, create_embedder, ingest_jsonl

config = KnowledgeEvolveConfig(
    embedding_backend="gemini",
    chroma_persist_dir="./chroma_db",
)
embedder = create_embedder(config)

ingest_jsonl(
    jsonl_paths=["papers_batch1.jsonl", "papers_batch2.jsonl"],
    embedder=embedder,
    config=config,
)
```

- Upsert idempotent — chạy lại không tạo duplicate.
- Progress bar per file.
- Embedding model lúc ingest **phải giống** lúc query (được lưu trong collection metadata).

---

## 9. Integration với AdaEvolve

### Luồng trong controller

```
AdaEvolveController._generate_child()
    │
    ├── database.sample()          → parent, context_programs, sampling_mode
    │
    ├── [if knowledge_evolve]
    │   ├── stage = "paradigm" if paradigm else "parent"
    │   ├── check use_parent / use_paradigm flags
    │   └── context["knowledge"] = await knowledge_evolve.get_context(
    │           task_description = config.context_builder.system_message,
    │           current_best_score = ...,
    │           evaluator_feedback = parent.artifacts["feedback"],
    │           stage = stage,
    │           search_mode = sampling_mode,
    │           parent_code = parent.solution,
    │           parent_metrics = parent.metrics,
    │           failed_paradigms = database.get_previously_tried_ideas(),
    │       )
    │
    └── context_builder.build_prompt(parent_dict, context)
```

### Vị trí trong prompt (search_guidance sections)

```
1. Evaluator feedback       (diagnostics từ evaluator artifacts)
2. Paradigm breakthrough    (nếu stagnating)
3. Sibling context          (previous mutations của parent này)
4. Knowledge references     ← KnowledgeEvolve inject ở đây
5. Error retry context      (nếu đang retry)
```

---

## 10. Tích hợp vào module khác

KnowledgeEvolve chỉ cần:
```python
from skydiscover.knowledge import KnowledgeEvolve, KnowledgeEvolveConfig, create_embedder

ke = KnowledgeEvolve(config=ke_config, embedder=create_embedder(ke_config))
knowledge_str = await ke.get_context(
    task_description="...",
    stage="parent",           # hoặc "paradigm"
    search_mode="exploitation",
    parent_code="...",
    parent_metrics={...},
)
```

Để tích hợp vào OpenEvolve hay GEPA:
1. Thêm 3 flags vào config của algorithm đó (`use_knowledge_evolve`, `knowledge_use_parent`, `knowledge_use_paradigm`)
2. Khởi tạo `KnowledgeEvolve` trong controller tương ứng
3. Call `get_context()` và inject `context["knowledge"]` trước khi build prompt

---

## 11. Setup & Cài đặt

### Bước 1 — Cài dependencies

```bash
# Gemini embedding (recommended)
pip install skydiscover[knowledge]

# Hoặc cài thủ công
pip install chromadb google-generativeai numpy

# Nếu dùng HuggingFace embedding thay Gemini
pip install chromadb sentence-transformers numpy
```

### Bước 2 — Set API key

```bash
# Gemini (dùng cho cả embedding lẫn query generation)
export GEMINI_API_KEY="your-gemini-api-key"

# Hoặc nếu dùng OpenAI model cho query generation
export OPENAI_API_KEY="your-openai-api-key"
```

Có thể đặt trong `.env` file ở root project — SkyDiscover tự load qua `python-dotenv`.

### Bước 3 — Chuẩn bị JSONL data

Mỗi dòng trong file JSONL phải có cấu trúc:
```json
{"paper_path": "/path/to/paper.pdf", "summary_dict": {"summary": "...", "motivation_questions": "...", "all_solutions": "...", "all_results": "...", "contributions": "..."}}
```

### Bước 4 — Ingest papers vào ChromaDB

```bash
# Gemini embedding (default)
skydiscover-knowledge-ingest papers.jsonl

# Nhiều file cùng lúc
skydiscover-knowledge-ingest batch1.jsonl batch2.jsonl

# Chỉ định thư mục và collection
skydiscover-knowledge-ingest papers.jsonl \
    --chroma-dir ./my_chroma_db \
    --collection my_collection

# HuggingFace embedding
skydiscover-knowledge-ingest papers.jsonl \
    --embedding-backend huggingface \
    --hf-model BAAI/bge-small-en-v1.5

# Verbose để xem progress chi tiết
skydiscover-knowledge-ingest papers.jsonl -v
```

Tất cả options:
```
usage: skydiscover-knowledge-ingest FILE [FILE ...] [options]

  --chroma-dir DIR          ChromaDB persist directory (default: ./chroma_db)
  --collection NAME         Collection name (default: knowledge_base)
  --embedding-backend       gemini | huggingface (default: gemini)
  --gemini-model MODEL      Gemini embedding model (default: models/text-embedding-004)
  --hf-model MODEL          HuggingFace model (default: BAAI/bge-small-en-v1.5)
  --hf-device DEVICE        cpu | cuda (default: cpu)
  --api-key KEY             API key (fallback: GEMINI_API_KEY env var)
  -v, --verbose             Verbose logging
```

Chạy một lần duy nhất — upsert idempotent, chạy lại không tạo duplicate.

### Bước 5 — Bật trong YAML config của AdaEvolve

Thêm vào file YAML config đang dùng:

```yaml
# Bật KnowledgeEvolve trong AdaEvolve
search:
  type: adaevolve
  database:
    use_knowledge_evolve: true
    knowledge_use_parent: true        # inject khi sinh từ parent
    knowledge_use_paradigm: true      # inject khi paradigm đang active

# Config của module KnowledgeEvolve
knowledge:
  embedding_backend: gemini
  chroma_persist_dir: ./chroma_db     # phải trỏ đúng thư mục đã ingest ở bước 4
  query_model_name: gemini-2.0-flash
  output_mode: raw_text               # hoặc "digest" để dùng LLM compress
```

### Bước 6 — Chạy AdaEvolve như bình thường

```bash
skydiscover-run --config your_config.yaml
```

KnowledgeEvolve tự động khởi tạo và inject knowledge vào mỗi iteration.
Log sẽ hiển thị:
```
KnowledgeEvolve enabled (parent=True, paradigm=True, mode=raw_text)
```

---

## 12. Troubleshooting

**`GEMINI_API_KEY` không được nhận:**
```bash
# Kiểm tra env var đã set chưa
echo $GEMINI_API_KEY
# Hoặc set trực tiếp trong config
knowledge:
  query_api_key: "your-key-here"
```

**ChromaDB collection rỗng (retrieval luôn trả về empty):**
```python
import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection("knowledge_base")
print(col.count())   # phải > 0
```
Nếu = 0 thì cần chạy lại bước ingest.

**Embedding model mismatch (query không khớp với index):**
Đảm bảo `embedding_backend` và model name trong config lúc ingest và lúc chạy **giống nhau**.
ChromaDB lưu `embedding_backend` trong collection metadata để detect mismatch.

**`ImportError: chromadb`:**
```bash
pip install chromadb
```

**`ImportError: google.generativeai`:**
```bash
pip install google-generativeai
```

---

## 13. Dependencies

```bash
pip install skydiscover[knowledge]
```

| Package | Dùng cho |
|---|---|
| `chromadb>=0.4.0` | Vector database |
| `google-generativeai>=0.8.0` | Gemini embedding backend |
| `sentence-transformers>=2.2.0` | HuggingFace embedding backend |
| `numpy>=1.22.0` | Softmax sampling |

**Env vars:**
| Var | Dùng khi |
|---|---|
| `GEMINI_API_KEY` hoặc `GOOGLE_API_KEY` | Gemini embedding + query LLM |
| `OPENAI_API_KEY` | Query LLM là gpt-* |
| HuggingFace không cần env var | Model download tự động từ HF Hub |
