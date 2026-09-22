"""The single execution entry point for one Canonical Eval Case."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Callable

from app.agent.run_context import RunContext
from app.config.settings import settings
from app.evaluation.dataset import (
    EvalCase,
    FSMDialogue,
    LLMDialogue,
    StaticDialogue,
    UserTurn,
)
from app.evaluation.faults import FaultInjector
from app.evaluation.metrics.deterministic import resolve_sop_text
from app.evaluation.state import (
    create_case_store,
    knowledge_hash,
    knowledge_manifest,
    knowledge_snapshot_errors,
    snapshot_store,
)
from app.evaluation.tracer import Tracer


class EvaluationRunner:
    """Build an isolated run, execute its dialogue, and return one RunTrace."""

    def __init__(
        self,
        mode: str = "single",
        agent_factory: Callable | None = None,
        expected_knowledge_hash: str | None = None,
    ):
        if mode not in {"single", "multi"}:
            raise ValueError("mode 必须是 single 或 multi")
        self.mode = mode
        self.agent_factory = agent_factory
        self.expected_knowledge_hash = expected_knowledge_hash

    def _build_agent(self, context: RunContext, session_path: str):
        if self.agent_factory:
            return self.agent_factory(self.mode, context, session_path)
        if self.mode == "multi":
            from app.multi_agent.orchestrator import MultiAgentOrchestrator

            return MultiAgentOrchestrator(session_path=session_path, context=context)
        from app.agent.chat import EcomAgent

        return EcomAgent(session_path=session_path, context=context)

    @staticmethod
    def _tool_managers(agent) -> list:
        if hasattr(agent, "tool_manager"):
            return [agent.tool_manager]
        if hasattr(agent, "agents"):
            return [sub_agent.tool_manager for sub_agent in agent.agents.values()]
        return []

    @staticmethod
    def _fsm_next(node: dict, reply: str) -> str | None:
        for transition in node.get("transitions", []):
            kind = transition.get("when", "always")
            value = transition.get("value", "")
            if kind == "always":
                return transition.get("next")
            if kind == "reply_contains" and value in reply:
                return transition.get("next")
            if kind == "reply_not_contains" and value not in reply:
                return transition.get("next")
        return node.get("next")

    def _run_dialogue(self, case: EvalCase, agent, tracer: Tracer):
        result = None
        dialogue = case.dialogue
        if isinstance(dialogue, StaticDialogue):
            for turn_index, turn in enumerate(dialogue.turns):
                tracer.set_turn_contract(turn_index, turn.text, list(turn.acts))
                result = agent.chat(turn.text)
            return result

        if isinstance(dialogue, LLMDialogue):
            raise ValueError("LLM User Simulator 属于 Exploratory 阶段，Canonical 不运行")

        if not isinstance(dialogue, FSMDialogue):
            raise TypeError(f"不支持的 dialogue: {type(dialogue).__name__}")
        state = dialogue.start
        seen = 0
        while state and seen < 12:
            node = dialogue.states.get(state)
            if not node:
                raise ValueError(f"FSM state 不存在: {state}")
            turn = UserTurn.model_validate(node["turn"])
            tracer.set_turn_contract(seen, turn.text, list(turn.acts))
            result = agent.chat(turn.text)
            state = self._fsm_next(node, result.reply if result else "")
            seen += 1
        if state:
            raise ValueError("FSM 超过 12 轮，疑似循环")
        return result

    @staticmethod
    def _close_agent(agent) -> None:
        if agent is None:
            return
        close = getattr(agent, "close", None)
        if callable(close):
            close()
            return
        for manager in EvaluationRunner._tool_managers(agent):
            manager.close()

    def run_case(self, case: EvalCase):
        """Run one Case. Store, Tracer and fault counters never cross Case boundaries."""

        if self.mode not in case.modes:
            raise ValueError(f"Case {case.id} 不支持 mode={self.mode}")

        from app.agent.tools.knowledge import reset_retriever

        started = time.perf_counter()
        old_memory = settings.memory_enabled
        old_mcp = settings.mcp_enabled
        store = create_case_store(case.run.seed_id, case.run.initial_state_patch)
        tracer = Tracer(case.id)
        faults = FaultInjector(case.run.faults)
        context = RunContext(
            store=store,
            current_user_id=case.run.user_id,
            tracer=tracer,
            faults=faults,
        )
        trace = tracer.trace
        agent = None
        manifest = knowledge_manifest()
        metadata = {
            "dataset_contract": "canonical-v4",
            "seed_id": case.run.seed_id,
            "mode": self.mode,
            "agent_model": settings.model_name,
            "judge_model": settings.eval_judge_model,
            "temperature": settings.temperature,
            "rag_backend": settings.rag_backend,
            "embedding_model": settings.embedding_model,
            "knowledge_hash": knowledge_hash(),
            "knowledge_snapshot_id": manifest.get("snapshot_id", "unknown"),
            "sop": resolve_sop_text(case.expected.sop_ref),
            "tool_schema": [],
        }
        trace.initial_state = snapshot_store(store)
        trace.metadata = metadata

        try:
            requires_knowledge_index = any(
                any(call.tool == "search_knowledge" for call in path)
                and not any(
                    fault.tool == "search_knowledge"
                    and fault.type in {"tool_error", "empty_result"}
                    and fault.trigger_call == 1
                    for fault in case.run.faults
                )
                for path in case.expected.tool_paths
            )
            errors = knowledge_snapshot_errors(
                require_index=requires_knowledge_index
            )
            if (
                self.expected_knowledge_hash
                and metadata["knowledge_hash"] != self.expected_knowledge_hash
            ):
                errors.append("Knowledge snapshot hash does not match Runner expectation")
            if errors:
                raise RuntimeError("; ".join(dict.fromkeys(errors)))

            settings.memory_enabled = False
            settings.mcp_enabled = False
            reset_retriever()
            with tempfile.TemporaryDirectory(prefix=f"eval-{case.id}-") as tmp_dir:
                session_path = str(Path(tmp_dir) / "session.json")
                agent = self._build_agent(context, session_path)
                managers = self._tool_managers(agent)
                for manager in managers:
                    manager.exclude_tools({"recall_user_memory"})
                metadata["tool_schema"] = [
                    definition
                    for manager in managers
                    for definition in manager.tool_definitions
                ]
                trace.final_response = self._run_dialogue(case, agent, tracer)
        except Exception as exc:  # noqa: BLE001 - isolate one failed Case
            trace.error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self._close_agent(agent)
            except Exception as exc:  # noqa: BLE001 - cleanup is part of the Run
                if not trace.error:
                    trace.error = f"清理异常 {type(exc).__name__}: {exc}"
            trace.final_state = snapshot_store(store)
            trace.end_to_end_latency_ms = (time.perf_counter() - started) * 1000
            try:
                reset_retriever()
            finally:
                settings.memory_enabled = old_memory
                settings.mcp_enabled = old_mcp
                store.close()
        return trace


__all__ = ["EvaluationRunner"]
