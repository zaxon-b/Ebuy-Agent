import json

from app.evaluation.faults import FaultInjector


def test_transient_and_persistent_result_faults_have_per_case_counters():
    transient = FaultInjector([{
        "type": "tool_error",
        "tool": "query_order",
        "trigger_call": 1,
        "fail_times": 1,
        "error": {"success": False, "error": "504"},
    }])
    first = transient.before_tool("query_order", {})
    assert first is not None
    assert json.loads(first.result)["success"] is False
    assert transient.before_tool("query_order", {}) is None

    persistent = FaultInjector([{
        "type": "empty_result",
        "tool": "search_knowledge",
        "trigger_call": 1,
        "results": [],
    }])
    assert json.loads(
        persistent.before_tool("search_knowledge", {}).result
    )["results"] == []
    assert persistent.before_tool("search_knowledge", {}) is not None
