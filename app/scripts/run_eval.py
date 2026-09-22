"""Run the deterministic Canonical benchmark defined by Eval v4."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.evaluation.dataset import load_dataset  # noqa: E402
from app.evaluation.evaluator import Evaluator  # noqa: E402
from app.evaluation.metrics.reliability import (  # noqa: E402
    aggregate_pass_at_k,
    observed_pass_power_k,
)
from app.evaluation.report import coverage_matrix, write_artifacts  # noqa: E402
from app.evaluation.runner import EvaluationRunner  # noqa: E402
from app.evaluation.state import knowledge_snapshot_errors  # noqa: E402


def _average_run_summaries(reports: list[dict]) -> dict:
    keys = [
        "task_success", "final_state_accuracy", "tool_correctness",
        "policy_compliance", "faithfulness", "supported_rate",
        "response_contract", "answer_quality", "process_soundness",
        "tool_recall", "tool_precision", "tool_f1", "forbidden_rate",
        "tool_efficiency", "tool_success_rate",
        "avg_tokens_per_case", "avg_tool_calls", "avg_llm_calls",
        "avg_total_tool_calls", "avg_latency_ms",
    ]
    summary = {
        "total": reports[0]["summary"]["total"] if reports else 0,
        "completed": reports[-1]["summary"]["completed"] if reports else 0,
        "passed": reports[-1]["summary"]["passed"] if reports else 0,
        "total_executions": sum(
            report["summary"]["total"] for report in reports
        ),
        "completed_executions": sum(
            report["summary"]["completed"] for report in reports
        ),
        "passed_executions": sum(
            report["summary"]["passed"] for report in reports
        ),
    }
    for key in keys:
        values = [report["summary"].get(key) for report in reports]
        present = [value for value in values if value is not None]
        summary[key] = sum(present) / len(present) if present else None
    summary["pass_rate"] = summary["task_success"]
    summary["total_tokens"] = sum(
        report["summary"]["total_tokens"] for report in reports
    )
    for key in (
        "total_turns",
        "total_events",
        "total_llm_errors",
        "total_tool_errors",
        "total_fault_events",
        "total_state_changes",
        "runtime_errors",
    ):
        summary[key] = sum(report["summary"].get(key, 0) for report in reports)
    route_counts: dict[str, int] = {}
    for report in reports:
        for route, count in report["summary"].get("route_counts", {}).items():
            route_counts[route] = route_counts.get(route, 0) + count
    summary["route_counts"] = route_counts
    return summary


def _combine(reports: list[dict], cases, runs: int) -> dict:
    task_runs: dict[str, list[bool | None]] = {case.id: [] for case in cases}
    for report in reports:
        for result in report["cases"]:
            task_runs[result["case_id"]].append(
                bool(result["passed"]) if result.get("complete") else None
            )
    reliability_ready = runs >= 3 and all(
        all(value is not None for value in values)
        for values in task_runs.values()
    )
    completed_runs = {
        case_id: [bool(value) for value in values]
        for case_id, values in task_runs.items()
    }
    reliability = {
        "pass_at_3": (
            aggregate_pass_at_k(completed_runs, 3) if reliability_ready else None
        ),
        "observed_pass_3": (
            observed_pass_power_k(completed_runs, 3) if reliability_ready else None
        ),
        "per_case": task_runs,
    }
    attribution: dict[str, int] = {}
    for report in reports:
        for name, count in report.get("failure_attribution", {}).items():
            attribution[name] = attribution.get(name, 0) + count
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "suite": "canonical",
        "contract": "canonical-v4",
        "runs": runs,
        "summary": _average_run_summaries(reports),
        "reliability": reliability,
        "coverage": coverage_matrix(cases),
        "failure_attribution": attribution,
        "cases": reports[-1]["cases"] if reports else [],
        "per_run": [report["summary"] for report in reports],
        "run_cases": [report["cases"] for report in reports],
    }


def _gate_failures(payload: dict, path: Path | None) -> list[str]:
    if path is None:
        return []
    config = tomllib.loads(path.read_text(encoding="utf-8"))["canonical"]
    checks = {
        "task_success": (
            payload["summary"].get("task_success"),
            config["min_task_success"],
        ),
        "policy_compliance": (
            payload["summary"].get("policy_compliance"),
            config["min_policy_compliance"],
        ),
        "observed_pass_3": (
            payload["reliability"].get("observed_pass_3"),
            config["min_observed_pass_3"],
        ),
    }
    failures = []
    for name, (actual, minimum) in checks.items():
        if actual is None:
            failures.append(f"{name}=N/A（评测未完成或运行次数不足）")
        elif actual < minimum:
            failures.append(f"{name}={actual:.1%} < {minimum:.1%}")
    return failures


def _display_percent(value) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _print_summary(payload: dict, artifact_path: Path) -> None:
    summary = payload["summary"]
    reliability = payload["reliability"]
    print("\nCanonical Eval v4")
    print(f"  Cases              : {summary['total']}")
    print(f"  Complete           : {summary['completed']}/{summary['total']}")
    print(f"  Runs               : {payload['runs']}")
    print(f"  Task success       : {_display_percent(summary['task_success'])}")
    print(f"  Final state        : {_display_percent(summary['final_state_accuracy'])}")
    print(f"  Tool correctness   : {_display_percent(summary['tool_correctness'])}")
    print(f"  Policy compliance  : {_display_percent(summary['policy_compliance'])}")
    print(f"  Faithfulness       : {_display_percent(summary['faithfulness'])}")
    print(f"  pass@3             : {_display_percent(reliability['pass_at_3'])}")
    print(f"  observed pass^3    : {_display_percent(reliability['observed_pass_3'])}")
    print(f"  Artifacts          : {artifact_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Canonical Agent Eval v4")
    parser.add_argument("--suite", choices=["canonical", "exploratory"], default="canonical")
    parser.add_argument("--dataset", default=settings.eval_canonical_dataset_path)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--mode", choices=["single", "multi"], default="single")
    parser.add_argument(
        "--judge", dest="judge", action="store_true", default=settings.eval_use_judge
    )
    parser.add_argument("--no-judge", dest="judge", action="store_false")
    parser.add_argument(
        "--diagnostics", dest="diagnostics", action="store_true", default=True
    )
    parser.add_argument("--no-diagnostics", dest="diagnostics", action="store_false")
    parser.add_argument("--gate-config", default=None)
    parser.add_argument("--artifact-dir", default=settings.eval_artifact_dir)
    parser.add_argument(
        "--only",
        default=None,
        help="逗号分隔的 case id 白名单，只运行这些 case（冒烟/定点调试用）",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate Case schema and references without running an Agent",
    )
    args = parser.parse_args()

    if args.suite == "exploratory":
        parser.error("Exploratory/LLM Simulator belongs to phase 4 and is not implemented")
    if args.runs < 1:
        parser.error("--runs must be >= 1")

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = ROOT / dataset_path
    all_cases = load_dataset(dataset_path, canonical_only=True)
    if args.validate_only:
        print(json.dumps(coverage_matrix(all_cases), ensure_ascii=False, indent=2))
        print(f"Validated {len(all_cases)} Canonical cases from {dataset_path}")
        return

    cases = [case for case in all_cases if args.mode in case.modes]
    if args.only:
        only_ids = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case.id in only_ids]
        missing = only_ids - {case.id for case in cases}
        if missing:
            print(
                f"⚠️  --only 指定的 case 不存在或在当前 mode 不可用: {sorted(missing)}"
            )
    if not cases:
        parser.error(f"No cases support mode={args.mode}")
    requires_knowledge_index = any(
        any(call.tool == "search_knowledge" for call in path)
        and not any(
            fault.tool == "search_knowledge"
            and fault.type in {"tool_error", "empty_result"}
            and fault.trigger_call == 1
            for fault in case.run.faults
        )
        for case in cases
        for path in case.expected.tool_paths
    )
    snapshot_errors = knowledge_snapshot_errors(
        require_index=requires_knowledge_index
    )
    if snapshot_errors:
        parser.error("; ".join(snapshot_errors))

    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    reports = []
    for index in range(args.runs):
        print(f"[run {index + 1}/{args.runs}] {len(cases)} cases, mode={args.mode}")
        evaluator = Evaluator(
            runner=EvaluationRunner(mode=args.mode),
            client=client,
            model=settings.eval_judge_model,
            use_judge=args.judge,
            diagnostics=args.diagnostics,
        )
        reports.append(evaluator.run_all(cases))

    payload = _combine(reports, cases, args.runs)
    artifact_root = Path(args.artifact_dir)
    if not artifact_root.is_absolute():
        artifact_root = ROOT / artifact_root
    artifact_path = write_artifacts(payload, artifact_root)
    _print_summary(payload, artifact_path)

    gate_path = Path(args.gate_config) if args.gate_config else None
    if gate_path and not gate_path.is_absolute():
        gate_path = ROOT / gate_path
    failures = _gate_failures(payload, gate_path)
    if failures:
        print("\nGate failed:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
