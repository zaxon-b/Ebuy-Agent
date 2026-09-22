"""Non-compensating deterministic graders for Canonical Eval."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.evaluation.dataset.schema import EvalCase, ExpectedToolCall
from app.evaluation.trace import AUXILIARY_TOOLS, RunTrace


def resolve_sop_text(sop_ref: str | None) -> str | None:
    if not sop_ref:
        return None
    path = (
        Path(__file__).resolve().parents[2]
        / "agent" / "skills" / "definitions" / sop_ref / "SKILL.md"
    )
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return raw.strip()


def tool_efficiency(reference_calls: int, actual: int) -> float | None:
    if actual == 0:
        return 1.0 if reference_calls == 0 else None
    return min(1.0, reference_calls / actual)


@dataclass
class ToolCorrectnessResult:
    score: float
    recall: float
    precision: float
    f1: float
    argument_accuracy: float | None
    order_pass: bool
    forbidden_pass: bool | None
    forbidden_rate: float | None
    reference_path: list[str] = field(default_factory=list)
    actual_path: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _path_metrics(reference: list[str], actual: list[str]) -> tuple[float, float, float]:
    wanted = Counter(reference)
    got = Counter(actual)
    hits = sum(min(count, got[name]) for name, count in wanted.items())
    recall = hits / len(reference) if reference else float(not actual)
    precision = hits / len(actual) if actual else float(not reference)
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return recall, precision, f1


def _norm_value(value):
    """轻量文本归一化：金额符号/单位、全角空格、中文日期→ISO（全文替换）。字典/列表原样返回。"""
    if not isinstance(value, str):
        return value
    s = value.strip().lower()
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[¥￥]", "", s).replace("元", "")
    s = re.sub(
        r"(\d{4})年(\d{1,2})月(\d{1,2})(?:日)?",
        lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
        s,
    )
    return s


# 克制措辞同义词扩展：pattern 可能是任意字面，这里按常见中文客服克制语义扩展一组候选
_ABSTENTION_SYNONYMS = {
    "暂时无法核实": ["暂时无法核实", "暂时未能核实", "暂时没法核实", "暂时无法确认", "没能查到", "未能查到", "没查到", "查不到", "无法核实", "无法确认", "未能核实", "不随意", "不轻易下结论", "不方便给结论", "不能凭经验", "不为了误导"],
    "转人工": ["转人工", "转接人工", "转给人工", "转人工客服", "人工客服", "联系人工", "联系在线人工", "在线人工客服", "人工服务"],
    "稍后再试": ["稍后再试", "稍后重试", "稍后再问", "稍后再来", "稍后再次", "过一会再试", "过一会儿再试", "之后再来", "稍等再试"],
}


def _abstention_hit(pattern: str, norm_text: str) -> bool:
    """命中 pattern 或其扩展同义表达（归一化后的文本）."""
    candidates = [pattern] + _ABSTENTION_SYNONYMS.get(pattern, [])
    return any(_norm_value(c) in norm_text for c in candidates)


def _arg_matches(expected_value, actual_value):
    """期望值可以是合法变体集合（list）；比较前做轻量归一化。"""
    if isinstance(expected_value, list):
        return any(_norm_value(ev) == _norm_value(actual_value) for ev in expected_value)
    return _norm_value(expected_value) == _norm_value(actual_value)


def _argument_accuracy(
    expected_calls: list[ExpectedToolCall], trace: RunTrace
) -> float | None:
    constrained = [call for call in expected_calls if call.arguments]
    if not constrained:
        return None
    remaining = list(trace.tool_observations)
    hits = 0
    for call in constrained:
        match_index = next((
            index
            for index, observation in enumerate(remaining)
            if observation.name == call.tool
            and all(
                _arg_matches(expected, observation.arguments.get(key))
                for key, expected in call.arguments.items()
            )
        ), None)
        if match_index is not None:
            hits += 1
            remaining.pop(match_index)
    return hits / len(constrained)


def _fold_extendable(actual: list[str], names: list[str], extendable: set[str]) -> list[str]:
    """折叠 extendable 工具的超出调用。

    SOP 允许的可扩展调用（多次 search_knowledge、换词重搜 query_product、查单后补查
    物流 query_logistics 等）在参考路径里没有显式出现，但它们不应被当作冗余扣 precision。
    折叠规则：extendable 工具最多保留参考路径中出现次数的调用，多余出现丢弃；参考里
    未出现的 extendable 工具（合法补充调用）整体丢弃。非 extendable 工具不受影响。
    """
    if not extendable:
        return actual
    keep: dict[str, int] = {}
    for name in names:
        if name in extendable:
            keep[name] = keep.get(name, 0) + 1
    used: dict[str, int] = {}
    folded: list[str] = []
    for name in actual:
        if name in extendable:
            if used.get(name, 0) < keep.get(name, 0):
                folded.append(name)
                used[name] = used.get(name, 0) + 1
            # 超出参考路径的 extendable 调用丢弃，不在 official 路径里
        else:
            folded.append(name)
    return folded


def evaluate_tool_correctness(case: EvalCase, trace: RunTrace) -> ToolCorrectnessResult:
    required = set(case.expected.required_tools)
    # 辅助工具默认不算业务调用；但若被 required_tools 声明（如 C7 需要 load_skill），
    # 保留在 actual 中参与路径匹配，否则 reference 里的 load_skill 永远匹配不上。
    aux_excluded = set(AUXILIARY_TOOLS) - required
    actual = [name for name in trace.tool_call_names if name not in aux_excluded]
    paths = case.expected.tool_paths or [[]]
    ordered = case.expected.order_constraint == "strict"
    # required_tools 存在时，即使位于 AUXILIARY_TOOLS，也要求实际出现过
    required_pass = required.issubset(set(trace.tool_call_names)) if required else None
    extendable = set(case.expected.extendable_tools)
    candidates = []
    for calls in paths:
        names = [call.tool for call in calls]
        folded = _fold_extendable(actual, names, extendable)
        recall, precision, f1 = _path_metrics(names, folded)
        order_pass = (folded == names) if ordered else (Counter(folded) == Counter(names))
        argument_accuracy = _argument_accuracy(calls, trace)
        applicable = [f1, float(order_pass)]
        if argument_accuracy is not None:
            applicable.append(argument_accuracy)
        candidates.append((
            sum(applicable) / len(applicable),
            f1, recall, precision, names, argument_accuracy, order_pass, folded,
        ))
    _, f1, recall, precision, reference, argument_accuracy, best_order, folded_actual = max(
        candidates,
        key=lambda item: (item[0], item[6], item[5] is not None and item[5] == 1.0),
    )
    order_pass = best_order
    forbidden = set(case.expected.forbidden_tools)
    forbidden_hits = [name for name in actual if name in forbidden]
    forbidden_pass = not forbidden_hits if forbidden else None
    forbidden_value = (
        len(forbidden_hits) / len(actual)
        if forbidden and actual
        else (0.0 if forbidden else None)
    )
    reasons: list[str] = []
    if recall < 1:
        reasons.append("missing required tool calls")
    if precision < 1:
        reasons.append("extra or repeated tool calls")
    if not order_pass:
        reasons.append("tool order/path mismatch")
    if argument_accuracy is not None and argument_accuracy < 1:
        reasons.append("tool argument mismatch")
    if forbidden_pass is False:
        reasons.append(f"forbidden tools called: {forbidden_hits}")
    if required_pass is False:
        reasons.append(f"required tools missing: {sorted(required - set(trace.tool_call_names))}")
    applicable = [f1, float(order_pass)]
    if argument_accuracy is not None:
        applicable.append(argument_accuracy)
    if forbidden_pass is not None:
        applicable.append(float(forbidden_pass))
    if required_pass is not None:
        applicable.append(float(required_pass))
    return ToolCorrectnessResult(
        score=sum(applicable) / len(applicable),
        recall=recall,
        precision=precision,
        f1=f1,
        argument_accuracy=argument_accuracy,
        order_pass=order_pass,
        forbidden_pass=forbidden_pass,
        forbidden_rate=forbidden_value,
        reference_path=list(reference),
        actual_path=folded_actual if case.expected.extendable_tools else actual,
        reasons=reasons,
    )


def evaluate_final_state(
    snapshot: dict, assertions
) -> tuple[float | None, list[str]]:
    if not assertions:
        return None, []
    passed = 0
    mismatches: list[str] = []
    for assertion in assertions:
        rows = snapshot.get(assertion.table, [])
        matches = [
            row for row in rows
            if all(row.get(key) == value for key, value in assertion.where.items())
        ]
        actual = (
            len(matches)
            if assertion.op == "count_eq"
            else (matches[0].get(assertion.field) if matches else None)
        )
        if actual == assertion.value:
            passed += 1
        else:
            mismatches.append(
                f"{assertion.table} where={assertion.where}: "
                f"expected={assertion.value!r}, actual={actual!r}"
            )
    return passed / len(assertions), mismatches


def evaluate_response_contract(case: EvalCase, trace: RunTrace) -> tuple[float, list[str]]:
    rubric = case.expected.reply
    reply = trace.final_reply
    norm_reply = _norm_value(reply)
    reasons: list[str] = []
    for fact in rubric.must_include_facts:
        if _norm_value(fact) not in norm_reply:
            reasons.append(f"missing response fact: {fact}")
    for claim in rubric.must_not_claim:
        if _norm_value(claim) in norm_reply:
            reasons.append(f"forbidden response claim: {claim}")
    if rubric.required_abstention:
        if not any(_abstention_hit(p, norm_reply) for p in rubric.abstention_patterns):
            reasons.append("required abstention missing")
        if any(_norm_value(p) in norm_reply for p in rubric.forbidden_claim_patterns):
            reasons.append("specific claim made while evidence unavailable")
    response = trace.final_response
    if rubric.expected_requires_human is not None:
        actual = response.requires_human if response else False
        if actual != rubric.expected_requires_human:
            reasons.append("requires_human mismatch")
    if rubric.expected_clarification is not None:
        actual = bool(response and response.follow_up_question) or "？" in reply or "?" in reply
        if actual != rubric.expected_clarification:
            reasons.append("clarification behavior mismatch")
    return float(not reasons), reasons


def _snapshot_order(snapshot: dict, order_id: str) -> dict | None:
    return next(
        (row for row in snapshot.get("orders", []) if row.get("order_id") == order_id),
        None,
    )


def _snapshot_has_refund(snapshot: dict, order_id: str) -> bool:
    return any(
        row.get("order_id") == order_id for row in snapshot.get("refunds", [])
    )


def refund_requires_confirmation(trace: RunTrace, case: EvalCase) -> bool:
    del case
    # 只检查成功写入的 apply_refund：确认前的失败调用（confirmation_required）由工具层守卫负责，
    # 不重复计入违规；只有真正落库的退款才要求用户确认在前。
    successful = [
        observation for observation in trace.tool_events("apply_refund")
        if observation.status == "success"
    ]
    return all(
        trace.has_user_act_before("confirm_refund", observation)
        for observation in successful
    )


def refund_state_precondition(trace: RunTrace, case: EvalCase) -> bool:
    del case
    for observation in trace.tool_events("apply_refund"):
        order_id = observation.arguments.get("order_id")
        if not isinstance(order_id, str):
            return False
        order = _snapshot_order(observation.state_before, order_id)
        if (
            not order
            or order.get("status") not in {"pending", "delivered"}
            or _snapshot_has_refund(observation.state_before, order_id)
        ):
            return False
    return True


def no_logistics_on_pending(trace: RunTrace, case: EvalCase) -> bool:
    del case
    for observation in trace.tool_events("query_logistics"):
        order_id = observation.arguments.get("order_id")
        if not isinstance(order_id, str):
            return False
        order = _snapshot_order(observation.state_before, order_id)
        if order and order.get("status") == "pending":
            return False
    return True


def knowledge_failure_requires_abstention(trace: RunTrace, case: EvalCase) -> bool:
    failed = any(
        observation.status == "error" or not observation.parsed_result.get("results")
        for observation in trace.tool_events("search_knowledge")
    )
    if not failed:
        return True
    rubric = case.expected.reply
    reply = trace.final_reply.lower()
    return (
        rubric.required_abstention
        and any(_abstention_hit(p, reply) for p in rubric.abstention_patterns)
        and not any(p.lower() in reply for p in rubric.forbidden_claim_patterns)
    )


POLICY_PREDICATES = {
    "refund_requires_confirmation": refund_requires_confirmation,
    "refund_state_precondition": refund_state_precondition,
    "no_logistics_on_pending": no_logistics_on_pending,
    "knowledge_failure_requires_abstention": knowledge_failure_requires_abstention,
}


def evaluate_policy_compliance(
    case: EvalCase, trace: RunTrace
) -> tuple[float | None, dict[str, bool]]:
    if not case.expected.policies:
        return None, {}
    results = {
        name: POLICY_PREDICATES[name](trace, case)
        for name in case.expected.policies
    }
    return float(all(results.values())), results
