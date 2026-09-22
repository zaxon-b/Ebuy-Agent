from collections import Counter

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import EvalCase, load_dataset, validate_cases


def _case(**overrides) -> EvalCase:
    value = {
        "meta": {
            "id": "case-1",
            "level": "Easy",
            "description": "minimal",
            "tags": [],
        },
        "run": {"modes": ["single"], "seed_id": "demo-v1", "user_id": "user-demo"},
        "dialogue": {
            "type": "static",
            "turns": [{"text": "你好", "acts": ["other"]}],
        },
        "expected": {"tool_paths": [[]], "reply": {}},
    }
    value.update(overrides)
    return EvalCase.model_validate(value)


def test_canonical_dataset_has_50_cases_with_category_axis():
    cases = load_dataset(
        "app/evaluation/dataset/canonical_cases.json", canonical_only=True
    )
    assert len(cases) == 50
    # 7 个能力类别 + MIXED 是数据集主轴
    assert Counter(case.meta.category for case in cases) == {
        "C1": 7, "C2": 6, "C3": 7, "C4": 5, "C5": 6, "C6": 6, "C7": 3, "MIXED": 10,
    }
    assert Counter(case.dialogue.type for case in cases) == {
        "static": 48,
        "fsm": 2,
    }
    assert len({c.id for c in cases}) == 50


def test_case_exposes_four_top_level_groups_only():
    case = _case()
    assert set(case.model_dump()) == {"meta", "run", "dialogue", "expected"}
    assert case.id == "case-1"
    with pytest.raises(ValidationError):
        EvalCase.model_validate({
            "id": "legacy-flat",
            "description": "old contract must not be accepted",
            "turns": ["你好"],
        })


def test_schema_rejects_deferred_state_change_fault():
    with pytest.raises(ValidationError):
        _case(run={
            "modes": ["single"],
            "seed_id": "demo-v1",
            "user_id": "user-demo",
            "faults": [{
                "type": "state_change",
                "tool": "query_order",
                "trigger_call": 1,
                "action": "mark_order_cancelled",
                "arguments": {"order_id": "ORD-20240120-002"},
            }],
        })


def test_canonical_rejects_runtime_llm_user_simulator():
    case = _case(dialogue={
        "type": "llm",
        "goal": "试探 Agent",
        "persona": "表达模糊的用户",
    })
    with pytest.raises(ValueError, match="Canonical 禁止"):
        validate_cases([case], canonical_only=True)
