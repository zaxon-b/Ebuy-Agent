from app.evaluation.dataset import EvalCase, StateAssertion
from app.evaluation.metrics import (
    aggregate_pass_at_k,
    evaluate_final_state,
    evaluate_policy_compliance,
    evaluate_tool_correctness,
    faithfulness_score_from_verdict,
    observed_pass_power_k,
    pass_at_k,
)
from app.evaluation.trace import RunTrace, ToolObservation, TurnRecord


def _case(expected: dict, case_id: str = "case") -> EvalCase:
    return EvalCase.model_validate({
        "meta": {
            "id": case_id,
            "level": "Easy",
            "description": case_id,
            "tags": [],
        },
        "run": {"modes": ["single"], "seed_id": "demo-v1", "user_id": "user-demo"},
        "dialogue": {
            "type": "static",
            "turns": [{"text": "测试", "acts": ["other"]}],
        },
        "expected": {"reply": {}, **expected},
    })


def _tool(name: str, arguments: dict, **values) -> ToolObservation:
    return ToolObservation(
        name=name,
        arguments=arguments,
        result='{"success": true}',
        **values,
    )


def test_tool_correctness_separates_selection_arguments_order_and_forbidden():
    case = _case({
        "tool_paths": [[
            {"tool": "query_order", "arguments": {"order_id": "ORD-1"}},
            {"tool": "query_logistics"},
        ]],
        "forbidden_tools": ["apply_refund"],
    })
    trace = RunTrace(
        case_id=case.id,
        tool_observations=[
            _tool("query_order", {"order_id": "ORD-1"}),
            _tool("query_logistics", {"order_id": "ORD-1"}),
        ],
    )
    result = evaluate_tool_correctness(case, trace)
    assert result.score == 1.0
    assert result.recall == result.precision == result.f1 == 1.0
    assert result.argument_accuracy == 1.0
    assert result.order_pass and result.forbidden_pass


def test_tool_correctness_selects_legal_path_and_ignores_auxiliary_tool():
    case = _case({
        "tool_paths": [
            [{"tool": "query_order"}, {"tool": "query_logistics"}],
            [{"tool": "query_logistics"}, {"tool": "query_order"}],
        ],
    })
    trace = RunTrace(
        case_id=case.id,
        tool_observations=[
            _tool("load_skill", {"skill_name": "track-order"}),
            _tool("query_logistics", {}),
            _tool("query_order", {}),
        ],
    )
    result = evaluate_tool_correctness(case, trace)
    assert result.reference_path == ["query_logistics", "query_order"]
    assert result.actual_path == ["query_logistics", "query_order"]
    assert result.score == 1.0

    trace.tool_observations.append(_tool("query_order", {}))
    assert 0.0 < evaluate_tool_correctness(case, trace).score < 1.0


def test_policy_uses_tool_time_snapshot_and_structured_user_act():
    before = {
        "orders": [{"order_id": "ORD-1", "status": "pending"}],
        "refunds": [],
    }
    trace = RunTrace(
        case_id="refund",
        turns=[TurnRecord(0, "确认退款", ["confirm_refund"])],
        tool_observations=[_tool(
            "apply_refund",
            {"order_id": "ORD-1", "reason": "买错"},
            turn_index=0,
            state_before=before,
        )],
    )
    case = _case({
        "tool_paths": [[{"tool": "apply_refund"}]],
        "policies": [
            "refund_requires_confirmation",
            "refund_state_precondition",
        ],
    }, case_id="refund")
    score, details = evaluate_policy_compliance(case, trace)
    assert score == 1.0
    assert all(details.values())


def test_policy_without_declared_predicates_is_na():
    case = _case({"tool_paths": [[]]}, case_id="no-policy")
    score, details = evaluate_policy_compliance(
        case, RunTrace(case_id=case.id)
    )
    assert score is None
    assert details == {}


def test_state_assertions_and_faithfulness_mapping():
    assertion = StateAssertion(
        table="orders",
        field="status",
        op="eq",
        value="cancelled",
        where={"order_id": "ORD-1"},
    )
    score, mismatches = evaluate_final_state(
        {"orders": [{"order_id": "ORD-1", "status": "cancelled"}]},
        [assertion],
    )
    assert score == 1.0 and not mismatches
    assert faithfulness_score_from_verdict("supported") == 1.0
    assert faithfulness_score_from_verdict("unverifiable") == 0.5
    assert faithfulness_score_from_verdict("unsupported") == 0.0


def test_reliability_uses_observed_runs_not_power_approximation():
    runs = {"a": [True, True, True], "b": [False, False, False]}
    assert pass_at_k(3, 3, 3) == 1.0
    assert aggregate_pass_at_k(runs, 3) == 0.5
    assert observed_pass_power_k(runs, 3) == 0.5
