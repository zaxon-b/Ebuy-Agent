"""Deterministic per-Case tool errors and empty results."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class FaultHit:
    result: str
    event_payload: dict


class FaultInjector:
    """One isolated fault counter and spec set for one Eval run."""

    def __init__(self, specs: Iterable[object] = ()):
        self.specs = list(specs)
        self._call_counts: dict[str, int] = defaultdict(int)

    @staticmethod
    def _value(spec: object, name: str, default=None):
        if isinstance(spec, dict):
            return spec.get(name, default)
        return getattr(spec, name, default)

    def before_tool(self, name: str, arguments: dict) -> FaultHit | None:
        self._call_counts[name] += 1
        call_number = self._call_counts[name]
        for spec in self.specs:
            fault_type = self._value(spec, "type")
            if self._value(spec, "tool") != name:
                continue
            trigger = int(self._value(spec, "trigger_call", 1))
            fail_times = self._value(spec, "fail_times")
            if call_number < trigger:
                continue
            if fail_times is not None and call_number >= trigger + int(fail_times):
                continue
            if fault_type == "tool_error":
                payload = self._value(spec, "error") or {
                    "success": False,
                    "error": "Injected tool error",
                }
            elif fault_type == "empty_result":
                payload = {"success": True, "results": self._value(spec, "results", [])}
            else:
                continue
            return FaultHit(
                result=json.dumps(payload, ensure_ascii=False),
                event_payload={
                    "fault_type": fault_type,
                    "tool": name,
                    "phase": "before",
                    "call_number": call_number,
                    "arguments": dict(arguments),
                    "result": payload,
                },
            )
        return None
