import json
from types import SimpleNamespace

from app.agent.observability import event
from app.agent.run_context import RunContext
from app.agent.tools.manager import ToolManager
from app.evaluation.faults import FaultInjector
from app.evaluation.state import create_case_store
from app.evaluation.tracer import Tracer
from app.multi_agent.router import Router


def _runtime(case_id: str, specs=()):
    store = create_case_store()
    tracer = Tracer(case_id)
    context = RunContext(
        store=store,
        current_user_id="user-demo",
        tracer=tracer,
        faults=FaultInjector(specs),
    )
    return store, tracer, context


def test_each_tool_call_emits_one_complete_event_and_one_observation():
    store, tracer, context = _runtime("trace-case")
    manager = ToolManager(
        context=context,
        allowed_tools={"query_order", "apply_refund"},
    )
    try:
        # 确认门禁（工具层）：应用户「确认退款」后 apply_refund 才允许写库。
        # 同一轮内先查单再退款，均带 confirm_refund 用户上下文。
        tracer.set_turn_contract(0, "确认退款", ["confirm_refund"])
        manager.begin_turn(0)
        manager.execute_tool("query_order", {"order_id": "ORD-20240120-002"})
        manager.execute_tool(
            "apply_refund",
            {"order_id": "ORD-20240120-002", "reason": "买错了"},
        )

        kinds = [item.kind for item in tracer.trace.events]
        assert kinds == ["on_tool_end", "on_tool_end"]
        observations = tracer.trace.tool_observations
        assert len(observations) == 2
        assert observations[0].sequence == 1
        assert observations[1].sequence == 2
        assert [item.step_index for item in observations] == [0, 1]
        assert observations[0].description
        assert observations[0].state_before == observations[0].state_after
        assert observations[1].state_before != observations[1].state_after
        assert json.loads(observations[1].result)["success"] is True
    finally:
        manager.close()
        store.close()


def test_tool_error_and_fault_events_keep_structured_status(monkeypatch):
    specs = [{
        "type": "tool_error",
        "tool": "query_order",
        "trigger_call": 1,
        "fail_times": 1,
        "error": {"success": False, "error": "injected"},
    }]
    store, tracer, context = _runtime("errors", specs)
    manager = ToolManager(context=context, allowed_tools={"query_order"})
    try:
        manager.begin_turn(0)
        manager.execute_tool("query_order", {"order_id": "ORD-20240115-001"})
        assert tracer.trace.fault_events[0].fault_type == "tool_error"
        assert tracer.trace.tool_observations[0].status == "error"

        def raise_from_tool(name, arguments, context):
            del name, arguments, context
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "app.agent.tools.manager.local_execute_tool", raise_from_tool
        )
        result = manager.execute_tool(
            "query_order", {"order_id": "ORD-20240115-001"}
        )
        assert json.loads(result)["success"] is False
        assert tracer.trace.events[-1].kind == "on_tool_end"
        assert tracer.trace.tool_observations[1].status == "error"
        assert "RuntimeError" in tracer.trace.tool_observations[1].error
        assert "boom" in tracer.trace.tool_observations[1].result
    finally:
        manager.close()
        store.close()


def test_complete_llm_event_is_projected_without_lifecycle_pairing():
    tracer = Tracer("llm")
    tracer.emit(event(
        "on_llm_end",
        purpose="react",
        model="fake",
        messages=[],
        tools=[],
        status="success",
        error=None,
        tool_calls=[{"name": "query_order", "arguments": '{"order_id":"ORD-1"}'}],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        latency_ms=12.0,
    ))
    tracer.emit(event(
        "on_route", turn_index=0, route="postsale", raw="postsale"
    ))
    assert len(tracer.trace.events) == 2
    assert len(tracer.trace.llm_calls) == 1
    assert tracer.trace.llm_calls[0].tool_calls[0]["name"] == "query_order"
    assert tracer.trace.total_tokens == 15
    assert tracer.trace.route == "postsale"


def test_real_router_boundary_emits_one_complete_llm_event():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="postsale", tool_calls=None
        ))],
        usage=SimpleNamespace(
            prompt_tokens=8, completion_tokens=1, total_tokens=9
        ),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: response
    )))
    tracer = Tracer("router-event")

    route = Router(client, "fake-model", tracer).route("查订单", turn_index=0)

    assert route == "postsale"
    assert [item.kind for item in tracer.trace.events] == [
        "on_llm_end", "on_route",
    ]
    payload = tracer.trace.events[0].payload
    assert payload["messages"] and payload["tools"] == []
    assert payload["usage"]["total_tokens"] == 9
    assert payload["status"] == "success" and payload["error"] is None
    assert tracer.trace.llm_calls[0].sequence == 1


def test_raw_event_payload_is_redacted_before_persistence():
    tracer = Tracer("redaction")
    tracer.emit(event(
        "on_llm_end",
        purpose="react",
        model="fake",
        messages=[{"role": "system", "api_key": "secret-value"}],
        tools=[],
    ))
    assert tracer.trace.events[0].payload["messages"][0]["api_key"] == "***REDACTED***"


def test_event_factory_is_a_small_unvalidated_envelope():
    item = event("on_tool_end", name="query_order")
    assert item.kind == "on_tool_end"
    assert item.payload == {"name": "query_order"}


def test_two_run_contexts_isolate_store_trace_and_fault_counters():
    store_a, tracer_a, context_a = _runtime("case-a")
    store_b, tracer_b, context_b = _runtime("case-b")
    manager_a = ToolManager(context=context_a, allowed_tools={"apply_refund"})
    manager_b = ToolManager(context=context_b, allowed_tools={"query_order"})
    try:
        # 用户已确认退款，apply_refund 才能写库（确认门禁在工具层）
        tracer_a.set_turn_contract(0, "确认退款", ["confirm_refund"])
        manager_a.begin_turn(0)
        manager_a.execute_tool(
            "apply_refund",
            {"order_id": "ORD-20240120-002", "reason": "买错了"},
        )
        assert store_a.get_order(
            "ORD-20240120-002", "user-demo"
        )["status"] == "cancelled"
        assert store_b.get_order(
            "ORD-20240120-002", "user-demo"
        )["status"] == "pending"
        assert len(tracer_a.trace.tool_observations) == 1
        assert tracer_b.trace.tool_observations == []

        manager_b.begin_turn(0)
        manager_b.execute_tool(
            "query_order", {"order_id": "ORD-20240120-002"}
        )
        assert len(tracer_a.trace.tool_observations) == 1
        assert len(tracer_b.trace.tool_observations) == 1
    finally:
        manager_a.close()
        manager_b.close()
        store_a.close()
        store_b.close()


def test_refund_confirmation_guard_rejects_without_user_confirm():
    store, tracer, context = _runtime("guard-case")
    manager = ToolManager(context=context, allowed_tools={"apply_refund"})
    try:
        # 测试确认门禁：无 confirm_refund 用户上下文 → apply_refund 必须拒绝且不写库
        tracer.set_turn_contract(0, "我要退货", ["request_refund"])
        manager.begin_turn(0)
        result = manager.execute_tool(
            "apply_refund",
            {"order_id": "ORD-20240120-002", "reason": "买错了"},
        )
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["error_code"] == "confirmation_required"
        # 订单仍 pending，没有任何退款记录被写入
        assert store.get_order("ORD-20240120-002", "user-demo")["status"] == "pending"
        obs = tracer.trace.tool_observations
        assert len(obs) == 1
        assert obs[0].status == "error"
    finally:
        manager.close()
        store.close()
