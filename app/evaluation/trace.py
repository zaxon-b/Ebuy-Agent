"""One auditable RunTrace containing raw Events and typed projections."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.schemas.response import CustomerServiceResponse


AUXILIARY_TOOLS: frozenset[str] = frozenset({"load_skill", "recall_user_memory"})
_SENSITIVE_KEY_RE = re.compile(
    r"^(api[_-]?key|apikey|token|secret|authorization|password|access[_-]?key)$",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


def redact_value(value):
    if hasattr(value, "model_dump"):
        return redact_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _SENSITIVE_KEY_RE.match(str(key)) else redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact_value(parsed), ensure_ascii=False)
    return value


@dataclass
class EventRecord:
    sequence: int
    kind: str
    payload: dict


@dataclass
class TurnRecord:
    turn_index: int
    text: str
    acts: list[str] = field(default_factory=list)


@dataclass
class LLMCallRecord:
    purpose: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    status: str = "success"
    error: str | None = None
    sequence: int = 0


@dataclass
class ToolObservation:
    name: str
    arguments: dict
    result: str
    description: str | None = None
    turn_index: int | None = None
    step_index: int | None = None
    status: str = "success"
    latency_ms: float = 0.0
    state_before: dict = field(default_factory=dict)
    state_after: dict = field(default_factory=dict)
    error: str | None = None
    sequence: int = 0

    @property
    def parsed_result(self) -> dict:
        try:
            value = json.loads(self.result)
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}


@dataclass
class FaultRecord:
    fault_type: str
    tool: str
    phase: str
    call_number: int
    payload: dict = field(default_factory=dict)
    sequence: int = 0


@dataclass
class RunTrace:
    case_id: str
    events: list[EventRecord] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    tool_observations: list[ToolObservation] = field(default_factory=list)
    fault_events: list[FaultRecord] = field(default_factory=list)
    route: str | None = None
    initial_state: dict = field(default_factory=dict)
    final_state: dict = field(default_factory=dict)
    final_response: Optional["CustomerServiceResponse"] = None
    metadata: dict = field(default_factory=dict)
    end_to_end_latency_ms: float = 0.0
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.llm_calls)

    @property
    def num_llm_calls(self) -> int:
        return len(self.llm_calls)

    @property
    def num_tool_calls(self) -> int:
        return len(self.tool_observations)

    @property
    def num_business_tool_calls(self) -> int:
        return len(self.business_tool_call_names)

    @property
    def tool_call_names(self) -> list[str]:
        return [observation.name for observation in self.tool_observations]

    @property
    def business_tool_call_names(self) -> list[str]:
        return [name for name in self.tool_call_names if name not in AUXILIARY_TOOLS]

    @property
    def num_tool_errors(self) -> int:
        return sum(observation.status == "error" for observation in self.tool_observations)

    @property
    def tool_success_rate(self) -> float | None:
        if not self.tool_observations:
            return None
        return 1.0 - self.num_tool_errors / len(self.tool_observations)

    @property
    def final_reply(self) -> str:
        return self.final_response.reply if self.final_response else ""

    def tool_events(self, name: str | None = None) -> list[ToolObservation]:
        if name is None:
            return list(self.tool_observations)
        return [item for item in self.tool_observations if item.name == name]

    def has_user_act_before(self, act: str, tool_event: ToolObservation) -> bool:
        tool_turn = tool_event.turn_index if tool_event.turn_index is not None else -1
        return any(
            record.turn_index <= tool_turn and act in record.acts
            for record in self.turns
        )

    def core_summary(self) -> dict:
        state_changes = [
            item for item in self.tool_observations if item.state_before != item.state_after
        ]
        return {
            "case_id": self.case_id,
            "turns": len(self.turns),
            "tool_path": self.tool_call_names,
            "tool_status": [item.status for item in self.tool_observations],
            "state_change_count": len(state_changes),
            "reply": self.final_reply,
            "tokens": self.total_tokens,
            "latency_ms": round(self.end_to_end_latency_ms, 1),
            "error": self.error,
        }

    def to_dict(self) -> dict:
        response = self.final_response
        return redact_value({
            "case_id": self.case_id,
            "turns": [asdict(item) for item in self.turns],
            "route": self.route,
            "reply": response.reply if response else None,
            "intent": response.intent.value if response else None,
            "requires_human": response.requires_human if response else None,
            "total_tokens": self.total_tokens,
            "num_llm_calls": self.num_llm_calls,
            "num_tool_calls": self.num_tool_calls,
            "num_business_tool_calls": self.num_business_tool_calls,
            "num_tool_errors": self.num_tool_errors,
            "tool_success_rate": self.tool_success_rate,
            "llm_calls": [asdict(item) for item in self.llm_calls],
            "tool_calls": [asdict(item) for item in self.tool_observations],
            "fault_events": [asdict(item) for item in self.fault_events],
            "events": [asdict(item) for item in self.events],
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "metadata": self.metadata,
            "core_summary": self.core_summary(),
            "end_to_end_latency_ms": round(self.end_to_end_latency_ms, 1),
            "error": self.error,
        })
