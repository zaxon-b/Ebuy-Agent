"""Save complete Events and project their useful fields into one RunTrace."""

from __future__ import annotations

from app.agent.observability import Event
from app.evaluation.trace import (
    EventRecord,
    FaultRecord,
    LLMCallRecord,
    RunTrace,
    ToolObservation,
    TurnRecord,
    redact_value,
)


class Tracer:
    """A small Event-to-RunTrace projector with no lifecycle pairing state."""

    def __init__(self, case_id: str):
        self.trace = RunTrace(case_id=case_id)
        self._sequence = 0
        self._acts_by_turn: dict[int, list[str]] = {}

    def set_turn_contract(self, turn_index: int, text: str, acts: list[str]) -> None:
        self._acts_by_turn[turn_index] = list(acts)
        existing = next(
            (item for item in self.trace.turns if item.turn_index == turn_index),
            None,
        )
        if existing:
            existing.text = text
            existing.acts = list(acts)

    def has_user_act(self, act: str) -> bool:
        """True if any registered turn (contract or emitted) carries this user act.

        Used by the runtime refund-confirmation guard: the user's confirmed
        intent is ground truth from the dataset, not parsed from model output.
        """
        return any(act in acts for acts in self._acts_by_turn.values())

    def emit(self, item: object) -> None:
        if not isinstance(item, Event):
            return
        self._sequence += 1
        payload = dict(item.payload)
        self.trace.events.append(EventRecord(
            sequence=self._sequence,
            kind=item.kind,
            payload=redact_value(payload),
        ))

        if item.kind == "on_turn_start":
            self._project_turn(payload)
        elif item.kind == "on_llm_end":
            self._project_llm_call(payload)
        elif item.kind == "on_tool_end":
            self._project_tool_observation(payload)
        elif item.kind == "on_route":
            self.trace.route = payload.get("route")
        elif item.kind == "on_fault":
            self.trace.fault_events.append(FaultRecord(
                fault_type=payload.get("fault_type", "unknown"),
                tool=payload.get("tool", ""),
                phase=payload.get("phase", "before"),
                call_number=int(payload.get("call_number", 0) or 0),
                payload=dict(payload),
                sequence=self._sequence,
            ))

    def _project_turn(self, payload: dict) -> None:
        turn_index = int(payload.get("turn_index", 0))
        acts = self._acts_by_turn.get(turn_index, list(payload.get("acts") or []))
        record = next(
            (item for item in self.trace.turns if item.turn_index == turn_index),
            None,
        )
        if record:
            record.text = payload.get("user_input", record.text)
            record.acts = list(acts)
        else:
            self.trace.turns.append(TurnRecord(
                turn_index=turn_index,
                text=payload.get("user_input", ""),
                acts=list(acts),
            ))

    def _project_llm_call(self, payload: dict) -> None:
        usage = payload.get("usage") or {}
        self.trace.llm_calls.append(LLMCallRecord(
            purpose=payload.get("purpose", "unknown"),
            model=payload.get("model", ""),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            tool_calls=list(payload.get("tool_calls") or []),
            latency_ms=float(payload.get("latency_ms", 0.0) or 0.0),
            status=payload.get("status", "error"),
            error=payload.get("error"),
            sequence=self._sequence,
        ))

    def _project_tool_observation(self, payload: dict) -> None:
        self.trace.tool_observations.append(ToolObservation(
            name=payload.get("name", ""),
            description=payload.get("description"),
            arguments=dict(payload.get("arguments") or {}),
            result=payload.get("result", ""),
            status=payload.get("status", "error"),
            turn_index=payload.get("turn_index"),
            step_index=payload.get("step_index"),
            latency_ms=float(payload.get("latency_ms", 0.0) or 0.0),
            state_before=payload.get("state_before") or {},
            state_after=payload.get("state_after") or {},
            error=payload.get("error"),
            sequence=self._sequence,
        ))
