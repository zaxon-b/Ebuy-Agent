import json
import time
from typing import Optional

from openai import OpenAI

from app.agent.storage import delete_session, load_session, save_session
from app.agent.observability import response_tool_calls, response_usage
from app.agent.run_context import RunContext, emit_run_event
from app.agent.store import SQLiteStore
from app.agent.summarizer import summarize
from app.config.settings import settings
from app.prompts.customer_service import SYSTEM_PROMPT
from app.schemas.response import CustomerServiceResponse, IntentType
from app.agent.tools.manager import ToolManager


class EcomAgent:
    """电商客服 Agent —— 第八期：Skill 可复用能力模块"""

    def __init__(
        self,
        session_path: Optional[str] = None,
        context: RunContext | None = None,
        client: OpenAI | None = None,
    ):
        self.context = context or RunContext(
            store=SQLiteStore.open(settings.ecom_db_path),
            current_user_id=settings.ecom_user_id,
        )
        self._owns_context = context is None
        self.client = client or OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.model_name
        self.temperature = settings.temperature
        self.session_path = session_path or settings.session_path
        self.history_threshold = settings.history_threshold
        self.history_keep_recent = settings.history_keep_recent
        self.max_react_steps = settings.max_react_steps

        self.tool_manager = ToolManager(
            use_mcp=settings.mcp_enabled,
            mcp_server_url=settings.mcp_server_url,
            context=self.context,
        )

        from app.agent.memory import MemoryManager
        self.memory_manager = MemoryManager(
            client=self.client,
            model=self.model,
            user_id=settings.memory_user_id,
            memory_dir=settings.memory_dir,
            memory_enabled=settings.memory_enabled,
            max_ltm_facts=settings.max_ltm_facts,
        )

        if settings.memory_enabled:
            from app.agent.tools.memory_tool import set_memory_manager
            set_memory_manager(self.memory_manager)


        from app.agent.skills import SkillManager
        self.skill_manager = SkillManager(
            skills_dir=settings.skills_dir,
            enabled=settings.skills_enabled,
        )
        if settings.skills_enabled:
            from app.agent.tools.skill_tool import set_skill_manager
            set_skill_manager(self.skill_manager)

        self.raw_messages: list[dict] = []
        self.summary: Optional[str] = None

        loaded = load_session(self.session_path)
        if loaded:
            self.summary = loaded["summary"]
            self.raw_messages = loaded["messages"]
            if loaded.get("short_term_memory"):
                self.memory_manager.restore_stm(loaded["short_term_memory"])

    @property
    def history_size(self) -> int:
        return len(self.raw_messages)

    @property
    def messages(self) -> list[dict]:
        """Compatibility view used by the original conversation tests."""
        return self._build_messages()

    def chat(self, user_input: str) -> CustomerServiceResponse:
        """处理用户输入：ReAct 循环 → 结构化提取 → 返回结果"""
        turn_index = sum(1 for message in self.raw_messages if message.get("role") == "user")
        self.tool_manager.begin_turn(turn_index)
        emit_run_event(self.context,
            "on_turn_start",
            turn_index=turn_index,
            user_input=user_input,
            acts=[],
        )
        self.raw_messages.append({"role": "user", "content": user_input})

        # llm每轮的原始输出
        final_text = self._react_loop()
        # 二次调用llm转换为结构化输出
        result = self._extract_structured_response(final_text)
        # 更新短期记忆(session)
        self.memory_manager.update_short_term(self.raw_messages[-6:])
        # 更新raw_messages(session)
        self.raw_messages.append(
            {
                "role": "assistant",
                "content": json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
            }
        )
        # 压缩message数量，并更新summary，
        if len(self.raw_messages) > self.history_threshold:
            self._compress_history()

        # sessions同时处理了：summary、raw_messages、stm
        save_session(
            self.session_path, self.raw_messages, self.summary,
            short_term_memory=self.memory_manager.stm_to_dict(),
        )
        return result

    def reset(self):
        self.raw_messages = []
        self.summary = None
        self.memory_manager.reset_short_term()
        delete_session(self.session_path)

    def save(self) -> None:
        save_session(
            self.session_path, self.raw_messages, self.summary,
            short_term_memory=self.memory_manager.stm_to_dict(),
        )

    def close(self):
        self.memory_manager.consolidate_to_long_term(self.raw_messages, self.summary)
        self.tool_manager.close()
        if self._owns_context:
            self.context.store.close()

    def _llm_create(self, purpose: str, **kwargs):
        """Emit one complete Event for one Chat Completions call."""
        started = time.perf_counter()
        model = kwargs.get("model", self.model)
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools", [])
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            emit_run_event(self.context,
                "on_llm_end",
                purpose=purpose,
                model=model,
                messages=messages,
                tools=tools,
                tool_calls=[],
                usage={},
                error=f"{type(exc).__name__}: {exc}",
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        emit_run_event(self.context,
            "on_llm_end",
            purpose=purpose,
            model=model,
            messages=messages,
            tools=tools,
            status="success",
            error=None,
            tool_calls=response_tool_calls(response),
            usage=response_usage(response),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return response

    def _llm_parse(self, purpose: str, **kwargs):
        started = time.perf_counter()
        model = kwargs.get("model", self.model)
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools", [])
        try:
            response = self.client.beta.chat.completions.parse(**kwargs)
        except Exception as exc:
            emit_run_event(self.context,
                "on_llm_end",
                purpose=purpose,
                model=model,
                messages=messages,
                tools=tools,
                tool_calls=[],
                usage={},
                error=f"{type(exc).__name__}: {exc}",
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        emit_run_event(self.context,
            "on_llm_end",
            purpose=purpose,
            model=model,
            messages=messages,
            tools=tools,
            status="success",
            error=None,
            tool_calls=response_tool_calls(response),
            usage=response_usage(response),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return response

    def _emit_final(self, content: str) -> str:
        """返回最终回复；若为空（模型多工具探索后忘了收尾），无工具重试一次强制补答。"""
        if content:
            self.raw_messages.append({"role": "assistant", "content": content})
            return content
        messages = self._build_messages()
        response = self._llm_create(
            "react_final",
            model=self.model,
            messages=messages,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        self.raw_messages.append({"role": "assistant", "content": content})
        return content

    def _react_loop(self) -> str:
        """ReAct 循环：调用 LLM → 执行工具 → 观察结果 → 重复，直到模型给出最终回答。"""
        for step in range(self.max_react_steps):

            messages = self._build_messages()

            response = self._llm_create(
                "react",
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                tools=self.tool_manager.tool_definitions,
            )
            choice = response.choices[0]
            assistant_msg = choice.message

            if assistant_msg.content:
                self._print_thought(assistant_msg.content)

            if not assistant_msg.tool_calls:
                return self._emit_final(assistant_msg.content or "")

            msg_dict = {"role": "assistant", "content": assistant_msg.content}
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
            self.raw_messages.append(msg_dict)

            for tc in assistant_msg.tool_calls:
                func_name = tc.function.name
                func_args = json.loads(tc.function.arguments)

                self._print_action(func_name, func_args)
                result_str = self.tool_manager.execute_tool(func_name, func_args)
                self._print_observation(result_str)

                self.raw_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        messages = self._build_messages()
        response = self._llm_create(
            "react_final",
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        return self._emit_final(response.choices[0].message.content or "")

    def _extract_structured_response(self, text: str) -> CustomerServiceResponse:
        """从最终文本中提取结构化元数据（意图、置信度等）。"""
        try:
            response = self._llm_parse(
                "extract",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "基于以下客服回复内容，提取结构化信息。"
                            "reply 字段直接使用原文，不要修改或缩减。"
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                response_format=CustomerServiceResponse,
            )
            return response.choices[0].message.parsed
        except Exception:
            return self._extract_structured_fallback(text)

    def _extract_structured_fallback(self, text: str) -> CustomerServiceResponse:
        """当 response_format 不被 API 支持时，用 prompt 引导 JSON 输出。"""
        intent_values = ", ".join(f'"{e.value}"' for e in IntentType)
        response = self._llm_create(
            "extract_fallback",
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "基于以下客服回复内容，提取结构化信息并输出 JSON。\n"
                        "reply 字段直接使用原文，不要修改或缩减。\n\n"
                        "必须严格按照以下 JSON 格式输出（不要加 markdown 代码块）：\n"
                        "{\n"
                        f'  "intent": <从以下选择: {intent_values}>,\n'
                        '  "confidence": <0.0到1.0的浮点数>,\n'
                        '  "reply": <原文回复内容>,\n'
                        '  "requires_human": <true或false>,\n'
                        '  "follow_up_question": <追问问题或null>\n'
                        "}"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return CustomerServiceResponse.model_validate_json(raw)

    def _build_messages(self) -> list[dict]:
        system_content = SYSTEM_PROMPT
        if self.skill_manager and self.skill_manager.enabled:
            system_content += self.skill_manager.build_catalog_prompt()

        messages: list[dict] = [
            {"role": "system", "content": system_content}
        ]
        messages.extend(self.memory_manager.build_memory_prompt_sections())
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是此前对话的摘要，用于延续上下文记忆：\n{self.summary}",
                }
            )
        messages.extend(self.raw_messages)
        return messages

    def _compress_history(self) -> None:
        keep = self.history_keep_recent
        split = len(self.raw_messages) - keep
        while split > 0 and self.raw_messages[split].get("role") in ("tool",):
            split -= 1
        if split <= 0:
            return
        old_messages = self.raw_messages[:split]
        recent = self.raw_messages[split:]

        new_summary = summarize(
            client=self.client,
            model=self.model,
            old_messages=old_messages,
            prev_summary=self.summary,
        )
        self.summary = new_summary
        self.raw_messages = recent
        print(
            f"\n💾 [已压缩 {len(old_messages)} 条老消息 → summary "
            f"({len(new_summary)} 字)]\n"
        )

    def _print_thought(self, text: str) -> None:
        print(f"\n💭 [思考] {text}")

    def _print_action(self, func_name: str, func_args: dict) -> None:
        args_str = ", ".join(f"{k}={v!r}" for k, v in func_args.items())
        print(f"🔧 [调用工具] {func_name}({args_str})")

    def _print_observation(self, result: str) -> None:
        display = result if len(result) <= 300 else result[:300] + "..."
        print(f"📋 [工具结果] {display}")
