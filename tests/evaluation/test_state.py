import json

from app.agent.run_context import RunContext
from app.agent.tools.registry import execute_tool
from app.evaluation.dataset import StateAssertion
from app.evaluation.metrics import evaluate_final_state
from app.evaluation.state import create_case_store, snapshot_store


def test_case_store_is_deterministic_and_user_isolated():
    store = create_case_store()
    try:
        assert store.get_order("ORD-20240115-001", "user-demo") is not None
        assert store.get_order("ORD-20240122-005", "user-demo") is None
        assert all(
            order["user_id"] == "user-demo"
            for order in store.list_orders("user-demo")
        )
        assert store.query_products("不存在的随机商品") == []
        logistics = store.get_logistics("ORD-20240115-001", "user-demo")
        assert logistics and len(logistics["events"]) == 4
    finally:
        store.close()


def test_refund_state_matrix_and_database_idempotency():
    store = create_case_store()
    context = RunContext(
        store=store,
        current_user_id="user-demo",
    )
    try:
        first = json.loads(execute_tool(
            "apply_refund",
            {"order_id": "ORD-20240120-002", "reason": "买错了"},
            context,
        ))
        second = json.loads(execute_tool(
            "apply_refund",
            {"order_id": "ORD-20240120-002", "reason": "再次申请"},
            context,
        ))
        assert first["success"] is True
        assert store.get_order(
            "ORD-20240120-002", "user-demo"
        )["status"] == "cancelled"
        assert second["error_code"] == "already_refunded_or_closed"
        count = store.conn.execute(
            "SELECT COUNT(*) FROM refunds WHERE order_id='ORD-20240120-002'"
        ).fetchone()[0]
        assert count == 1

        assert store.apply_refund(
            "user-demo", "ORD-20240115-001", "不想要"
        )["error_code"] == "shipped_not_refundable_yet"
        delivered = store.apply_refund(
            "user-demo", "ORD-20240110-003", "质量问题"
        )
        assert delivered["success"] is True
        assert store.get_order(
            "ORD-20240110-003", "user-demo"
        )["status"] == "refund_processing"
        assert store.apply_refund(
            "user-demo", "ORD-20240105-006", "再次申请"
        )["error_code"] == "already_refunded_or_closed"
        assert store.apply_refund(
            "user-demo", "ORD-20240122-005", "越权申请"
        )["error_code"] == "order_not_found"
    finally:
        store.close()


def test_patch_snapshot_and_final_state_assertion_are_separate_functions():
    store = create_case_store(initial_state_patch={
        "orders": {"ORD-20240120-002": {"shipping_address": "新地址"}}
    })
    try:
        snapshot = snapshot_store(store)
        score, mismatches = evaluate_final_state(snapshot, [StateAssertion(
            table="orders",
            field="shipping_address",
            op="eq",
            value="新地址",
            where={"order_id": "ORD-20240120-002"},
        )])
        assert score == 1.0
        assert mismatches == []
    finally:
        store.close()
