"""Freeze the locally built RAG index as the Canonical evaluation snapshot.

Run this only after reviewing and executing ``build_kb_index``. The command does
not call a model service; it hashes local knowledge files and the existing index.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config.settings import settings  # noqa: E402
from app.evaluation.state import knowledge_hash, project_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze Canonical RAG snapshot")
    parser.add_argument(
        "--snapshot-id", default="knowledge-v1",
        help="Versioned identifier stored in traces",
    )
    args = parser.parse_args()

    index_path = project_path(settings.kb_index_path)
    if not index_path.exists():
        parser.error(
            f"RAG index is missing: {index_path}. Review data egress, then run "
            "`python -m app.scripts.build_kb_index --backend numpy` first."
        )

    target = project_path(settings.eval_rag_snapshot_path)
    payload = {
        "snapshot_id": args.snapshot_id,
        "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rag_backend": settings.rag_backend,
        "embedding_model": settings.embedding_model,
        "knowledge_dir": settings.kb_dir,
        "index_path": settings.kb_index_path,
        "index_present": True,
        "sha256": knowledge_hash(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Frozen RAG snapshot {args.snapshot_id}: {target}")


if __name__ == "__main__":
    main()
