"""
CLI for KnowledgeEvolve ingestion.

Usage:
    skydiscover-knowledge-ingest papers.jsonl [papers2.jsonl ...] [options]
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="skydiscover-knowledge-ingest",
        description="Ingest JSONL paper summaries into the KnowledgeEvolve ChromaDB.",
    )
    parser.add_argument(
        "jsonl_files",
        nargs="+",
        metavar="FILE",
        help="One or more JSONL files to ingest.",
    )
    parser.add_argument(
        "--chroma-dir",
        default="./chroma_db",
        help="ChromaDB persist directory (default: ./chroma_db).",
    )
    parser.add_argument(
        "--collection",
        default="knowledge_base",
        help="ChromaDB collection name (default: knowledge_base).",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["gemini", "huggingface", "openai"],
        default="gemini",
        help="Embedding backend (default: gemini).",
    )
    parser.add_argument(
        "--gemini-model",
        default="models/text-embedding-004",
        help="Gemini embedding model (default: models/text-embedding-004).",
    )
    parser.add_argument(
        "--hf-model",
        default="BAAI/bge-small-en-v1.5",
        help="HuggingFace embedding model (default: BAAI/bge-small-en-v1.5).",
    )
    parser.add_argument(
        "--hf-device",
        default="cpu",
        help="Device for HuggingFace model (default: cpu).",
    )
    parser.add_argument(
        "--openai-model",
        default="text-embedding-3-small",
        help="OpenAI embedding model (default: text-embedding-3-small).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Gemini/OpenAI API key. Falls back to GEMINI_API_KEY env var.",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory to write error log (default: same dir as first JSONL file).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Build config
    from skydiscover.knowledge.config import KnowledgeEvolveConfig
    from skydiscover.knowledge.embedder import create_embedder
    from skydiscover.knowledge.ingest import ingest_jsonl

    import os
    if args.api_key:
        os.environ["GEMINI_API_KEY"] = args.api_key

    config = KnowledgeEvolveConfig(
        embedding_backend=args.embedding_backend,
        gemini_embedding_model=args.gemini_model,
        huggingface_embedding_model=args.hf_model,
        huggingface_device=args.hf_device,
        openai_embedding_model=args.openai_model,
        chroma_persist_dir=args.chroma_dir,
        collection_name=args.collection,
    )

    try:
        embedder = create_embedder(config)
    except (ImportError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    total = ingest_jsonl(
        jsonl_paths=args.jsonl_files,
        embedder=embedder,
        config=config,
        log_dir=args.log_dir,
    )
    print(f"\nDone. {total} documents upserted into '{args.collection}' at '{args.chroma_dir}'.")


if __name__ == "__main__":
    main()
