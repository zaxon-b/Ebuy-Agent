"""ToolManager：统一管理本地工具和 MCP 工具。

当 MCP 启用时，通过 Streamable HTTP 连接 MCP Server 获取工具；
当 MCP 未启用或连接失败时，退回本地工具。
"""

import json
import time
from typing import Any, Optional

from app.agent.run_context import RunContext, emit_run_event
from app.agent.store import SQLiteStore
from app.agent.tools.registry import TOOL_DEFINITIONS as LOCAL_TOOL_DEFINITIONS
from app.agent.tools.registry import execute_tool as local_execute_tool
from app.config.settings import settings


class ToolManager:
    """聚合本地工具和 MCP 工具，提供统一的工具定义和调度接口。"""

    def __init__(
        self,
        use_mcp: bool = False,
        mcp_server_url: str = "",
        allowed_tools: Optional[set] = None,
        context: RunContext | None = None,
    ):
        self.context = context or RunContext(
            store=SQLiteStore.open(settings.ecom_db_path),
            current_user_id=settings.ecom_user_id,
        )
        self._owns_context = context is None
        # MCP is an optional dependency loaded lazily in ``_init_mcp``.
        self._mcp_client: Any = None
        self._tool_source: dict[str, str] = {}
        self._tool_defs: list[dict] = []

        if use_mcp and mcp_server_url:
            self._init_mcp(mcp_server_url)
        else:
            self._init_local()

        if allowed_tools is not None:
            self._filter_tools(allowed_tools)

        self._description_by_name = {
            tool["function"]["name"]: tool["function"].get("description", "")
            for tool in self._tool_defs
        }
        self._turn_index = -1
        self._step_index = 0

    def _init_local(self):
        """只加载本地工具。"""
        self._tool_defs = list(LOCAL_TOOL_DEFINITIONS)
        for td in self._tool_defs:
            self._tool_source[td["function"]["name"]] = "local"

    def _init_mcp(self, server_url: str):
        """连接 MCP Server 加载工具；失败时降级到本地工具。"""
        from app.mcp_client import MCPClient

        try:
            self._mcp_client = MCPClient(server_url)
            mcp_tools = self._mcp_client.connect()
            print(f"🔗 [MCP] 已连接 {server_url}，发现 {len(mcp_tools)} 个工具")

            mcp_names = set()
            for td in mcp_tools:
                name = td["function"]["name"]
                mcp_names.add(name)
                self._tool_source[name] = "mcp"
            self._tool_defs = list(mcp_tools)

            for td in LOCAL_TOOL_DEFINITIONS:
                name = td["function"]["name"]
                if name not in mcp_names:
                    self._tool_defs.append(td)
                    self._tool_source[name] = "local"

        except Exception as e:
            print(f"⚠️  [MCP] 连接失败 ({e})，降级使用本地工具")
            if self._mcp_client:
                self._mcp_client.close()
                self._mcp_client = None
            self._init_local()

    def _filter_tools(self, allowed: set):
        """只保留白名单中的工具，用于子 Agent 工具隔离。"""
        self._tool_defs = [
            d for d in self._tool_defs
            if d["function"]["name"] in allowed
        ]
        self._tool_source = {
            k: v for k, v in self._tool_source.items()
            if k in allowed
        }

    def exclude_tools(self, names: set[str]) -> None:
        """Remove tools from the exposed schema for a benchmark or restricted agent."""
        allowed = {
            item["function"]["name"] for item in self._tool_defs
        } - set(names)
        self._filter_tools(allowed)
        self._description_by_name = {
            tool["function"]["name"]: tool["function"].get("description", "")
            for tool in self._tool_defs
        }

    @property
    def tool_definitions(self) -> list[dict]:
        return self._tool_defs

    def begin_turn(self, turn_index: int) -> None:
        self._turn_index = turn_index
        self._step_index = 0

    def _next_step_index(self) -> int:
        current = self._step_index
        self._step_index += 1
        return current

    @staticmethod
    def _infer_status(result: str) -> str:
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return "error"
        if payload.get("success") is False:
            return "error"
        if "success" not in payload and payload.get("error"):
            return "error"
        return "success"

    def _capture_state(self) -> dict:
        """Read Eval state only when this run has a Tracer."""

        if self.context.tracer is None:
            return {}
        from app.evaluation.state import snapshot_store

        return snapshot_store(self.context.store)

    def execute_tool(self, name: str, arguments: dict) -> str:
        """根据工具来源分发调用。"""
        started = time.perf_counter()
        step_index = self._next_step_index()
        description = self._description_by_name.get(name, "")
        state_before = self._capture_state()
        source = self._tool_source.get(name)
        result = ""
        status = "error"
        raised_error: Exception | None = None
        try:
            fault = (
                self.context.faults.before_tool(name, arguments)
                if self.context.faults is not None
                else None
            )
            if fault is not None:
                emit_run_event(self.context, "on_fault", **fault.event_payload)
                result = fault.result
            elif source == "mcp" and self._mcp_client:
                result = self._mcp_client.call_tool(name, arguments)
            elif source == "local":
                result = local_execute_tool(name, arguments, context=self.context)
            else:
                result = json.dumps(
                    {"success": False, "error": f"未知工具: {name}"},
                    ensure_ascii=False,
                )
            status = self._infer_status(result)
            return result
        except Exception as exc:  # noqa: BLE001 - tool failures are structured observations
            raised_error = exc
            result = json.dumps(
                {"success": False, "error": f"工具执行出错: {exc}"},
                ensure_ascii=False,
            )
            return result
        finally:
            state_after = self._capture_state()
            emit_run_event(self.context,
                "on_tool_end",
                name=name,
                description=description,
                arguments=dict(arguments),
                result=result,
                status="error" if raised_error is not None else status,
                error=(f"{type(raised_error).__name__}: {raised_error}" if raised_error else None),
                turn_index=self._turn_index,
                step_index=step_index,
                state_before=state_before,
                state_after=state_after,
                latency_ms=(time.perf_counter() - started) * 1000,
            )

    def close(self):
        """清理 MCP 连接。"""
        if self._mcp_client:
            self._mcp_client.close()
            self._mcp_client = None
        if self._owns_context:
            self.context.store.close()
