"""MCP Client：同步封装，通过 Streamable HTTP 连接 MCP Server。

内部使用后台线程运行异步事件循环，对外暴露同步接口，
使得现有的同步 Agent 代码无需改动即可调用 MCP 工具。
"""

import asyncio
import json
import threading

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.mcp_client.converter import mcp_tools_to_openai


class MCPClient:
    """同步 MCP 客户端，通过 Streamable HTTP 连接远程 MCP Server。"""

    def __init__(self, server_url: str):
        self._server_url = server_url
        # 创建事件循环
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        # 线程间通信状态，默认False，
        self._connected = threading.Event()
        self._close_event: asyncio.Event | None = None

    def connect(self) -> list[dict]:
        """连接 MCP Server，发现工具，返回 OpenAI 格式的工具定义列表。"""
        self._loop = asyncio.new_event_loop()
        self._close_event = asyncio.Event()
        tool_definitions: list[dict] = []
        error_holder: list[Exception] = []
        
        # 定义子线程的任务：事件循环直到结束（循环的是_run())）
        def run_loop():
            self._loop.run_until_complete(self._run(tool_definitions, error_holder))

        # 创建子线程，设定任务时run_loop为target，daemon=True表示子线程随主线程退出而退出
        self._thread = threading.Thread(target=run_loop, daemon=True)
        # 启动子线程
        self._thread.start()
        # 让主线程等待子线程连接，30s
        self._connected.wait(timeout=30)

        if error_holder:
            raise error_holder[0]
        # 子线程返回的工具清单
        return tool_definitions

    async def _run(self, tool_definitions: list[dict], error_holder: list[Exception]):
        """后台协程：建立连接 → 发现工具 → 保持存活等待调用。"""
        try:
            # 建立与MCP Server的连接
            async with streamable_http_client(self._server_url) as (read, write, _):
                # 建立 session
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session

                    tools_result = await session.list_tools()
                    openai_tools = mcp_tools_to_openai(tools_result.tools)
                    tool_definitions.extend(openai_tools)
                    # 通知主线程连接成功，停止等待
                    self._connected.set()
                    # 防止子线程关闭断开网络连接，保持事件循环直到得到close信号
                    await self._close_event.wait()
        except Exception as e:
            error_holder.append(e)
            self._connected.set()

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回 JSON 字符串结果。"""
        if not self._session or not self._loop:
            return json.dumps({"error": "MCP 客户端未连接"}, ensure_ascii=False)

        # 在子线程中调用工具
        # 跨线程把调用工具的任务提交到事件循环_loop
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments), self._loop
        )
        try:
            result = future.result(timeout=30)
        except Exception as e:
            return json.dumps(
                {"error": f"MCP 工具调用出错: {e}"}, ensure_ascii=False
            )

        if result.isError:
            text = result.content[0].text if result.content else "未知错误"
            return json.dumps({"error": f"工具执行出错: {text}"}, ensure_ascii=False)

        return result.content[0].text if result.content else "{}"

    def close(self):
        """关闭 MCP 连接，清理后台线程。"""
        # 发送关闭信号
        if self._close_event and self._loop:
            self._loop.call_soon_threadsafe(self._close_event.set)
        # 等待子线程结束
        if self._thread:
            self._thread.join(timeout=5)
        self._session = None
        self._loop = None
        self._thread = None
