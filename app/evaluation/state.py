"""Evaluation-only SQLite setup, state snapshots and RAG snapshot checks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.store import SQLiteStore
from app.config.settings import settings


ALLOWED_FIELDS = {
    "orders": {
        "order_id", "user_id", "status", "items_json", "shipping_address",
        "total_amount", "tracking_number", "carrier", "logistics_status",
        "logistics_events_json", "estimated_delivery", "delivered_at", "created_at",
    },
    "products": {
        "product_id", "name", "category", "price", "stock", "description",
        "specs_json", "is_refundable",
    },
    "refunds": {"refund_id", "order_id", "reason", "status", "created_at"},
}
PRIMARY_KEYS = {"orders": "order_id", "products": "product_id", "refunds": "refund_id"}
ALLOWED_OPS = {"eq", "count_eq"}
REGISTERED_SEEDS = {"demo-v1"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_case_store(
    seed_id: str = "demo-v1",
    initial_state_patch: dict[str, Any] | None = None,
) -> SQLiteStore:
    """Create one isolated, deterministic SQLite store for one Eval Case."""

    if seed_id not in REGISTERED_SEEDS:
        raise ValueError(f"未注册 seed_id: {seed_id}")
    store = SQLiteStore.in_memory(
        seed=True,
        now=lambda: datetime(2026, 1, 1, 0, 0, 0),
    )
    if initial_state_patch:
        apply_initial_patch(store, initial_state_patch)
    return store


def apply_initial_patch(store: SQLiteStore, patch: dict[str, Any]) -> None:
    """Apply allow-listed ``{table: {primary_key: {field: value}}}`` updates."""

    for table, records in patch.items():
        if table not in ALLOWED_FIELDS or not isinstance(records, dict):
            raise ValueError(f"initial_state_patch 包含非法表或结构: {table}")
        primary_key = PRIMARY_KEYS[table]
        for record_id, fields in records.items():
            if not isinstance(fields, dict) or not fields:
                raise ValueError(f"{table}.{record_id} patch 不能为空")
            illegal = set(fields) - ALLOWED_FIELDS[table]
            if illegal or primary_key in fields:
                raise ValueError(
                    f"非法 patch 字段: {sorted(illegal | ({primary_key} & set(fields)))}"
                )
            assignments = ", ".join(f"{field} = ?" for field in fields)
            values = [
                json.dumps(value, ensure_ascii=False)
                if field.endswith("_json") and isinstance(value, (dict, list))
                else value
                for field, value in fields.items()
            ]
            cursor = store.conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {primary_key} = ?",
                [*values, record_id],
            )
            if cursor.rowcount != 1:
                raise ValueError(f"patch 目标不存在: {table}.{record_id}")
    store.conn.commit()


def snapshot_store(store: SQLiteStore) -> dict[str, list[dict[str, Any]]]:
    """Read a complete deterministic snapshot; RunTrace owns the returned data."""

    return {
        table: [
            dict(row)
            for row in store.conn.execute(
                f"SELECT * FROM {table} ORDER BY {PRIMARY_KEYS[table]}"
            ).fetchall()
        ]
        for table in ALLOWED_FIELDS
    }


def project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def knowledge_manifest() -> dict:
    path = project_path(settings.eval_rag_snapshot_path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def knowledge_hash() -> str:
    digest = hashlib.sha256()
    root = project_path(settings.kb_dir)
    for path in sorted(root.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    index_path = project_path(settings.kb_index_path)
    if index_path.exists():
        digest.update(index_path.name.encode("utf-8"))
        digest.update(index_path.read_bytes())
    return digest.hexdigest()


def knowledge_snapshot_errors(require_index: bool = False) -> list[str]:
    manifest = knowledge_manifest()
    if not manifest:
        return ["RAG snapshot manifest is missing"]
    errors: list[str] = []
    expected = {
        "rag_backend": settings.rag_backend,
        "embedding_model": settings.embedding_model,
        "knowledge_dir": settings.kb_dir,
        "index_path": settings.kb_index_path,
    }
    for key, actual in expected.items():
        if manifest.get(key) != actual:
            errors.append(f"RAG snapshot {key}={manifest.get(key)!r}, runtime={actual!r}")
    index_exists = project_path(settings.kb_index_path).exists()
    if bool(manifest.get("index_present")) != index_exists:
        errors.append("RAG snapshot index presence does not match the local index")
    if require_index and not index_exists:
        errors.append("Canonical policy cases require a frozen RAG index; build and freeze it first")
    if manifest.get("sha256") != knowledge_hash():
        errors.append("Knowledge snapshot hash mismatch")
    return errors
