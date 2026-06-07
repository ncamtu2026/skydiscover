"""
Ingestion pipeline: JSONL → ChromaDB.

Each JSONL line:
    {"paper_path": "...", "summary_dict": {"summary": "...", "all_solutions": "...", ...}}

Each content field of each paper becomes one ChromaDB document.
Other fields are stored in metadata so retrieval returns the full paper context.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from tqdm import tqdm

from skydiscover.knowledge.config import KnowledgeEvolveConfig
from skydiscover.knowledge.embedder import BaseEmbedder

logger = logging.getLogger(__name__)


def _extract_title(summary: Optional[str]) -> str:
    if not summary:
        return "Unknown"
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip()[:200]
        if line:
            return line[:200]
    return "Unknown"


def _paper_id(paper_path: str) -> str:
    return hashlib.md5(paper_path.encode()).hexdigest()[:12]


def ingest_jsonl(
    jsonl_paths: Union[str, Path, List[Union[str, Path]]],
    embedder: BaseEmbedder,
    config: KnowledgeEvolveConfig,
    log_dir: Optional[Union[str, Path]] = None,
) -> int:
    """
    Ingest one or more JSONL files into ChromaDB.

    Errors are skipped and written to a .log file in log_dir
    (defaults to the directory of the first JSONL file).

    Returns:
        Total number of documents upserted.
    """
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb is required. Install with: pip install chromadb")

    if isinstance(jsonl_paths, (str, Path)):
        jsonl_paths = [jsonl_paths]
    jsonl_paths = [Path(p) for p in jsonl_paths]

    # Error log file
    if log_dir is None:
        log_dir = jsonl_paths[0].parent
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_log_path = log_dir / f"ingest_errors_{timestamp}.log"
    error_log = open(error_log_path, "w", encoding="utf-8")

    client = chromadb.PersistentClient(path=str(config.chroma_persist_dir))
    collection = client.get_or_create_collection(
        name=config.collection_name,
        metadata={
            "hnsw:space": "cosine",
            "embedding_backend": config.embedding_backend,
        },
    )

    total = 0
    total_errors = 0

    for path in jsonl_paths:
        logger.info(f"Ingesting {path}")
        with open(path) as f:
            lines = [l for l in f if l.strip()]

        file_errors = 0
        for line_num, line in enumerate(tqdm(lines, desc=path.name), start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                _log_error(error_log, path, line_num, f"JSON parse error: {e}", raw=line)
                file_errors += 1
                continue

            try:
                paper_path = record.get("paper_path", "")
                summary_dict = record.get("summary_dict", {})
                if not isinstance(summary_dict, dict):
                    raise ValueError(f"summary_dict is {type(summary_dict).__name__}, expected dict")

                pid = _paper_id(paper_path)
                title = _extract_title(summary_dict.get("summary"))

                for field_name in config.content_fields:
                    content = summary_dict.get(field_name)
                    if not content:
                        continue

                    doc_id = f"{pid}_{field_name}"
                    embedding = embedder.embed([content], task_type="document")[0]

                    metadata: dict = {
                        "paper_id": pid,
                        "paper_path": paper_path,
                        "field_type": field_name,
                        "title": title,
                    }
                    for other_field in config.content_fields:
                        if other_field != field_name:
                            metadata[other_field] = summary_dict.get(other_field) or ""

                    collection.upsert(
                        ids=[doc_id],
                        embeddings=[embedding],
                        documents=[content],
                        metadatas=[metadata],
                    )
                    total += 1

            except Exception as e:
                _log_error(error_log, path, line_num, str(e), record=record)
                file_errors += 1
                continue

        if file_errors:
            tqdm.write(f"  {path.name}: {file_errors} errors — see {error_log_path.name}")
        total_errors += file_errors

    error_log.close()

    summary = (
        f"Ingested {total} documents into '{config.collection_name}' "
        f"at '{config.chroma_persist_dir}'. "
        f"Errors: {total_errors}."
    )
    logger.info(summary)
    print(f"\n{summary}")
    if total_errors:
        print(f"Error log: {error_log_path}")
    else:
        error_log_path.unlink(missing_ok=True)  # clean up empty log

    return total


def _log_error(
    log_file,
    path: Path,
    line_num: int,
    error: str,
    raw: str = "",
    record: Optional[dict] = None,
) -> None:
    log_file.write(f"{'='*60}\n")
    log_file.write(f"File    : {path}\n")
    log_file.write(f"Line    : {line_num}\n")
    log_file.write(f"Error   : {error}\n")
    if raw:
        log_file.write(f"Raw     : {raw[:300]}\n")
    if record is not None:
        log_file.write(f"Record  :\n{json.dumps(record, indent=2, ensure_ascii=False)[:1000]}\n")
    log_file.write("\n")
    log_file.flush()
