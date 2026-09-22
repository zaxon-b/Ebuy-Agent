"""Coverage views and four local artifacts for the Canonical benchmark."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def coverage_matrix(cases) -> dict:
    levels: dict[str, int] = {}
    tags: dict[str, int] = {}
    faults: dict[str, int] = {}
    categories: dict[str, int] = {}
    difficulty_buckets: dict[int, int] = {}
    for case in cases:
        levels[case.level] = levels.get(case.level, 0) + 1
        for tag in case.tags:
            tags[tag] = tags.get(tag, 0) + 1
        for fault in case.run.faults:
            faults[fault.type] = faults.get(fault.type, 0) + 1
        cat = case.meta.category
        categories[cat] = categories.get(cat, 0) + 1
        diff = case.meta.difficulty_score
        difficulty_buckets[diff] = difficulty_buckets.get(diff, 0) + 1
    return {
        "levels": levels,
        "categories": categories,
        "difficulty": difficulty_buckets,
        "execution_modes": {
            mode: sum(mode in case.modes for case in cases)
            for mode in ("single", "multi")
        },
        "simulators": {
            mode: sum(case.dialogue.type == mode for case in cases)
            for mode in ("static", "fsm", "llm")
        },
        "core_metrics": {
            "task_success": len(cases),
            "final_state_accuracy": sum(
                bool(case.expected.final_state) for case in cases
            ),
            "tool_correctness": len(cases),
            "policy_compliance": sum(
                bool(case.expected.policies) for case in cases
            ),
            "faithfulness": len(cases),
        },
        "tags": tags,
        "faults": faults,
    }


def _percent(value) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def markdown_report(payload: dict) -> str:
    summary = payload["summary"]
    reliability = payload.get("reliability") or {}
    attribution = payload.get("failure_attribution") or {}
    lines = [
        "# Canonical Eval Report",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Runs: {payload.get('runs', 1)}",
        f"- Complete cases: {summary.get('completed', 0)}/{summary.get('total', 0)}",
        f"- Task success: {_percent(summary.get('task_success'))}",
        f"- Final-state accuracy: {_percent(summary.get('final_state_accuracy'))}",
        f"- Tool correctness: {_percent(summary.get('tool_correctness'))}",
        f"- Policy compliance: {_percent(summary.get('policy_compliance'))}",
        f"- Faithfulness: {_percent(summary.get('faithfulness'))}",
        f"- pass@3: {_percent(reliability.get('pass_at_3'))}",
        f"- observed pass^3: {_percent(reliability.get('observed_pass_3'))}",
        "",
        "## Diagnostic and observability metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Response contract | {_percent(summary.get('response_contract'))} |",
        f"| Answer quality | {_percent(summary.get('answer_quality'))} |",
        f"| Process soundness | {_percent(summary.get('process_soundness'))} |",
        f"| Tool recall | {_percent(summary.get('tool_recall'))} |",
        f"| Tool precision | {_percent(summary.get('tool_precision'))} |",
        f"| Tool F1 | {_percent(summary.get('tool_f1'))} |",
        f"| Forbidden rate | {_percent(summary.get('forbidden_rate'))} |",
        f"| Tool efficiency | {_percent(summary.get('tool_efficiency'))} |",
        f"| Tool success rate | {_percent(summary.get('tool_success_rate'))} |",
        f"| Supported rate | {_percent(summary.get('supported_rate'))} |",
        f"| Average Agent tokens / Case | {summary.get('avg_tokens_per_case', 0):.1f} |",
        f"| Average business tool calls / Case | {summary.get('avg_tool_calls', 0):.2f} |",
        f"| Average total tool calls / Case | {summary.get('avg_total_tool_calls', 0):.2f} |",
        f"| Average LLM calls / Case | {summary.get('avg_llm_calls', 0):.2f} |",
        f"| Average Agent latency / Case (ms) | {summary.get('avg_latency_ms', 0):.1f} |",
        f"| Total Agent tokens | {summary.get('total_tokens', 0)} |",
        f"| Total turns | {summary.get('total_turns', 0)} |",
        f"| Total raw events | {summary.get('total_events', 0)} |",
        f"| Total LLM errors | {summary.get('total_llm_errors', 0)} |",
        f"| Total tool errors | {summary.get('total_tool_errors', 0)} |",
        f"| Total injected fault events | {summary.get('total_fault_events', 0)} |",
        f"| Total state changes | {summary.get('total_state_changes', 0)} |",
        f"| Runtime errors | {summary.get('runtime_errors', 0)} |",
        f"| Route distribution | `{json.dumps(summary.get('route_counts', {}), ensure_ascii=False)}` |",
        "",
        "## Failure attribution",
        "",
    ]
    if attribution:
        lines.extend(f"- {name}: {count}" for name, count in sorted(attribution.items()))
    else:
        lines.append("- No failures")
    lines.extend([
        "",
        "## Pass rate by ability category",
        "",
        "| Category | Cases | Passed | Rate |",
        "|---|---:|---:|---:|",
    ])
    cats: dict[str, list[bool]] = {}
    for case in payload.get("cases", []):
        cats.setdefault(case.get("category") or "C1", []).append(bool(case.get("passed")))
    for cat in sorted(cats):
        bucket = cats[cat]
        lines.append(
            f"| {cat} | {len(bucket)} | {sum(bucket)} | {_percent(sum(bucket) / len(bucket))} |"
        )
    lines.extend([
        "",
        "## Cases",
        "",
        "| Case | Category | Complete | Pass | Failure types |",
        "|---|---:|---|---:|---|",
    ])
    for case in payload.get("cases", []):
        failures = ", ".join(case.get("failure_types") or []) or "-"
        lines.append(
            f"| {case['case_id']} | {case.get('category') or 'C1'} | "
            f"{'yes' if case.get('complete') else 'no'} | "
            f"{'yes' if case.get('passed') else 'no'} | {failures} |"
        )
    return "\n".join(lines) + "\n"


def _json_line(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_artifacts(payload: dict, artifact_root: str | Path) -> Path:
    """Write exactly: summary.json, cases.jsonl, traces.jsonl and report.md."""

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(artifact_root) / run_id
    suffix = 1
    while target.exists():
        target = Path(artifact_root) / f"{run_id}-{suffix}"
        suffix += 1
    target.mkdir(parents=True, exist_ok=False)

    summary_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"cases", "run_cases"}
    }
    (target / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_cases = payload.get("run_cases") or [payload.get("cases", [])]
    case_lines: list[str] = []
    trace_lines: list[str] = []
    for run_index, cases in enumerate(run_cases, start=1):
        for case in cases:
            trace_id = f"run-{run_index}:{case['case_id']}"
            case_without_trace = {
                key: value for key, value in case.items() if key != "trace"
            }
            case_lines.append(_json_line({
                "run_index": run_index,
                "trace_id": trace_id,
                **case_without_trace,
            }))
            trace_lines.append(_json_line({
                "run_index": run_index,
                "trace_id": trace_id,
                "case_id": case["case_id"],
                "complete": case.get("complete", False),
                "passed": case.get("passed", False),
                "trace": case["trace"],
            }))
    (target / "cases.jsonl").write_text(
        "\n".join(case_lines) + ("\n" if case_lines else ""),
        encoding="utf-8",
    )
    (target / "traces.jsonl").write_text(
        "\n".join(trace_lines) + ("\n" if trace_lines else ""),
        encoding="utf-8",
    )
    (target / "report.md").write_text(markdown_report(payload), encoding="utf-8")
    return target
