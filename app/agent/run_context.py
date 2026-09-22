"""Objects shared by one Agent run.

``RunContext`` is deliberately a thin reference container. It does not own
object lifecycles, execute tools, route events, take snapshots or grade a run.
Normal application runs only provide ``store`` and ``current_user_id``;
evaluation additionally injects one per-run ``Tracer`` and ``FaultInjector``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agent.observability import EventKind, event
from app.agent.store import SQLiteStore

if TYPE_CHECKING:
    from app.evaluation.faults import FaultInjector
    from app.evaluation.tracer import Tracer


@dataclass(frozen=True)
class RunContext:
    """The four run-scoped references shared by Agent and ToolManager."""

    store: SQLiteStore
    current_user_id: str
    tracer: "Tracer | None" = None
    faults: "FaultInjector | None" = None


def emit_run_event(context: RunContext, kind: EventKind, **payload: Any) -> None:
    """Create and emit an Event only when this run has an Eval Tracer."""

    if context.tracer is not None:
        context.tracer.emit(event(kind, **payload))
