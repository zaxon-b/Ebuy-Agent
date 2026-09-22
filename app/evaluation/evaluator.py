"""Five-core-metric evaluator; diagnostics never compensate for hard failures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from openai import OpenAI

from app.evaluation import metrics
from app.evaluation.dataset import EvalCase
from app.evaluation.runner import EvaluationRunner


def _avg(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


@dataclass
class EvalResult:
    case_id: str
    description: str
    category: str = "C1"
    difficulty: int = 0

    # Five public core metrics. Task success is incomplete without Faithfulness Judge.
    task_success: float | None = None
    final_state_accuracy: float | None = None
    tool_correctness: float = 0.0
    policy_compliance: float | None = None
    faithfulness: float | None = None
    faithfulness_verdict: str | None = None

    tool_details: dict = field(default_factory=dict)
    policy_details: dict = field(default_factory=dict)
    state_mismatches: list[str] = field(default_factory=list)
    response_contract: float = 0.0
    response_reasons: list[str] = field(default_factory=list)

    # Diagnostics and observations: measured, never used to rescue a failed Case.
    answer_quality: float | None = None
    process_soundness: float | None = None
    token_cost: int = 0
    num_tool_calls: int = 0
    num_business_tool_calls: int = 0
    num_llm_calls: int = 0
    tool_success_rate: float | None = None
    latency_ms: float = 0.0
    tool_recall: float | None = None
    tool_precision: float | None = None
    tool_f1: float | None = None
    forbidden_rate: float | None = None
    tool_efficiency: float | None = None

    complete: bool = False
    passed: bool = False
    trace: dict = field(default_factory=dict)
    judge_reasons: dict = field(default_factory=dict)
    failure_types: list[str] = field(default_factory=list)
    error: str | None = None


class Evaluator:
    def __init__(
        self,
        runner: EvaluationRunner,
        client: OpenAI,
        model: str,
        use_judge: bool = True,
        diagnostics: bool = True,
    ):
        self.runner = runner
        self.client = client
        self.model = model
        self.use_judge = use_judge
        self.diagnostics = diagnostics

    @staticmethod
    def _process_context(trace) -> dict:
        return {
            "user_turns": [record.text for record in trace.turns],
            "tool_steps": [
                {
                    "turn_index": item.turn_index or 0,
                    "step_index": item.step_index or 0,
                    "name": item.name,
                    "description": item.description,
                    "arguments": item.arguments,
                    "result": item.result,
                    "status": item.status,
                }
                for item in trace.tool_observations
            ],
            "sop": trace.metadata.get("sop"),
            "tool_schema": trace.metadata.get("tool_schema", []),
        }

    @staticmethod
    def _failure_types(
        result: EvalResult, case: EvalCase | None = None
    ) -> list[str]:
        failures: list[str] = []
        if result.error:
            return ["runtime_error"]
        if result.tool_correctness < 1:
            argument_accuracy = result.tool_details.get("argument_accuracy")
            if argument_accuracy is not None and argument_accuracy < 1:
                failures.append("tool_argument_error")
            elif not result.tool_details.get("order_pass", True):
                failures.append("planning_or_order_error")
            else:
                failures.append("tool_selection_error")
        if result.final_state_accuracy not in {None, 1.0}:
            failures.append("final_state_error")
        if result.policy_compliance not in {None, 1.0}:
            failures.append("policy_violation")
        if result.response_contract < 1:
            failures.append("response_contract_error")
        if result.faithfulness_verdict in {"unsupported", "contradicted"}:
            failures.append("hallucination_or_contradiction")
        valid_expected_abstention = bool(
            case
            and case.expected.reply.required_abstention
            and result.policy_details.get("knowledge_failure_requires_abstention")
            is True
        )
        if (
            result.faithfulness_verdict == "unverifiable"
            and not valid_expected_abstention
        ):
            failures.append("unverifiable_without_valid_abstention")
        if not result.complete and not result.error:
            failures.append("judge_incomplete")
        return list(dict.fromkeys(failures))

    def run_case(self, case: EvalCase) -> EvalResult:
        trace = self.runner.run_case(case)
        result = EvalResult(
            case_id=case.id,
            description=case.description,
            category=case.meta.category,
            difficulty=case.meta.difficulty_score,
            trace=trace.to_dict(),
            error=trace.error,
            token_cost=trace.total_tokens,
            num_tool_calls=trace.num_tool_calls,
            num_business_tool_calls=trace.num_business_tool_calls,
            num_llm_calls=trace.num_llm_calls,
            tool_success_rate=trace.tool_success_rate,
            latency_ms=trace.end_to_end_latency_ms,
        )
        if trace.error:
            result.failure_types = self._failure_types(result, case)
            return result

        try:
            tool = metrics.evaluate_tool_correctness(case, trace)
            result.tool_correctness = tool.score
            result.tool_details = asdict(tool)
            result.tool_recall = tool.recall
            result.tool_precision = tool.precision
            result.tool_f1 = tool.f1
            result.forbidden_rate = tool.forbidden_rate
            result.tool_efficiency = metrics.tool_efficiency(
                len(tool.reference_path), trace.num_business_tool_calls
            )

            result.final_state_accuracy, result.state_mismatches = (
                metrics.evaluate_final_state(trace.final_state, case.expected.final_state)
            )
            result.policy_compliance, result.policy_details = (
                metrics.evaluate_policy_compliance(case, trace)
            )
            result.response_contract, result.response_reasons = (
                metrics.evaluate_response_contract(case, trace)
            )

            if self.use_judge:
                if self.diagnostics:
                    quality, reason = metrics.judge_answer_quality(
                        self.client,
                        self.model,
                        [record.text for record in trace.turns],
                        trace.final_reply,
                        case.expected.reply.must_include_facts,
                        (
                            trace.final_response.model_dump(mode="json")
                            if trace.final_response
                            else None
                        ),
                    )
                    result.answer_quality = quality / 5
                    result.judge_reasons["answer_quality"] = reason

                faith_score, verdict, reason = metrics.judge_faithfulness(
                    self.client,
                    self.model,
                    trace.final_reply,
                    trace.tool_observations,
                )
                result.faithfulness = faith_score
                result.faithfulness_verdict = verdict
                result.judge_reasons["faithfulness"] = reason

                if self.diagnostics:
                    process, reason = metrics.judge_process_soundness(
                        self.client, self.model, self._process_context(trace)
                    )
                    result.process_soundness = process / 5
                    result.judge_reasons["process_soundness"] = reason

                result.complete = verdict in {
                    "supported", "unverifiable", "contradicted", "unsupported"
                }
                if result.complete:
                    faithfulness_pass = verdict == "supported" or (
                        verdict == "unverifiable"
                        and case.expected.reply.required_abstention
                        and result.policy_compliance in {None, 1.0}
                    )
                    result.task_success = float(
                        result.tool_correctness == 1.0
                        and result.final_state_accuracy in {None, 1.0}
                        and result.policy_compliance in {None, 1.0}
                        and result.response_contract == 1.0
                        and faithfulness_pass
                    )
                    result.passed = result.task_success == 1.0
            # --no-judge deliberately leaves faithfulness/task_success as N/A.
        except Exception as exc:  # noqa: BLE001 - isolate grading failures per Case
            result.error = f"评分异常 {type(exc).__name__}: {exc}"
            result.task_success = 0.0
            result.passed = False
        result.failure_types = self._failure_types(result, case)
        return result

    def run_all(self, cases: list[EvalCase]) -> dict:
        return self._aggregate([self.run_case(case) for case in cases])

    def _aggregate(self, results: list[EvalResult]) -> dict:
        total = len(results)
        complete = [result for result in results if result.complete]
        summary = {
            "total": total,
            "completed": len(complete),
            "passed": sum(result.passed for result in results),
            "pass_rate": (
                sum(result.passed for result in complete) / len(complete)
                if complete else None
            ),
            "task_success": _avg([result.task_success for result in results]),
            "final_state_accuracy": _avg(
                [result.final_state_accuracy for result in results]
            ),
            "tool_correctness": _avg([result.tool_correctness for result in results]),
            "policy_compliance": _avg(
                [result.policy_compliance for result in results]
            ),
            "faithfulness": _avg([result.faithfulness for result in results]),
            "response_contract": _avg(
                [result.response_contract for result in results]
            ),
            "answer_quality": _avg([result.answer_quality for result in results]),
            "process_soundness": _avg(
                [result.process_soundness for result in results]
            ),
            "tool_recall": _avg([result.tool_recall for result in results]),
            "tool_precision": _avg([result.tool_precision for result in results]),
            "tool_f1": _avg([result.tool_f1 for result in results]),
            "forbidden_rate": _avg([result.forbidden_rate for result in results]),
            "tool_efficiency": _avg([result.tool_efficiency for result in results]),
            "tool_success_rate": _avg(
                [result.tool_success_rate for result in results]
            ),
            "supported_rate": (
                sum(result.faithfulness_verdict == "supported" for result in results)
                / sum(result.faithfulness_verdict is not None for result in results)
                if any(result.faithfulness_verdict is not None for result in results)
                else None
            ),
            "total_tokens": sum(result.token_cost for result in results),
            "avg_tokens_per_case": (
                sum(result.token_cost for result in results) / total if total else 0.0
            ),
            "avg_tool_calls": (
                sum(result.num_business_tool_calls for result in results) / total
                if total else 0.0
            ),
            "avg_total_tool_calls": (
                sum(result.num_tool_calls for result in results) / total
                if total else 0.0
            ),
            "avg_llm_calls": (
                sum(result.num_llm_calls for result in results) / total if total else 0.0
            ),
            "avg_latency_ms": (
                sum(result.latency_ms for result in results) / total if total else 0.0
            ),
            "total_turns": sum(
                len(result.trace.get("turns", [])) for result in results
            ),
            "total_events": sum(
                len(result.trace.get("events", [])) for result in results
            ),
            "total_llm_errors": sum(
                call.get("status") == "error"
                for result in results
                for call in result.trace.get("llm_calls", [])
            ),
            "total_tool_errors": sum(
                int(result.trace.get("num_tool_errors", 0)) for result in results
            ),
            "total_fault_events": sum(
                len(result.trace.get("fault_events", [])) for result in results
            ),
            "total_state_changes": sum(
                int(result.trace.get("core_summary", {}).get("state_change_count", 0))
                for result in results
            ),
            "runtime_errors": sum(result.error is not None for result in results),
        }
        route_counts: dict[str, int] = {}
        for result in results:
            route = result.trace.get("route")
            if route:
                route_counts[route] = route_counts.get(route, 0) + 1
        summary["route_counts"] = route_counts
        attribution: dict[str, int] = {}
        for result in results:
            for failure in result.failure_types:
                attribution[failure] = attribution.get(failure, 0) + 1
        return {
            "summary": summary,
            "failure_attribution": attribution,
            "cases": [self._result_to_dict(result) for result in results],
        }

    @staticmethod
    def _result_to_dict(result: EvalResult) -> dict:
        return {
            "case_id": result.case_id,
            "description": result.description,
            "category": result.category,
            "difficulty": result.difficulty,
            "complete": result.complete,
            "passed": result.passed,
            "core": {
                "task_success": result.task_success,
                "final_state_accuracy": result.final_state_accuracy,
                "tool_correctness": result.tool_correctness,
                "policy_compliance": result.policy_compliance,
                "faithfulness": result.faithfulness,
                "faithfulness_verdict": result.faithfulness_verdict,
            },
            "response_contract": result.response_contract,
            "response_reasons": result.response_reasons,
            "tool_details": result.tool_details,
            "policy_details": result.policy_details,
            "state_mismatches": result.state_mismatches,
            "diagnostics": {
                "answer_quality": result.answer_quality,
                "process_soundness": result.process_soundness,
                "token_cost": result.token_cost,
                "num_tool_calls": result.num_tool_calls,
                "num_business_tool_calls": result.num_business_tool_calls,
                "num_llm_calls": result.num_llm_calls,
                "tool_success_rate": result.tool_success_rate,
                "latency_ms": result.latency_ms,
                "tool_recall": result.tool_recall,
                "tool_precision": result.tool_precision,
                "tool_f1": result.tool_f1,
                "forbidden_rate": result.forbidden_rate,
                "tool_efficiency": result.tool_efficiency,
            },
            "judge_reasons": result.judge_reasons,
            "failure_types": result.failure_types,
            "trace": result.trace,
            "error": result.error,
        }
