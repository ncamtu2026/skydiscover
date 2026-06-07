#!/usr/bin/env bash
# Delete the ChromaDB collection so it can be re-ingested from scratch.
# Usage: ./scripts/knowledge/reset_db.sh

set -euo pipefail

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CHROMA_DIR="./chroma_db"
COLLECTION="knowledge_base"
# ──────────────────────────────────────────────────────────────────────────────

echo "WARNING: This will delete collection '$COLLECTION' at '$CHROMA_DIR'."
read -r -p "Are you sure? [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted."
    exit 0
fi

uv run python - <<EOF
import sys
try:
    import chromadb
except ImportError:
    print("ERROR: chromadb not installed.")
    sys.exit(1)

client = chromadb.PersistentClient(path="$CHROMA_DIR")
try:
    client.delete_collection("$COLLECTION")
    print(f"Deleted collection '$COLLECTION'.")
except Exception as e:
    print(f"Nothing to delete: {e}")
EOF
