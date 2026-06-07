# KnowledgeEvolve — Architecture & Usage

## 1. Overview

KnowledgeEvolve is a **standalone** RAG (Retrieval-Augmented Generation) module that provides
knowledge from academic papers as supplementary context for the solution generation process of
search algorithms (AdaEvolve, and other modules in the future).

**Core idea**: At each iteration, instead of the LLM relying solely on its pre-training memory,
KnowledgeEvolve retrieves relevant paper excerpts and injects them into the prompt — like handing
the LLM a stack of domain-specific documents at the moment of solution generation.

```
paper corpus (JSONL)
        ↓ ingest
   ChromaDB (vectors)
        ↓ retrieve (each iteration)
  7 relevant excerpts
        ↓ format/digest
  knowledge context string
        ↓ inject
   LLM optimization prompt
```

---

## 2. Module Structure

```
skydiscover/knowledge/
├── __init__.py           ← public exports
├── config.py             ← KnowledgeEvolveConfig (standalone dataclass)
├── embedder.py           ← Gemini / HuggingFace embedding backends
├── ingest.py             ← JSONL → ChromaDB pipeline
├── retriever.py          ← query gen + ChromaDB search + sampling
└── knowledge_evolve.py   ← main class, 2 output modes
```

The module **does not import anything from AdaEvolve** — fully independent.
Integration flags (`use_knowledge_evolve`, `knowledge_use_parent`, `knowledge_use_paradigm`)
live in each search algorithm's config, not in KnowledgeEvolveConfig.

---

## 3. Data Schema

### Input JSONL (one line per paper)
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
Single collection (`knowledge_base`), each document = 1 field of 1 paper:

```
id:       "{paper_id_12chars}_{field_type}"
document: content of that field
metadata:
  paper_id:    "abc123def456"
  paper_path:  "/path/to/paper.pdf"
  field_type:  "all_solutions"         ← filter on query
  title:       "Paper title"
  summary:     "..."                   ← remaining fields (returned as full context)
  motivation_questions: "..."
  all_results: "..."
  contributions: "..."
```

---

## 4. Three Search Levels (L1 / L2 / L3)

The entire pipeline — query tone, LLM temperature, top_k, sampling temperature — scales
across 3 levels determined by `(stage, search_mode)`:

| Level | When | Query tone | LLM temp | top_k | Softmax temp |
|---|---|---|---|---|---|
| **L1** | `stage == paradigm` | Abstract, task-level. No reference to current solution. Includes failed paradigm history. | 1.2 (creative) | 100 | 5.0 (≈ uniform) |
| **L2** | `stage == parent` + `mode ∈ {exploration, balanced, None}` | Loose parent tie. Directed toward diverse / novel methods. | 0.9 (balanced) | 50 | 1.5 (moderate) |
| **L3** | `stage == parent` + `mode == exploitation` | Specific: includes parent metrics + bottleneck. Targeted optimizations. | 0.3 (focused) | 30 | 0.5 (sharp) |

**Why softmax temperature instead of two separate distributions:**
```
high temperature → flat distribution near uniform   → diversity
low temperature  → winner-takes-most                → precision
```

---

## 5. Per-Iteration Pipeline

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
Injects excerpts directly into the prompt:
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
Adds 1 LLM call to compress 7 samples into 3-5 actionable bullet points:
```
## KNOWLEDGE INSIGHTS

• From [Paper X]: technique Y showed Z% improvement by doing ...
• Consider approach A (seen in papers X, Y) which directly addresses ...
• [Paper Z] reports that strategy B outperforms baseline by ...
```

`digest` has better signal-to-noise but costs 1 extra LLM call per iteration.

---

## 7. Configuration

### `KnowledgeEvolveConfig` (under `Config.knowledge`)

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
  # Auto-detects Gemini endpoint if model name starts with "gemini-"
  query_model_name: gemini-2.0-flash
  query_api_key: null                # fallback: GEMINI_API_KEY / OPENAI_API_KEY env
  query_api_base: null               # fallback: auto-detect from model name

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

### Integration flags in `AdaEvolveDatabaseConfig`

```yaml
search:
  type: adaevolve
  database:
    use_knowledge_evolve: true       # master toggle
    knowledge_use_parent: true       # inject when stage = parent
    knowledge_use_paradigm: true     # inject when stage = paradigm
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

- Upsert is idempotent — re-running does not create duplicates.
- Progress bar per file.
- The embedding model used during ingest **must match** the one used at query time (stored in collection metadata).

---

## 9. Integration with AdaEvolve

### Flow in the controller

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

### Position in the prompt (search_guidance sections)

```
1. Evaluator feedback       (diagnostics from evaluator artifacts)
2. Paradigm breakthrough    (if stagnating)
3. Sibling context          (previous mutations of this parent)
4. Knowledge references     ← KnowledgeEvolve injects here
5. Error retry context      (if retrying)
```

---

## 10. Integration with Other Modules

KnowledgeEvolve only requires:
```python
from skydiscover.knowledge import KnowledgeEvolve, KnowledgeEvolveConfig, create_embedder

ke = KnowledgeEvolve(config=ke_config, embedder=create_embedder(ke_config))
knowledge_str = await ke.get_context(
    task_description="...",
    stage="parent",           # or "paradigm"
    search_mode="exploitation",
    parent_code="...",
    parent_metrics={...},
)
```

To integrate into OpenEvolve or GEPA:
1. Add 3 flags to that algorithm's config (`use_knowledge_evolve`, `knowledge_use_parent`, `knowledge_use_paradigm`)
2. Initialise `KnowledgeEvolve` in the corresponding controller
3. Call `get_context()` and inject `context["knowledge"]` before building the prompt

---

## 11. Setup & Installation

### Step 1 — Install dependencies

```bash
# Gemini embedding (recommended)
pip install skydiscover[knowledge]

# Or install manually
pip install chromadb google-generativeai numpy

# If using HuggingFace embedding instead of Gemini
pip install chromadb sentence-transformers numpy
```

### Step 2 — Set API key

```bash
# Gemini (used for both embedding and query generation)
export GEMINI_API_KEY="your-gemini-api-key"

# Or if using OpenAI model for query generation
export OPENAI_API_KEY="your-openai-api-key"
```

Can be placed in a `.env` file at the project root — SkyDiscover auto-loads it via `python-dotenv`.

### Step 3 — Prepare JSONL data

Each line in the JSONL file must have this structure:
```json
{"paper_path": "/path/to/paper.pdf", "summary_dict": {"summary": "...", "motivation_questions": "...", "all_solutions": "...", "all_results": "...", "contributions": "..."}}
```

### Step 4 — Ingest papers into ChromaDB

```bash
# Gemini embedding (default)
skydiscover-knowledge-ingest papers.jsonl

# Multiple files at once
skydiscover-knowledge-ingest batch1.jsonl batch2.jsonl

# Specify directory and collection
skydiscover-knowledge-ingest papers.jsonl \
    --chroma-dir ./my_chroma_db \
    --collection my_collection

# HuggingFace embedding
skydiscover-knowledge-ingest papers.jsonl \
    --embedding-backend huggingface \
    --hf-model BAAI/bge-small-en-v1.5

# Verbose to see detailed progress
skydiscover-knowledge-ingest papers.jsonl -v
```

All options:
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

Run once only — upsert is idempotent, re-running does not create duplicates.

### Step 5 — Enable in AdaEvolve YAML config

Add to the YAML config file in use:

```yaml
# Enable KnowledgeEvolve in AdaEvolve
search:
  type: adaevolve
  database:
    use_knowledge_evolve: true
    knowledge_use_parent: true        # inject when generating from parent
    knowledge_use_paradigm: true      # inject when paradigm is active

# KnowledgeEvolve module config
knowledge:
  embedding_backend: gemini
  chroma_persist_dir: ./chroma_db     # must point to the directory ingested in step 4
  query_model_name: gemini-2.0-flash
  output_mode: raw_text               # or "digest" to use LLM compression
```

### Step 6 — Run AdaEvolve as normal

```bash
skydiscover-run --config your_config.yaml
```

KnowledgeEvolve initialises automatically and injects knowledge at each iteration.
The log will display:
```
KnowledgeEvolve enabled (parent=True, paradigm=True, mode=raw_text)
```

---

## 12. Troubleshooting

**`GEMINI_API_KEY` not recognised:**
```bash
# Check if env var is set
echo $GEMINI_API_KEY
# Or set directly in config
knowledge:
  query_api_key: "your-key-here"
```

**ChromaDB collection empty (retrieval always returns empty):**
```python
import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection("knowledge_base")
print(col.count())   # must be > 0
```
If = 0, re-run the ingest step.

**Embedding model mismatch (queries don't match the index):**
Ensure `embedding_backend` and model name in config are **identical** between ingest time and run time.
ChromaDB stores `embedding_backend` in collection metadata to detect mismatches.

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

| Package | Used for |
|---|---|
| `chromadb>=0.4.0` | Vector database |
| `google-generativeai>=0.8.0` | Gemini embedding backend |
| `sentence-transformers>=2.2.0` | HuggingFace embedding backend |
| `numpy>=1.22.0` | Softmax sampling |

**Env vars:**
| Var | When used |
|---|---|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini embedding + query LLM |
| `OPENAI_API_KEY` | Query LLM is gpt-* |
| `OPENAI_EMBEDDING_KEY` | OpenAI embedding when OPENAI_API_KEY is already used for another LLM |
| HuggingFace — no env var needed | Model downloaded automatically from HF Hub |

---

## 14. Implementation Status (updated 2026-06-07)

### Deviations from original design

**LLMPool integration:**
- `knowledge_evolve.py` and `retriever.py` now use `LLMPool` (the controller's `guide_llms`) instead of a raw openai client.
- `KnowledgeEvolve.__init__` accepts an additional `llm_pool: LLMPool` argument.
- Query generation and digest calls use `llm_pool.generate(..., reasoning_effort=None, max_tokens=1200)` — thinking tokens are disabled because output is short JSON; the original 400-token limit caused truncation with reasoning models.

**OPENAI_EMBEDDING_KEY:**
- Dedicated env var `OPENAI_EMBEDDING_KEY` for the OpenAI embedding backend, needed when `OPENAI_API_KEY` is already used for a different LLM (e.g. glm-4.7 via the int2.net proxy).
- Resolution order: `config.openai_embedding_api_key` → `OPENAI_EMBEDDING_KEY` → `OPENAI_API_KEY`.

**top_k values:**
- Changed from `{L1: 100, L2: 50, L3: 30}` to `{L1: 20, L2: 10, L3: 5}` to match actual collection size.

**Circular import fix:**
- `KnowledgeEvolve` removed from `knowledge/__init__.py`.
- Root cause: `__init__` → `knowledge_evolve` → `retriever` → `LLMPool` → `config.py` → `knowledge/__init__` (cycle).
- Fix: controller imports directly via `from skydiscover.knowledge.knowledge_evolve import KnowledgeEvolve`.

**Retriever state logging:**
- `last_queries`, `last_field_results`, `last_random_samples` stored on the `Retriever` instance after each `retrieve()` call.
- Controller reads these to write the `knowledge_retrieve` field into the iteration stats JSONL.

**Query generation token budget:**
- Old: `max_tokens=400` caused JSON truncation when a reasoning model used thinking tokens first.
- Fix: `max_tokens=1200`, `reasoning_effort=None` for both query generation and digest calls.

---

## 15. Attribution System

### Goal
When an LLM generates a solution from a prompt that includes paper excerpts, record which papers (if any) motivated that solution and what specifically was leveraged.

### Three attribution sources

| Source | Level | Mechanism | Metadata key |
|---|---|---|---|
| **Paradigm LLM** | L1 | `"attribution"` field in the JSON schema output of the paradigm generator | `paradigm_attribution` |
| **Code LLM — inline** | L2/L3 | LLM appends `# KNOWLEDGE_ATTRIBUTION: ...` at the end of the code; controller extracts and strips it before parsing | `knowledge_attribution` |
| **Guide LLM — post_eval** | L2/L3 | After code is parsed, a separate guide LLM call receives the solution + paper list and returns attribution text | `knowledge_attribution` |

### Config

```yaml
knowledge:
  attribution_mode: inline    # "inline" (default) | "post_eval"
```

- **`inline`**: Code LLM self-reports. The knowledge context prompt gains an `## ATTRIBUTION REQUIRED` section instructing the model to append `# KNOWLEDGE_ATTRIBUTION: ...` at the end of its code block. The controller extracts and strips this comment before diff/rewrite parsing.
- **`post_eval`**: Code generation prompt is unchanged. After `child_solution` is parsed, `knowledge_evolve.evaluate_attribution(solution, results)` is called — the guide LLM receives the solution (first 3000 chars) plus the paper list and returns attribution text.

### Design notes
- `attribution_mode` only affects L2/L3. L1 always uses JSON attribution from the paradigm generator, regardless of this setting.
- `knowledge_attribution` and `paradigm_attribution` never overlap: parent-stage programs have the former, paradigm-stage programs have the latter.
- Web analysis prefers `knowledge_attribution`, falls back to `paradigm_attribution` if absent.

---

## 16. Iteration Stats Logging

`adaevolve_iteration_stats_*.jsonl` gains a `knowledge_retrieve` field per iteration:

```json
{
  "iteration": 3,
  "knowledge_retrieve": {
    "stage": "parent",
    "level": "L3",
    "n_results": 7,
    "queries": {
      "summary": "multi-cloud broadcast cost minimization...",
      "all_solutions": "..."
    },
    "weighted_samples": [
      {"title": "DeDe: ...", "paper_path": "...", "field_type": "motivation_questions", "similarity": 0.44}
    ],
    "random_samples": [
      {"title": "Wukong: ...", "paper_path": "...", "field_type": "contributions", "similarity": 0.5}
    ]
  }
}
```

---

## 17. Modified files in skydiscover / AdaEvolve

### Knowledge module (new)
| File | Changes |
|---|---|
| `skydiscover/knowledge/config.py` | Added `openai_embedding_api_key`, `openai_embedding_api_base`, `attribution_mode`; top_k = {L1:20, L2:10, L3:5} |
| `skydiscover/knowledge/embedder.py` | Added OpenAI backend; reads `OPENAI_EMBEDDING_KEY` |
| `skydiscover/knowledge/knowledge_evolve.py` | Uses LLMPool instead of raw client; added `_ATTRIBUTION_SYSTEM/USER`, `evaluate_attribution()`; `_format_raw()` appends inline attribution instruction when `attribution_mode == "inline"` |
| `skydiscover/knowledge/retriever.py` | Uses LLMPool; stores `last_queries/last_field_results/last_random_samples`; max_tokens=1200, reasoning_effort=None for query generation |
| `skydiscover/knowledge/__init__.py` | Removed `KnowledgeEvolve` export (circular import fix) |

### AdaEvolve controller
| File | Changes |
|---|---|
| `skydiscover/search/adaevolve/controller.py` | Initialises `KnowledgeEvolve(ke_config, embedder, self.guide_llms)`; calls `get_context()` for parent stage; extracts `# KNOWLEDGE_ATTRIBUTION` from raw LLM response before code parsing; runs post_eval attribution via `evaluate_attribution()`; stores `knowledge_attribution` in `child_metadata`; writes `knowledge_retrieve` to iteration stats |
| `skydiscover/search/adaevolve/paradigm/generator.py` | Added `knowledge_context` param to `generate()` and `_build_prompt()`; added `attribution` field to JSON schema; added attribution instruction to the knowledge context injection block; updated output format example |

### Context builder
| File | Changes |
|---|---|
| `skydiscover/context_builder/adaevolve/builder.py` | Section 4 in `_build_search_guidance`: reads `context["knowledge"]` and appends it to the prompt sections |

### Core config
| File | Changes |
|---|---|
| `skydiscover/config.py` | `AdaEvolveDatabaseConfig`: added `use_knowledge_evolve`, `knowledge_use_parent`, `knowledge_use_paradigm`; `Config`: added `knowledge: KnowledgeEvolveConfig` |

### Web analysis
| File | Changes |
|---|---|
| `analysis/web_analysis/app.py` | `/api/programs` includes `artifacts`; new `/api/iteration-stats` endpoint |
| `analysis/web_analysis/index.html` | "Info" tab in program detail: Metadata, Paper Attribution (`knowledge_attribution` + `paradigm_attribution`), Evaluator Feedback, Knowledge Retrieved (weighted + random samples + collapsible per-field queries) |

### Benchmark config
| File | Changes |
|---|---|
| `benchmarks/ADRS/cloudcast/config.yaml` | Added `guide_models`, `search.type: adaevolve`, `search.database` knowledge flags, `knowledge:` section, `timeout: 400`, `retries: 2`, `retry_delay: 0` |

---

## 18. Backlog

### B1 — Prompt parity when KnowledgeEvolve is disabled
**Description:** Not yet verified that setting `use_knowledge_evolve: false` produces a prompt identical to vanilla AdaEvolve (no KnowledgeEvolve).  
**Risk:** Possible side effects in the context builder or controller when the KnowledgeEvolve object is initialised but not used.  
**How to check:** Diff the logged prompts between a run with `use_knowledge_evolve: false` and a vanilla AdaEvolve run.

### B2 — Prompt parity with `attribution_mode: post_eval`
**Description:** When using `post_eval`, the prompt sent to the code-generating LLM should be identical to vanilla AdaEvolve (no `## ATTRIBUTION REQUIRED` section). Not yet verified in practice.  
**How to check:** Log and inspect the prompt text with `attribution_mode: post_eval` vs vanilla AdaEvolve.

### B3 — Impact of `inline` mode on LLM generation behaviour
**Description:** `attribution_mode: inline` adds a `## ATTRIBUTION REQUIRED` section at the end of the knowledge context in the prompt. Unknown whether this instruction affects the quality or style of the generated code (the LLM may be distracted by the extra requirement, or there may be measurable score differences).  
**How to check:** Compare code quality / scores between `inline` and `post_eval` runs on the same benchmark.

---

## 19. Open Design Questions

- **When to inject knowledge.** Currently injected every iteration for L2/L3 (parent stage) and at every paradigm generation (L1). This may add noise — papers retrieved at L2/L3 can be loosely relevant and dilute the prompt. Worth considering: inject only at L1 (paradigm stage), where the LLM is explicitly searching for new directions. L2/L3 code generation may benefit more from a clean, focused prompt than from potentially off-topic excerpts.

- **Retaining knowledge that showed improvement.** No mechanism yet to track which retrieved papers (or which queries) were associated with score improvements. A useful future feature: if a child that cited paper X improves over its parent, record that signal and up-weight paper X in future sampling (or pin it for the next few iterations).

- **Knowledge only at paradigm stage.** The argument for limiting injection to L1: paradigm generation is the natural moment to seek novel directions from literature. At L2/L3 the model is refining existing code — adding unrelated paper content may hurt rather than help. Consider making `knowledge_use_parent: false` the recommended default and only enabling it experimentally.

- **Adaptive / dynamic retrieval trigger.** Instead of retrieving knowledge every iteration, decide dynamically based on search signals — similar to how paradigm generation only fires on stagnation. Possible signals: improvement rate drops below a threshold, score plateau detected over a window, current sampling mode switches to exploration, or a minimum number of iterations since the last retrieval has passed. This avoids injecting knowledge when the search is already converging well (where the extra context is noise), and focuses retrieval on moments where new directions are actually needed. Could be implemented as a `knowledge_trigger` policy: `always` (current), `on_stagnation`, `on_exploration`, or a composite condition.
