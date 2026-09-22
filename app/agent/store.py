"""The single SQLite-backed business data store used by demo and evaluation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.agent.data.seed_demo import seed_demo


SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "schema.sql"


class SQLiteStore:
    """Concrete data access layer. No mock/dict adapter is kept in runtime code."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        now: Callable[[], datetime] | None = None,
        owns_connection: bool = True,
    ):
        self.conn = conn
        # 这一行很关键：让查询结果支持通过列名访问，比如 row["status"]，而不是只能 row[0]
        self.conn.row_factory = sqlite3.Row
        # 开启外键检查
        self.conn.execute("PRAGMA foreign_keys = ON")
        # 时间获取器（允许测试时固定时间）
        self._now = now or datetime.now
        self._owns_connection = owns_connection

    @classmethod
    def open(cls, path: str | Path, initialize: bool = True) -> "SQLiteStore":
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = cls(sqlite3.connect(db_path))
        if initialize:
            store.initialize(seed_if_empty=True)
        return store

    @classmethod
    def in_memory(
        cls,
        seed: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> "SQLiteStore":
        store = cls(sqlite3.connect(":memory:"), now=now)
        store.initialize(seed_if_empty=seed)
        return store

    def initialize(self, seed_if_empty: bool = True) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if seed_if_empty and count == 0:
            seed_demo(self.conn)
        self.conn.commit()

    @staticmethod
    def _json(value: str | None, fallback):
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def _order_dict(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["items"] = self._json(data.pop("items_json", "[]"), [])
        data["logistics_events"] = self._json(
            data.pop("logistics_events_json", "[]"), []
        )
        data["total"] = float(data["total_amount"])
        return data

    def get_order(self, order_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE order_id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
        return self._order_dict(row) if row else None

    def list_orders(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC, order_id",
            (user_id,),
        ).fetchall()
        return [self._order_dict(row) for row in rows]

    def query_products(self, keyword: str) -> list[dict]:
        query = (keyword or "").strip().lower()
        if not query:
            return []
        exact = self.conn.execute(
            "SELECT * FROM products WHERE lower(product_id) = ?",
            (query,),
        ).fetchall()
        rows = exact or self.conn.execute(
            "SELECT * FROM products ORDER BY product_id"
        ).fetchall()
        terms = [term for term in query.split() if term] or [query]
        scored: list[tuple[int, dict]] = []
        for row in rows:
            data = dict(row)
            data["specs"] = self._json(data.pop("specs_json", "{}"), {})
            data["price"] = float(data["price"])
            data["is_refundable"] = bool(data["is_refundable"])
            if exact:
                scored.append((len(terms), data))
                continue
            searchable = " ".join(
                [
                    data["product_id"], data["name"], data.get("category") or "",
                    data.get("description") or "",
                    " ".join(str(value) for value in data["specs"].values()),
                ]
            ).lower()
            score = sum(1 for term in terms if term in searchable)
            if score:
                scored.append((score, data))
        scored.sort(key=lambda item: (-item[0], item[1]["product_id"]))
        return [data for _, data in scored[:5]]

    def get_logistics(self, order_id: str, user_id: str) -> dict | None:
        order = self.get_order(order_id, user_id)
        if not order:
            return None
        if not order.get("tracking_number"):
            return {
                "order_id": order_id,
                "available": False,
                "order_status": order["status"],
                "error": "该订单尚未发货，暂无物流信息",
            }
        return {
            "order_id": order_id,
            "available": True,
            "tracking_number": order["tracking_number"],
            "carrier": order["carrier"],
            "status": order["logistics_status"],
            "events": order["logistics_events"][-5:],
            "estimated_delivery": order["estimated_delivery"],
        }

    def apply_refund(self, user_id: str, order_id: str, reason: str) -> dict:
        reason = (reason or "").strip()
        if not reason:
            return {"success": False, "error_code": "missing_reason", "error": "退款原因不能为空"}

        with self.conn:
            row = self.conn.execute(
                "SELECT status FROM orders WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            ).fetchone()
            if not row:
                return {
                    "success": False,
                    "error_code": "order_not_found",
                    "error": f"未找到订单 {order_id}，请核实订单号",
                }

            status = row["status"]
            existing = self.conn.execute(
                "SELECT status FROM refunds WHERE order_id = ?", (order_id,)
            ).fetchone()
            if status in {"refund_processing", "refunded", "cancelled"} or existing:
                return {
                    "success": False,
                    "error_code": "already_refunded_or_closed",
                    "error": "该订单已有退款记录或已关闭，不能重复申请",
                }
            if status == "shipped":
                return {
                    "success": False,
                    "error_code": "shipped_not_refundable_yet",
                    "error": "订单已发货，请等待签收后申请退货，或选择拒收",
                }
            if status not in {"pending", "delivered"}:
                return {
                    "success": False,
                    "error_code": "invalid_order_status",
                    "error": f"订单状态 {status} 不允许申请退款",
                }

            next_status = "cancelled" if status == "pending" else "refund_processing"
            created_at = self._now().isoformat(sep=" ", timespec="seconds")
            try:
                self.conn.execute(
                    """
                    INSERT INTO refunds (refund_id, order_id, reason, status, created_at)
                    VALUES (?, ?, ?, 'processing', ?)
                    """,
                    (f"REF-{order_id}", order_id, reason, created_at),
                )
                self.conn.execute(
                    "UPDATE orders SET status = ? WHERE order_id = ? AND user_id = ?",
                    (next_status, order_id, user_id),
                )
            except sqlite3.IntegrityError:
                return {
                    "success": False,
                    "error_code": "already_refunded_or_closed",
                    "error": "该订单已有退款记录，不能重复申请",
                }

        action = "取消订单并发起退款" if status == "pending" else "提交退款申请"
        return {
            "success": True,
            "order_id": order_id,
            "previous_status": status,
            "order_status": next_status,
            "refund_status": "processing",
            "message": f"已{action}，预计 1-3 个工作日内处理。",
        }

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()
