import json
from types import SimpleNamespace

from app.agent.observability import event
from app.agent.run_context import RunContext
from app.agent.tools.manager import ToolManager
from app.config.settings import settings
from app.evaluation.dataset import EvalCase, load_dataset
from app.evaluation.evaluator import EvalResult, Evaluator
from app.evaluation.report import coverage_matrix, write_artifacts
from app.evaluation.runner import EvaluationRunner
from app.evaluation.state import (
    knowledge_hash,
    knowledge_snapshot_errors,
)
from app.scripts.run_eval import _average_run_summaries
from app.schemas.response import CustomerServiceResponse, IntentType


class ScriptedAgent:
    def __init__(self, context: RunContext):
        self.context = context
        self.tool_manager = ToolManager(
            context=context, allowed_tools={"query_order"}
        )

    def chat(self, text: str) -> CustomerServiceResponse:
        self.context.tracer.emit(event(
            "on_turn_start",
            turn_index=0,
            user_input=text,
            acts=[],
        ))
        return CustomerServiceResponse(
            intent=IntentType.GREETING,
            confidence=1.0,
            reply="你好，我是小夕，请问有什么可以帮您？",
            requires_human=False,
        )

    def close(self):
        self.tool_manager.close()


def _factory(mode, context, session_path):
    del mode, session_path
    return ScriptedAgent(context)


def _case() -> EvalCase:
    return EvalCase.model_validate({
        "meta": {
            "id": "offline-greeting",
            "level": "Easy",
            "description": "offline greeting",
            "tags": ["greeting"],
        },
        "run": {
            "modes": ["single"],
            "seed_id": "demo-v1",
            "user_id": "user-demo",
        },
        "dialogue": {
            "type": "static",
            "turns": [{"text": "你好", "acts": ["other"]}],
        },
        "expected": {
            "tool_paths": [[]],
            "forbidden_tools": ["query_order"],
            "reply": {
                "must_include_facts": ["你好"],
                "expected_requires_human": False,
            },
        },
    })


def _judge_client(verdict: str = "supported"):
    def create(**kwargs):
        del kwargs
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"verdict": verdict, "reason": "offline"})
            ))
        ])

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def test_offline_runner_and_evaluator_complete_without_agent_api_calls():
    evaluator = Evaluator(
        runner=EvaluationRunner(mode="single", agent_factory=_factory),
        client=_judge_client(),
        model="offline",
        use_judge=True,
        diagnostics=False,
    )
    report = evaluator.run_all([_case()])
    result = report["cases"][0]
    assert result["complete"] is True
    assert result["passed"] is True
    assert result["core"]["task_success"] == 1.0
    assert result["core"]["tool_correctness"] == 1.0
    assert [item["kind"] for item in result["trace"]["events"]] == [
        "on_turn_start",
    ]
    assert result["trace"]["turns"][0]["acts"] == ["other"]
    assert report["summary"]["total_turns"] == 1
    assert report["summary"]["total_events"] == 1
    assert report["summary"]["total_llm_errors"] == 0
    assert report["summary"]["total_tool_errors"] == 0
    assert report["summary"]["total_fault_events"] == 0
    assert report["summary"]["total_state_changes"] == 0
    assert report["summary"]["runtime_errors"] == 0
    assert report["summary"]["route_counts"] == {}


def test_no_judge_is_explicitly_incomplete_not_an_automatic_pass():
    evaluator = Evaluator(
        runner=EvaluationRunner(mode="single", agent_factory=_factory),
        client=None,
        model="offline",
        use_judge=False,
    )
    result = evaluator.run_all([_case()])["cases"][0]
    assert result["complete"] is False
    assert result["passed"] is False
    assert result["core"]["task_success"] is None
    assert result["core"]["faithfulness"] is None
    assert "judge_incomplete" in result["failure_types"]


def test_unverifiable_needs_an_explicit_abstention_policy_to_pass():
    evaluator = Evaluator(
        runner=EvaluationRunner(mode="single", agent_factory=_factory),
        client=_judge_client("unverifiable"),
        model="offline",
        use_judge=True,
        diagnostics=False,
    )
    result = evaluator.run_all([_case()])["cases"][0]
    assert result["complete"] is True
    assert result["core"]["faithfulness_verdict"] == "unverifiable"
    assert result["core"]["task_success"] == 0.0
    assert result["passed"] is False
    assert "unverifiable_without_valid_abstention" in result["failure_types"]


def test_valid_abstention_is_not_misattributed_when_another_gate_fails():
    case = _case().model_copy(
        update={
            "expected": _case().expected.model_copy(
                update={
                    "reply": _case().expected.reply.model_copy(
                        update={
                            "required_abstention": True,
                            "abstention_patterns": ["无法核实"],
                        }
                    )
                }
            )
        }
    )
    result = EvalResult(
        case_id=case.id,
        description=case.description,
        tool_correctness=0.0,
        task_success=0.0,
        faithfulness_verdict="unverifiable",
        policy_details={"knowledge_failure_requires_abstention": True},
    )

    failures = Evaluator._failure_types(result, case)

    assert "tool_selection_error" in failures
    assert "unverifiable_without_valid_abstention" not in failures


def test_repeated_run_summary_sums_observation_counters_and_routes():
    def one_run(route: str, passed: int) -> dict:
        return {"summary": {
            "total": 2,
            "completed": 2,
            "passed": passed,
            "task_success": passed / 2,
            "total_tokens": 100,
            "total_turns": 3,
            "total_events": 8,
            "total_llm_errors": 0,
            "total_tool_errors": 1,
            "total_fault_events": 1,
            "total_state_changes": 1,
            "runtime_errors": 0,
            "route_counts": {route: 2},
        }}

    summary = _average_run_summaries([
        one_run("presale", 1),
        one_run("postsale", 2),
    ])

    assert summary["total_executions"] == 4
    assert summary["completed_executions"] == 4
    assert summary["passed_executions"] == 3
    assert summary["total_events"] == 16
    assert summary["total_tool_errors"] == 2
    assert summary["route_counts"] == {"presale": 2, "postsale": 2}


def test_report_writes_only_the_four_v4_artifacts(tmp_path):
    cases = load_dataset(
        "app/evaluation/dataset/canonical_cases.json", canonical_only=True
    )
    payload = {
        "generated_at": "2026-01-01T00:00:00",
        "runs": 1,
        "summary": {
            "total": 0,
            "completed": 0,
            "task_success": None,
            "final_state_accuracy": None,
            "tool_correctness": None,
            "policy_compliance": None,
            "faithfulness": None,
        },
        "reliability": {"pass_at_3": None, "observed_pass_3": None},
        "failure_attribution": {},
        "cases": [],
    }
    target = write_artifacts(payload, tmp_path)
    assert {path.name for path in target.iterdir()} == {
        "summary.json", "cases.jsonl", "traces.jsonl", "report.md",
    }
    coverage = coverage_matrix(cases)
    assert coverage["levels"] == {
        "Easy": 9, "Medium": 9, "Hard": 32,
    }
    assert coverage["execution_modes"] == {
        "single": 48, "multi": 50,
    }


def test_rag_snapshot_preflight_requires_frozen_index(tmp_path, monkeypatch):
    missing_index = tmp_path / "missing-index.json"
    snapshot = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        "app.evaluation.state.settings.kb_index_path", str(missing_index)
    )
    monkeypatch.setattr(
        "app.evaluation.state.settings.eval_rag_snapshot_path", str(snapshot)
    )
    snapshot.write_text(json.dumps({
        "snapshot_id": "test",
        "rag_backend": settings.rag_backend,
        "embedding_model": settings.embedding_model,
        "knowledge_dir": settings.kb_dir,
        "index_path": str(missing_index),
        "index_present": False,
        "sha256": knowledge_hash(),
    }), encoding="utf-8")

    assert knowledge_snapshot_errors(require_index=False) == []
    errors = knowledge_snapshot_errors(require_index=True)
    assert any("require a frozen RAG index" in error for error in errors)
