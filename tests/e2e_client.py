"""End-to-end MCP test: spawn the server over stdio and call its tools. Run:

    venv/Scripts/python.exe tests/e2e_client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "server.py"


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert {"execute_code", "inspect_namespace", "reset_session"} <= tools, tools

            res = await session.call_tool("execute_code", {"code": "a = [i*i for i in range(5)]\nsum(a)"})
            assert not res.isError, res
            assert '"value": "30"' in str(res.content), res.content

            res = await session.call_tool("execute_code", {"code": "a"})
            assert '"value": "[0, 1, 4, 9, 16]"' in str(res.content), res.content

            res = await session.call_tool("execute_code", {"code": "raise ValueError('boom')"})
            assert "ValueError" in str(res.content), res.content

            res = await session.call_tool("inspect_namespace", {})
            assert '"a"' in str(res.content), res.content

            res = await session.call_tool("reset_session", {})
            assert not res.isError, res

            res = await session.call_tool("execute_code", {"code": "a"})
            assert "NameError" in str(res.content), res.content

    print("e2e MCP test passed")


if __name__ == "__main__":
    asyncio.run(main())
