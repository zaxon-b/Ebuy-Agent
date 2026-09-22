"""Canonical evaluation dataset models and validated loader."""

from app.evaluation.dataset.loader import load_dataset, validate_cases
from app.evaluation.dataset.schema import (
    CaseMeta,
    DialogueSpec,
    EmptyResultFault,
    EvalCase,
    ExpectedOutcome,
    ExpectedToolCall,
    FSMDialogue,
    FaultSpec,
    LLMDialogue,
    ResponseRubric,
    RunSpec,
    StateAssertion,
    StaticDialogue,
    ToolErrorFault,
    UserAct,
    UserTurn,
)

__all__ = [
    "CaseMeta", "DialogueSpec", "EmptyResultFault", "EvalCase", "ExpectedOutcome",
    "ExpectedToolCall", "FSMDialogue", "FaultSpec", "LLMDialogue", "ResponseRubric",
    "RunSpec", "StateAssertion", "StaticDialogue",
    "ToolErrorFault", "UserAct", "UserTurn",
    "load_dataset", "validate_cases",
]
