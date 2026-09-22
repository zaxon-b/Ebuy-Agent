"""Generate a trace-backed, per-case Eval V2 audit report.

The report deliberately keeps raw evaluation results separate from the manual
adjudication in adjusted_scores.json.  It is intended to answer, for every
case/run: what was specified, what the agent actually did, why the evaluator
failed it, which rule applies, and which metrics were affected.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1].parent
DATASET = ROOT / "app/evaluation/dataset/canonical_cases.json"
SINGLE_DIR = ROOT / "artifacts/eval/20260904-104253"
MULTI_DIR = ROOT / "artifacts/eval/20260905-024018"
ADJUSTED = ROOT / "artifacts/eval/adjusted_scores.json"
OUT = ROOT / "eval_v2/CASE_AUDIT_codex.md"


CATEGORY_NAMES = {
    "C1": "工具调用正确性",
    "C2": "回答忠实度",
    "C3": "业务红线",
    "C4": "数据库终态",
    "C5": "故障韧性",
    "C6": "多轮协议",
    "C7": "SOP 获取与遵从",
    "MIXED": "混合综合",
}

CORE_METRICS = (
    ("task_success", "task_success"),
    ("tool_correctness", "tool_correctness"),
    ("policy_compliance", "policy_compliance"),
    ("faithfulness", "faithfulness"),
    ("response_contract", "response_contract"),
    ("final_state_accuracy", "final_state_accuracy"),
)
DIAGNOSTIC_METRICS = (
    ("tool_recall", "tool_recall"),
    ("tool_precision", "tool_precision"),
    ("tool_f1", "tool_f1"),
    ("forbidden_rate", "forbidden_rate"),
    ("tool_efficiency", "tool_efficiency"),
)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compact(value, limit: int = 420) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text or "（空）"


def fmt_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def quoted(text, limit: int = 280) -> str:
    if text is None:
        return "（无最终回复）"
    text = compact(text, limit)
    return f"“{text}”"


def format_call(call: dict) -> str:
    name = call.get("name", "?")
    args = call.get("arguments", {})
    return f"{name}({compact(args, 180)})"


def format_expected_call(call: dict) -> str:
    name = call.get("tool", "?")
    args = call.get("arguments", {})
    return f"{name}({compact(args, 180)})"


def trace_error(trace: dict) -> str | None:
    errors = []
    if trace.get("error"):
        errors.append(str(trace["error"]))
    for llm in trace.get("llm_calls", []):
        if llm.get("status") != "success" and llm.get("error"):
            errors.append(str(llm["error"]))
    return "；".join(dict.fromkeys(errors)) or None


def dialogue_text(dialogue: dict) -> str:
    if dialogue.get("type") == "static":
        turns = dialogue.get("turns", [])
        return "；".join(
            f"T{i}: {t.get('text', '')}"
            + (f"（acts={','.join(t.get('acts', []))}）" if t.get("acts") else "")
            for i, t in enumerate(turns, 1)
        )
    parts = []
    for state, spec in dialogue.get("states", {}).items():
        turn = spec.get("turn", {})
        text = f"{state}: {turn.get('text', '')}"
        if turn.get("acts"):
            text += f"（acts={','.join(turn['acts'])}）"
        transitions = spec.get("transitions", [])
        if transitions:
            text += "；transitions=" + ",".join(
                f"{t.get('when')}→{t.get('next')}" for t in transitions
            )
        parts.append(text)
    return "；".join(parts)


def format_paths(expected: dict) -> str:
    paths = expected.get("tool_paths") or [[]]
    rendered = []
    for path in paths:
        if not path:
            rendered.append("（无业务工具调用）")
            continue
        rendered.append(" → ".join(format_expected_call(call) for call in path))
    return " / ".join(rendered)


def format_reply_contract(reply: dict) -> str:
    bits = []
    if reply.get("must_include_facts"):
        bits.append("must_include=" + json.dumps(reply["must_include_facts"], ensure_ascii=False))
    if reply.get("must_not_claim"):
        bits.append("must_not_claim=" + json.dumps(reply["must_not_claim"], ensure_ascii=False))
    if reply.get("required_abstention"):
        bits.append("required_abstention=true")
        if reply.get("abstention_patterns"):
            bits.append("abstention_patterns=" + json.dumps(reply["abstention_patterns"], ensure_ascii=False))
    if reply.get("forbidden_claim_patterns"):
        bits.append("forbidden_claim_patterns=" + json.dumps(reply["forbidden_claim_patterns"], ensure_ascii=False))
    if reply.get("expected_clarification") is not None:
        bits.append(f"expected_clarification={reply['expected_clarification']}")
    if reply.get("expected_requires_human") is not None:
        bits.append(f"expected_requires_human={reply['expected_requires_human']}")
    return "；".join(bits) or "（无额外回复字面/行为断言）"


def format_faults(faults: list[dict]) -> str:
    return compact(faults, 900) if faults else "无"


def rule_contract(case: dict) -> list[str]:
    meta = case["meta"]
    run = case["run"]
    expected = case["expected"]
    reply = expected.get("reply", {})
    lines = [
        f"- Agent 可见/关联 SOP：`{expected.get('sop_ref') or '—'}`；dataset rule_sources={compact(meta.get('rule_sources') or {}, 360)}",
        f"- 评测器期望路径（含参数）：`{format_paths(expected)}`；order_constraint=`{expected.get('order_constraint') or '—'}`",
        f"- 评测器禁用工具：`{json.dumps(expected.get('forbidden_tools') or [], ensure_ascii=False)}`；required_tools=`{json.dumps(expected.get('required_tools') or [], ensure_ascii=False)}`；extendable_tools=`{json.dumps(expected.get('extendable_tools') or [], ensure_ascii=False)}`",
        f"- 回复契约：{format_reply_contract(reply)}",
        f"- policy 谓词：`{json.dumps(expected.get('policies') or [], ensure_ascii=False)}`；final_state 断言：`{compact(expected.get('final_state') or [], 600)}`",
        f"- 故障注入：`{format_faults(run.get('faults') or [])}`",
    ]
    return lines


def metric_line(row: dict, only_failed: bool = False) -> str:
    values = []
    for key, label in CORE_METRICS + DIAGNOSTIC_METRICS:
        source = row.get("core", {}).get(key) if key in {x[0] for x in CORE_METRICS} else row.get("diagnostics", {}).get(key)
        if source is None:
            continue
        if only_failed and source in (1, 1.0):
            continue
        values.append(f"{label}={fmt_value(source)}")
    return "、".join(values) or "（无可用数值）"


def affected_metrics(row: dict) -> str:
    failures = set(row.get("failure_types") or [])
    affected = {"task_success"}
    mapping = {
        "tool_argument_error": {"tool_correctness"},
        "planning_or_order_error": {"tool_correctness"},
        "response_contract_error": {"response_contract"},
        "policy_violation": {"policy_compliance"},
        "hallucination_or_contradiction": {"faithfulness"},
        "unverifiable_without_valid_abstention": {"faithfulness"},
        "runtime_error": {"completion/runtime"},
    }
    for failure in failures:
        affected.update(mapping.get(failure, {failure}))
    if row.get("state_mismatches"):
        affected.add("final_state_accuracy")
    return ", ".join(sorted(affected))


def audit_affected_metrics(entry: dict | None, row: dict) -> str:
    """Metrics affected by an audit-only override, including raw PASS漏检."""
    if not entry:
        return affected_metrics(row)
    what = entry.get("what") or entry.get("why") or ""
    affected = set()
    if "第8条" in what or "相对" in what:
        affected.update({"policy_compliance", "response_contract"})
    if "第9条" in what or "重试顺序" in what:
        affected.update({"tool_correctness", "tool_efficiency"})
    if "取消状态" in what or "退款" in what and "真缺陷" in what:
        affected.update({"policy_compliance", "faithfulness"})
    if "规划" in what or "品类" in what or "能力" in what:
        affected.update({"tool_correctness", "task_success"})
    if not affected:
        return affected_metrics(row)
    affected.add("task_success")
    return ", ".join(sorted(affected))


def raw_reason(row: dict, trace: dict) -> str:
    parts = []
    if row.get("tool_details", {}).get("reasons"):
        parts.append("tool=" + "; ".join(row["tool_details"]["reasons"]))
    if row.get("response_reasons"):
        parts.append("response=" + "; ".join(row["response_reasons"]))
    if row.get("policy_details"):
        parts.append("policy=" + compact(row["policy_details"], 480))
    if row.get("state_mismatches"):
        parts.append("state=" + compact(row["state_mismatches"], 480))
    if row.get("judge_reasons", {}).get("faithfulness"):
        parts.append("judge=" + row["judge_reasons"]["faithfulness"])
    if not row.get("complete"):
        parts.append("runtime=" + (trace_error(trace) or str(row.get("error") or "未记录")))
    return "；".join(parts) or "（评测器未提供细分原因）"


def actual_path(trace: dict, row: dict) -> str:
    calls = trace.get("tool_calls") or []
    if calls:
        return " → ".join(format_call(call) for call in calls)
    path = row.get("tool_details", {}).get("actual_path") or []
    return " → ".join(path) if path else "（无工具调用）"


def actual_output(trace: dict, limit: int = 280) -> str:
    reply = trace.get("reply")
    if reply is not None and str(reply).strip():
        return quoted(reply, limit)
    err = trace_error(trace)
    if err:
        return f"（无最终回复；trace 中断：{compact(err, 500)}）"
    return "（空回复）"


def rule_requirement(expected: dict) -> str:
    reply = expected.get("reply", {})
    bits = [f"路径 `{format_paths(expected)}`"]
    forbidden = expected.get("forbidden_tools") or []
    required = expected.get("required_tools") or []
    policies = expected.get("policies") or []
    if forbidden:
        bits.append("不得调用 " + json.dumps(forbidden, ensure_ascii=False))
    if required:
        bits.append("必须调用 " + json.dumps(required, ensure_ascii=False))
    if policies:
        bits.append("必须满足 policy=" + json.dumps(policies, ensure_ascii=False))
    bits.append("回复契约：" + format_reply_contract(reply))
    return "；".join(bits)


def decision_map() -> dict[tuple[str, str, int], dict]:
    data = json.loads(ADJUSTED.read_text(encoding="utf-8"))
    return {
        (mode, entry["case"], entry["run"]): entry
        for mode in ("single", "multi")
        for entry in data.get("audit", {}).get(mode, [])
    }


def expanded_what(
    mode: str,
    case_id: str,
    run_index: int,
    decisions: dict[tuple[str, str, int], dict],
) -> str:
    entry = decisions.get((mode, case_id, run_index))
    if not entry:
        return "（未找到人工裁决条目；以下仅依据原始 trace 和 evaluator 输出）"
    what = entry.get("what") or entry.get("why") or "（未提供）"
    if what.startswith("同 r") or what.startswith("同 single"):
        for prior in range(run_index - 1, 0, -1):
            prior_entry = decisions.get((mode, case_id, prior))
            prior_what = prior_entry.get("what") if prior_entry else None
            if prior_what and not prior_what.startswith("同 r") and not prior_what.startswith("同 single"):
                return f"{what}；参照前一轮具体归因：{prior_what}"
    return what


def adjudication_text(
    mode: str,
    case_id: str,
    run_index: int,
    row: dict,
    decisions: dict[tuple[str, str, int], dict],
) -> tuple[str, str]:
    entry = decisions.get((mode, case_id, run_index))
    if row.get("passed") and row.get("complete"):
        if entry and entry.get("decision") == "KEEP_FAIL":
            return "KEEP_FAIL", "原始评测漏检，审计保留为 Agent/系统真缺陷：" + expanded_what(mode, case_id, run_index, decisions)
        if entry and entry.get("decision") == "FLIP":
            return "FLIP", "原始 PASS 的人工复核修正：" + expanded_what(mode, case_id, run_index, decisions)
        return "PASS", "原始评测通过，无需人工翻转。"
    if not entry:
        return "UNRESOLVED", "没有对应人工裁决；不擅自修改原始结果。"
    decision = entry.get("decision", "UNRESOLVED")
    if decision == "FLIP":
        if not row.get("complete"):
            return "FLIP", "基础设施中断，不归因于 Agent；具体错误见本轮中断证据。"
        return "FLIP", "测量层/基础设施误罚：" + expanded_what(mode, case_id, run_index, decisions)
    if decision == "KEEP_FAIL":
        return "KEEP_FAIL", "保留为 Agent/系统真缺陷：" + expanded_what(mode, case_id, run_index, decisions)
    if decision == "FILL_ASSUM":
        return "ASSUMED_PASS", "原始轮次未实测，既有裁决按 402/timeout 假设通过；本报告不把它当实测通过。"
    return decision, expanded_what(mode, case_id, run_index, decisions)


def case_dot(
    case_id: str,
    raw: dict[str, dict[tuple[str, int], dict]],
    decisions: dict[tuple[str, str, int], dict],
) -> str:
    """Return a title dot based on all available mode/run evidence for a case."""
    rows = [
        row
        for mode in ("single", "multi")
        for (cid, _), row in raw[mode].items()
        if cid == case_id
    ]
    if not rows:
        return '<span style="color:#D32F2F">●</span>'
    # 原始 PASS 也可能是 evaluator 漏检的 Agent 缺陷；先检查审计覆盖。
    for mode in ("single", "multi"):
        for (cid, run_index), row in raw[mode].items():
            if cid != case_id or not (row.get("complete") and row.get("passed")):
                continue
            entry = decisions.get((mode, case_id, run_index))
            if entry and entry.get("decision") == "KEEP_FAIL":
                return '<span style="color:#D32F2F">●</span>'
    if all(row.get("complete") and row.get("passed") for row in rows):
        return '<span style="color:#00C853">●</span>'
    for mode in ("single", "multi"):
        for (cid, run_index), row in raw[mode].items():
            if cid != case_id or (row.get("complete") and row.get("passed")):
                continue
            entry = decisions.get((mode, case_id, run_index))
            if not entry or entry.get("decision") == "KEEP_FAIL":
                return '<span style="color:#D32F2F">●</span>'
    return '<span style="color:#A5D6A7">●</span>'


def status_label(row: dict) -> str:
    if row.get("complete") and row.get("passed"):
        return "✅ RAW PASS"
    if row.get("complete"):
        return "❌ RAW FAIL"
    return "⚪ RAW INCOMPLETE"


def write_case_runs(
    lines: list[str],
    case_id: str,
    mode: str,
    rows: dict[tuple[str, int], dict],
    traces: dict[str, dict],
    decisions: dict[tuple[str, str, int], dict],
) -> None:
    mode_cn = "single agent" if mode == "single" else "multi agent"
    lines.append(f"#### {mode_cn}")
    for run_index in (1, 2, 3):
        row = rows.get((case_id, run_index))
        if not row:
            lines.append(f"- `run{run_index}` — **N/A（该模式未执行此 case）**")
            continue
        trace = traces.get(row["trace_id"], {})
        entry = decisions.get((mode, case_id, run_index))
        decision, adjudication = adjudication_text(mode, case_id, run_index, row, decisions)
        lines.append(
            f"- `run{run_index}` {status_label(row)}；审计裁决：**{decision}**；"
            f"failure_types=`{json.dumps(row.get('failure_types') or [], ensure_ascii=False)}`"
        )
        lines.append(f"  - 实际工具轨迹：`{actual_path(trace, row)}`")
        lines.append(f"  - Agent 最终输出：{actual_output(trace)}")
        lines.append(f"  - 原始核心指标：{metric_line(row)}")
        if not row.get("complete"):
            lines.append(f"  - 中断证据：`{compact(trace_error(trace) or row.get('error') or '未记录', 600)}`")
            lines.append("  - 解释：该轮没有可审计的完整最终回复；任何 0/null 指标只能归因于运行未完成，不能归因于 Agent 能力。")
        elif not row.get("passed"):
            lines.append(f"  - Agent 实际 A：{actual_output(trace, 900)}；实际调用为 `{actual_path(trace, row)}`")
            lines.append("  - 规则要求 B：" + rule_requirement(row.get("_expected", {})))
            lines.append(f"  - 原始失败证据：{compact(raw_reason(row, trace), 900)}")
            lines.append(f"  - 失败归因：{adjudication}")
            lines.append(f"  - 影响指标：`{affected_metrics(row)}`；原始受损值：{metric_line(row, only_failed=True)}")
        elif decision == "KEEP_FAIL":
            lines.append(f"  - Agent 实际 A：{actual_output(trace, 900)}；实际调用为 `{actual_path(trace, row)}`")
            lines.append("  - 规则要求 B：" + rule_requirement(row.get("_expected", {})))
            lines.append(f"  - 原始评测漏检证据：{compact(expanded_what(mode, case_id, run_index, decisions), 1000)}")
            lines.append(f"  - 失败归因：{adjudication}")
            lines.append(f"  - 影响指标：`{audit_affected_metrics(entry, row)}`；原始指标虽为 PASS，但该维度应视为审计不通过")
        else:
            diagnostic = []
            if row.get("failure_types"):
                diagnostic.append("failure_types=" + json.dumps(row["failure_types"], ensure_ascii=False))
            if row.get("core", {}).get("faithfulness_verdict") not in (None, "supported"):
                diagnostic.append("faithfulness_verdict=" + str(row["core"].get("faithfulness_verdict")))
            if diagnostic:
                lines.append(f"  - 原始评测通过，但诊断字段存在未闭合信号（不改变本轮 PASS）：`{'；'.join(diagnostic)}`；需修复 evaluator 的内部一致性")
            else:
                lines.append(f"  - 原始失败证据：无；工具/回复/策略检查均通过。")


def build_report() -> str:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = {case["meta"]["id"]: case for case in dataset["cases"]}
    raw = {}
    traces = {}
    for mode, directory in (("single", SINGLE_DIR), ("multi", MULTI_DIR)):
        rows = load_jsonl(directory / "cases.jsonl")
        raw[mode] = {(row["case_id"], row["run_index"]): row for row in rows}
        traces[mode] = {
            item["trace_id"]: item.get("trace", {})
            for item in load_jsonl(directory / "traces.jsonl")
        }
    decisions = decision_map()

    for mode in ("single", "multi"):
        for (case_id, _), row in raw[mode].items():
            row["_expected"] = cases[case_id]["expected"]

    raw_counts = {}
    for mode in ("single", "multi"):
        rows = list(raw[mode].values())
        raw_counts[mode] = {
            "total": len(rows),
            "complete": sum(bool(r.get("complete")) for r in rows),
            "passed": sum(bool(r.get("complete") and r.get("passed")) for r in rows),
            "failed": sum(bool(r.get("complete") and not r.get("passed")) for r in rows),
            "incomplete": sum(not r.get("complete") for r in rows),
        }
    audit_counts = Counter()
    raw_pass_audit_counts = Counter()
    for (mode, _, _), entry in decisions.items():
        audit_counts[(mode, entry.get("decision"))] += 1
        if entry.get("raw_status") == "PASS":
            raw_pass_audit_counts[(mode, entry.get("decision"))] += 1

    effective_counts = {}
    for mode in ("single", "multi"):
        complete_rows = [r for r in raw[mode].values() if r.get("complete")]
        effective_pass = 0
        effective_keep = 0
        for row in complete_rows:
            entry = decisions.get((mode, row["case_id"], row["run_index"]))
            if row.get("passed"):
                is_pass = not (entry and entry.get("decision") == "KEEP_FAIL")
            else:
                is_pass = bool(entry and entry.get("decision") == "FLIP")
            if is_pass:
                effective_pass += 1
            else:
                effective_keep += 1
        effective_counts[mode] = {"complete": len(complete_rows), "pass": effective_pass, "keep": effective_keep}

    lines = [
        "# Eval V2 · CASE_AUDIT_codex（逐 case / 逐轮原始审计）",
        "",
        "> 本报告由原始 `cases.jsonl`、`traces.jsonl`、canonical case 定义和既有人工裁决生成。原始评测结果与人工审计结论分栏展示，不把修正分数伪装成实测分数。",
        "> 数据范围：single `artifacts/eval/20260904-104253`；multi `artifacts/eval/20260905-024018`。每个已执行 case 均列 `run1–run3`；没有执行的模式标记 N/A。",
        '> 标题颜色：<span style="color:#00C853">●</span> 鲜绿色=所有已执行轮次原始通过且没有审计漏检；<span style="color:#A5D6A7">●</span> 淡绿色=原始失败/中断但审计后无保留缺陷；<span style="color:#D32F2F">●</span> 红色=审计后仍有 KEEP_FAIL（包括原始 PASS 被审计发现的漏检）。',
        "> 状态：`RAW PASS`=原始评测通过；`RAW FAIL`=原始评测失败；`RAW INCOMPLETE`=没有完整最终回复。`FLIP`=审计认为测量层误罚；`KEEP_FAIL`=审计保留真缺陷；`ASSUMED_PASS`=既有裁决的未实测假设，不能当实测通过。",
        "> 规则口径：Agent 可见的系统纪律来自 `app/prompts/customer_service.py`（先查再答、退款须确认、检索失败克制、只复述工具绝对时间、持续故障不得绕查）；SOP 来自 `app/agent/skills/definitions/*/SKILL.md`；工具契约来自 `app/agent/tools/registry.py`。case 的 exact path / literal response contract 是评测器断言，不能自动等同于 Agent 可见规则。",
        "",
        "## 1. 执行总览",
        "",
        "| 模式 | 原始执行数 | 完成 | 原始通过 | 原始失败 | 未完成 | 完成后通过率 | 按全部执行数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in ("single", "multi"):
        count = raw_counts[mode]
        completed_rate = count["passed"] / count["complete"] if count["complete"] else 0
        execution_rate = count["passed"] / count["total"] if count["total"] else 0
        lines.append(
            f"| {mode} | {count['total']} | {count['complete']} | {count['passed']} | {count['failed']} | {count['incomplete']} | {completed_rate:.1%} | {execution_rate:.1%} |"
        )
    lines += [
        "",
        "### 1.1 审计裁决计数",
        "",
        "| 模式 | FLIP（原始 FAIL 的测量/基础设施误罚） | KEEP_FAIL（原始 FAIL 真缺陷） | ASSUMED_PASS（未实测） | 原始 PASS 漏检后 KEEP_FAIL |",
        "|---|---:|---:|---:|---:|",
        f"| single | {audit_counts[('single', 'FLIP')] - raw_pass_audit_counts[('single', 'FLIP')]} | {audit_counts[('single', 'KEEP_FAIL')] - raw_pass_audit_counts[('single', 'KEEP_FAIL')]} | {audit_counts[('single', 'FILL_ASSUM')]} | {raw_pass_audit_counts[('single', 'KEEP_FAIL')]} |",
        f"| multi | {audit_counts[('multi', 'FLIP')] - raw_pass_audit_counts[('multi', 'FLIP')]} | {audit_counts[('multi', 'KEEP_FAIL')] - raw_pass_audit_counts[('multi', 'KEEP_FAIL')]} | {audit_counts[('multi', 'FILL_ASSUM')]} | {raw_pass_audit_counts[('multi', 'KEEP_FAIL')]} |",
        "",
        "### 1.2 审计后的完成轮次口径",
        "",
        "这里把原始 PASS 漏检的 KEEP_FAIL 扣除，把原始 FAIL 的 FLIP 加回；未完成轮次不计入通过率。",
        "",
        "| 模式 | 完成轮次 | 审计后通过 | 审计后 KEEP_FAIL | 审计后完成通过率 |",
        "|---|---:|---:|---:|---:|",
        f"| single | {effective_counts['single']['complete']} | {effective_counts['single']['pass']} | {effective_counts['single']['keep']} | {effective_counts['single']['pass'] / effective_counts['single']['complete']:.1%} |",
        f"| multi | {effective_counts['multi']['complete']} | {effective_counts['multi']['pass']} | {effective_counts['multi']['keep']} | {effective_counts['multi']['pass'] / effective_counts['multi']['complete']:.1%} |",
        "",
        "说明：multi run3 的 11 个 case 因 API 402 `Insufficient Balance` 中断；multi run2 的 `v2_m_m8`、`v2_m_m9` 因 timeout 中断。single run3 的 `v2_c6_t37` 因 `APIConnectionError` 中断。报告逐轮保留这些原始事实。",
        "",
        "## 2. 逐 case 审计",
        "",
    ]

    ordered_ids = sorted(cases, key=lambda cid: (cases[cid]["meta"].get("category", ""), cid))
    for case_id in ordered_ids:
        case = cases[case_id]
        meta = case["meta"]
        expected = case["expected"]
        lines += [
            f"### {case_dot(case_id, raw, decisions)} {case_id} · [{meta.get('category')} {CATEGORY_NAMES.get(meta.get('category'), '')}] {meta.get('description', '')}",
            "",
            f"- case 定义：level=`{meta.get('level')}`，difficulty_score=`{meta.get('difficulty_score')}`，dialogue=`{case.get('dialogue', {}).get('type')}`，tags=`{json.dumps(meta.get('tags') or [], ensure_ascii=False)}`",
            f"- 用户对话：{dialogue_text(case.get('dialogue', {}))}",
            *rule_contract(case),
            "",
            "#### 逐轮原始结果",
        ]
        for mode in ("single", "multi"):
            write_case_runs(lines, case_id, mode, raw[mode], traces[mode], decisions)
            lines.append("")

    lines += [
        "## 3. 读法与审计边界",
        "",
        "1. `failure_types` 和核心指标来自原始 evaluator；它们回答“评测器判了什么”。",
        "2. `Agent 最终输出`、实际工具调用和 runtime 错误来自同一轮 trace；它们回答“Agent 实际做了什么”。",
        "3. `规则要求 B` 同时受 case contract 与 Agent 可见 SOP/系统纪律约束；当 exact path 或 exact literal 比 Agent 可见规则更窄时，人工归因标为 FLIP，而不是把 Agent 的合规行为判成能力缺陷。",
        "4. `KEEP_FAIL` 代表审计后仍有可由 Agent/多 Agent 编排修复的行为问题，例如能力否认、相对日期过度承诺、确认前退款、持续故障时绕工具或无依据断言。",
        "5. 未完成轮只记录运行中断和指标影响，不根据邻近轮次推断 Agent 输出。既有 `ASSUMED_PASS` 只保留为外部裁决标签。",
        "",
        "## 4. Agent 真缺陷的原因分类与优化方案",
        "",
        "以下只归纳审计后的 `KEEP_FAIL`，不把 FLIP 的评测器误罚混入 Agent 缺陷统计。",
        "",
        "| 原因类别 | 典型表现（A） | 规则要求（B） | Agent 优化方案 |",
        "|---|---|---|---|",
        "| 相对时间违规 | 已有工具绝对日期后仍说‘今天/明天/马上/很快’ | SYSTEM_PROMPT 第8条只复述工具返回的具体日期/时间 | 在最终回复前增加时间表达扫描；将相对词替换为工具原文绝对日期，无法映射时删除承诺。 |",
        "| 故障重试顺序错误 | query_order 504 后先查 logistics，之后才重试 | SYSTEM_PROMPT 第9条 504/5xx 必须先用相同参数重试一次 | 工具异常进入 retry 状态机；未完成 retry 前禁止推进后续工具；增加顺序断言测试。 |",
        "| 多 Agent 能力/路由不匹配 | 商品问题被 postsale 接管并声称没有 query_product | 选中的子 Agent 必须使用其实际可用工具完成意图 | 路由结果与工具白名单绑定；路由失败不要静默 fallback 到无关 Agent；对能力否认做回归集。 |",
        "| 证据外推/品类混淆 | 将 AirPods 的白色结果当成白色运动鞋，或补写工具未返回颜色 | 只复述当前工具证据，不把相邻品类/历史信息拼接成事实 | 回复槽位绑定到 tool result 的 product_id/类别；生成前逐字段做 evidence check。 |",
        "| 业务状态处理错误 | cancelled 订单仍引导再次发起退款 | 已取消/已退款订单不得重复退款；敏感操作须确认且先看状态 | 在退款前先运行状态决策表；cancelled/refunded 直接解释现状和到账核查，不进入 apply_refund 流程。 |",
        "| SOP/最终回答未完成 | 查到 shipped 后只说继续查，或查到会员政策却只说再查会员等级 | 完成当前意图的状态分流、事实报告和下一步建议 | 为每个 SOP 建“完成条件”；最终回复前检查用户问题、必报事实、下一步是否齐全。 |",
        "| 工具规划冗余/越界 | 为一个颜色/品类意图连续发散多次 q_product，或查不到订单仍查物流 | product-recommend 只允许一次合理变体重搜；查不到订单不查物流 | 记录意图、已尝试查询和停止条件；每轮设置工具预算与 forbidden-tool guard。 |",
        "",
        "## 5. 评测器/判定层需要修正的方向",
        "",
        "- 同一语义在不同 run 被 Judge 一正一负（如 c1_t06 的‘黑色/未激活’），应改为证据字段对齐与跨 run 一致性检查，避免单次 LLM Judge 覆盖确定性事实。",
        "- literal keyword、exact tool path、结构化 requires_human 不应单独推翻符合 SOP 的语义结果；应把“字面覆盖不足”和“Agent 真违例”拆成不同指标。",
        "- multi evaluator 必须使用实际被路由子 Agent 的工具白名单；aggregate schema 会让能力否认/工具可用性判断失真。",
        "- 对原始 PASS 也执行 system-rule lint（尤其绝对日期）并保存 `audit_override`，避免 evaluator 只审 FAIL 导致漏检。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    OUT.write_text(report + "\n", encoding="utf-8")
    print(f"written {OUT} ({len(report.splitlines())} lines, {len(report)} chars)")
