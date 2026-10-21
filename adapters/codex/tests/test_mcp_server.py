import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_server_exposes_report_status_tool() -> None:
    async def inspect() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "agent_monitor_adapter.mcp_server"],
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ["report_status"]

    asyncio.run(inspect())
