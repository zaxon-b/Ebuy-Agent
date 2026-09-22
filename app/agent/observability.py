"""Native callback events emitted at Agent, LLM, Tool and Route boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


EventKind = Literal[
    "on_turn_start",
    "on_llm_end",
    "on_tool_end",
    "on_route",
    "on_fault",
]


@dataclass(frozen=True)
class Event:
    kind: EventKind
    payload: dict[str, Any]


def event(kind: EventKind, **payload: Any) -> Event:
    return Event(kind=kind, payload=payload)


def response_tool_calls(response: Any) -> list[dict]:
    """Extract real OpenAI Function Calling output without SDK-version coupling."""
    try:
        calls = response.choices[0].message.tool_calls or []
    except (AttributeError, IndexError, TypeError):
        return []
    return [
        {
            "id": getattr(call, "id", None),
            "name": getattr(getattr(call, "function", None), "name", None),
            "arguments": getattr(getattr(call, "function", None), "arguments", None),
        }
        for call in calls
    ]


def response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
