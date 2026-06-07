#!/usr/bin/env bash
# Verify ChromaDB collection: count docs, field coverage, sample titles.
# Usage: ./scripts/knowledge/verify.sh

set -euo pipefail

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CHROMA_DIR="./chroma_db"
COLLECTION="knowledge_base"
# ──────────────────────────────────────────────────────────────────────────────

uv run python - <<EOF
import sys

try:
    import chromadb
except ImportError:
    print("ERROR: chromadb not installed. Run: pip install chromadb")
    sys.exit(1)

client = chromadb.PersistentClient(path="$CHROMA_DIR")

try:
    col = client.get_collection("$COLLECTION")
except Exception:
    print(f"ERROR: Collection '$COLLECTION' not found at '$CHROMA_DIR'.")
    print("       Run ingest.sh first.")
    sys.exit(1)

count = col.count()
print(f"==> Collection : $COLLECTION")
print(f"    Directory  : $CHROMA_DIR")
print(f"    Total docs : {count}")

if count == 0:
    print("\nWARNING: Collection is empty — run ingest.sh first.")
    sys.exit(1)

results = col.get(limit=min(count, 5000), include=["metadatas"])
from collections import Counter
field_counts = Counter(m["field_type"] for m in results["metadatas"])
paper_ids    = {m["paper_id"] for m in results["metadatas"]}

print(f"    Unique papers : {len(paper_ids)}")
print(f"\n==> Field coverage (sampled {len(results['ids'])} docs):")
for field, n in sorted(field_counts.items()):
    print(f"    {field:<25} {n} docs")

titles = list({m.get("title", "?") for m in results["metadatas"]})[:5]
print(f"\n==> Sample paper titles:")
for t in titles:
    print(f"    - {t}")

print("\nOK: Collection looks healthy.")
EOF
