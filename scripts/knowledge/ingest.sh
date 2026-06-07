#!/usr/bin/env bash
# Ingest JSONL paper summaries into ChromaDB.
# Usage: ./scripts/knowledge/ingest.sh

set -euo pipefail

# ─── CONFIG ───────────────────────────────────────────────────────────────────
JSONL_FILES=(
    "skydiscover/knowledge/data/summary_osdi.jsonl"
    "skydiscover/knowledge/data/summary_sosp.jsonl"
)

CHROMA_DIR="./chroma_db"
COLLECTION="knowledge_base"
BACKEND="openai"               # gemini | huggingface | openai
VERBOSE=true                   # true | false
LOG_DIR="$(dirname "$0")"      # error log is written next to this script

# Gemini
# export GEMINI_API_KEY="your-gemini-api-key"

# OpenAI
# export OPENAI_API_KEY="your-openai-api-key"
# ──────────────────────────────────────────────────────────────────────────────

VERBOSE_FLAG=""
if [[ "$VERBOSE" == "true" ]]; then
    VERBOSE_FLAG="--verbose"
fi

echo "==> Ingesting into ChromaDB"
echo "    chroma-dir : $CHROMA_DIR"
echo "    collection : $COLLECTION"
echo "    backend    : $BACKEND"
echo "    files      : ${JSONL_FILES[*]}"
echo ""

uv run python -m skydiscover.knowledge.cli "${JSONL_FILES[@]}" \
    --chroma-dir "$CHROMA_DIR" \
    --collection "$COLLECTION" \
    --embedding-backend "$BACKEND" \
    --log-dir "$LOG_DIR" \
    $VERBOSE_FLAG
