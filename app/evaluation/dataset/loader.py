"""Dataset loading plus cross-reference validation."""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.tools.registry import TOOL_DEFINITIONS
from app.evaluation.dataset.schema import EvalCase, FSMDialogue, LLMDialogue
from app.evaluation.state import ALLOWED_FIELDS, ALLOWED_OPS, PRIMARY_KEYS, REGISTERED_SEEDS


POLICY_NAMES = {
    "refund_requires_confirmation",
    "refund_state_precondition",
    "no_logistics_on_pending",
    "knowledge_failure_requires_abstention",
}
SUITE_AUXILIARY_TOOLS = {"load_skill"}
CATEGORIES = {
    "C1", "C2", "C3", "C4", "C5", "C6", "C7",
    "MIXED",  # 混合 case 主类标 MIXED，由 covers 声明实际覆盖
}


def _validate_assertion(case: EvalCase, assertion) -> None:
    table = assertion.table
    op = assertion.op
    field = assertion.field
    where = assertion.where
    if table not in ALLOWED_FIELDS or op not in ALLOWED_OPS:
        raise ValueError(f"{case.id}: 非法状态断言 table={table}, op={op}")
    if not where or not set(where).issubset(ALLOWED_FIELDS[table]):
        raise ValueError(f"{case.id}: 状态断言 where 非法")
    if op == "eq" and field not in ALLOWED_FIELDS[table]:
        raise ValueError(f"{case.id}: 状态断言字段非法: {field}")


def validate_cases(cases: list[EvalCase], canonical_only: bool = False) -> None:
    tool_names = {item["function"]["name"] for item in TOOL_DEFINITIONS}
    ids: set[str] = set()
    skill_root = Path(__file__).resolve().parents[2] / "agent" / "skills" / "definitions"
    for case in cases:
        if case.id in ids:
            raise ValueError(f"重复 Case id: {case.id}")
        ids.add(case.id)
        if canonical_only and isinstance(case.dialogue, LLMDialogue):
            raise ValueError(f"{case.id}: Canonical 禁止运行时 LLM User Simulator")
        if case.run.seed_id not in REGISTERED_SEEDS:
            raise ValueError(f"{case.id}: 未注册 seed_id {case.run.seed_id}")

        referenced_tools = set(case.expected.forbidden_tools) | SUITE_AUXILIARY_TOOLS
        referenced_tools |= {
            call.tool for path in case.expected.tool_paths for call in path
        }
        referenced_tools |= {fault.tool for fault in case.run.faults}
        referenced_tools |= set(case.expected.required_tools)
        unknown = referenced_tools - tool_names
        if unknown:
            raise ValueError(f"{case.id}: 未知工具 {sorted(unknown)}")
        if "recall_user_memory" in referenced_tools:
            raise ValueError(f"{case.id}: Canonical 本轮不评测 memory")

        if case.meta.category not in CATEGORIES:
            raise ValueError(
                f"{case.id}: 未知能力类别 {case.meta.category}"
            )
        if case.meta.category == "MIXED" and not case.expected.covers:
            raise ValueError(f"{case.id}: MIXED case 必须声明 expected.covers")
        unknown_covers = set(case.expected.covers) - CATEGORIES
        if unknown_covers:
            raise ValueError(f"{case.id}: covers 含未知类别 {sorted(unknown_covers)}")
        if case.expected.required_tools and case.expected.order_constraint == "strict":
            # required_tools 与顺序强校验共存时可能自相矛盾，暂允许；C7 一般配 loose
            pass

        unknown_policies = set(case.expected.policies) - POLICY_NAMES
        if unknown_policies:
            raise ValueError(f"{case.id}: 未知 policy predicate {sorted(unknown_policies)}")
        if case.expected.sop_ref and not (
            skill_root / case.expected.sop_ref / "SKILL.md"
        ).exists():
            raise ValueError(f"{case.id}: SOP 不存在: {case.expected.sop_ref}")

        for table, records in case.run.initial_state_patch.items():
            if table not in ALLOWED_FIELDS or not isinstance(records, dict):
                raise ValueError(f"{case.id}: initial_state_patch 非法表或结构: {table}")
            for fields in records.values():
                if (
                    not isinstance(fields, dict)
                    or not fields
                    or not set(fields).issubset(ALLOWED_FIELDS[table])
                    or PRIMARY_KEYS[table] in fields
                ):
                    raise ValueError(f"{case.id}: initial_state_patch 包含非法字段")

        if isinstance(case.dialogue, FSMDialogue):
            if case.dialogue.start not in case.dialogue.states:
                raise ValueError(f"{case.id}: FSM start/state 非法")
            for state_name, node in case.dialogue.states.items():
                if "turn" not in node:
                    raise ValueError(f"{case.id}: FSM state {state_name} 缺少 turn")
                for transition in node.get("transitions", []):
                    target = transition.get("next")
                    if target is not None and target not in case.dialogue.states:
                        raise ValueError(
                            f"{case.id}: FSM transition 指向未知 state {target}"
                        )

        for assertion in case.expected.final_state:
            _validate_assertion(case, assertion)


def load_dataset(path: str | Path, canonical_only: bool = False) -> list[EvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in raw.get("cases", [])]
    validate_cases(cases, canonical_only=canonical_only)
    return cases
