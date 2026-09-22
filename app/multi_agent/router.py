"""意图路由器：分析用户消息，决定分发给哪个子 Agent。"""

import time
from typing import Any, List, Optional

from openai import OpenAI

from app.prompts.agents import ROUTER_PROMPT
from app.agent.observability import event, response_tool_calls, response_usage

VALID_AGENTS = {"presale", "postsale", "complaint"}
DEFAULT_AGENT = "postsale"


class Router:
    """使用 LLM 对用户意图分类，路由到对应的子 Agent。"""

    def __init__(self, client: OpenAI, model: str, tracer: Any | None):
        self.client = client
        self.model = model
        self.tracer = tracer

    def _emit(self, kind, **payload) -> None:
        if self.tracer is not None:
            self.tracer.emit(event(kind, **payload))

    def route(
        self,
        user_input: str,
        history: Optional[List[dict]] = None,
        turn_index: int = -1,
    ) -> str:
        """返回子 Agent 标识: "presale" / "postsale" / "complaint"。"""
        recent_context = ""
        if history:
            recent = [
                m for m in history[-4:]
                if m.get("role") in ("user", "assistant")
            ]
            if recent:
                lines = []
                for m in recent:
                    role = "用户" if m["role"] == "user" else "客服"
                    content = m.get("content", "")
                    if content and len(content) < 200:
                        lines.append(f"{role}: {content}")
                if lines:
                    recent_context = "\n最近对话：\n" + "\n".join(lines) + "\n"

        prompt = ROUTER_PROMPT.format(user_input=user_input)
        if recent_context:
            prompt = recent_context + "\n" + prompt

        messages = [{"role": "user", "content": prompt}]
        # V5 修复：此前 max_tokens=10 在 deepseek 推理模型下会把预算全部消耗在
        # reasoning_content，导致 content 恒为空 → 精确匹配必失败 → 静默兜底 postsale，
        # 实测 150/150 全 fallback（presale/complaint 从未被路由），详见 eval_v2_run_log.md。
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=64,
            )
        except Exception as exc:
            self._emit(
                "on_llm_end", purpose="router", model=self.model,
                messages=messages, tools=[], tool_calls=[], usage={},
                error=f"{type(exc).__name__}: {exc}",
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        self._emit(
            "on_llm_end", purpose="router", model=self.model,
            messages=messages, tools=[], status="success", error=None,
            tool_calls=response_tool_calls(response), usage=response_usage(response),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

        raw = (response.choices[0].message.content or "").strip().lower()

        # 空值防御：模型可能把预算花在 reasoning 上导致 content 为空。首轮仍空则
        # 用默认预算重试一次；仍空才走兜底，并打 empty_content=True 便于观测。
        if not raw:
            retry_resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
            )
            raw = (retry_resp.choices[0].message.content or "").strip().lower()

        if not raw:
            self._emit(
                "on_route", turn_index=turn_index, route=DEFAULT_AGENT,
                raw="", fallback=True, empty_content=True,
            )
            return DEFAULT_AGENT

        for agent_key in VALID_AGENTS:
            if agent_key in raw:
                self._emit(
                    "on_route", turn_index=turn_index, route=agent_key, raw=raw
                )
                return agent_key

        self._emit(
            "on_route", turn_index=turn_index, route=DEFAULT_AGENT,
            raw=raw, fallback=True,
        )
        return DEFAULT_AGENT
