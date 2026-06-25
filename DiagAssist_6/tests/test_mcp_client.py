"""
test_mcp_client.py
--------------------
Standalone MCP client that spawns mcp_server.py as a subprocess and talks
to it over the real MCP stdio protocol — proving the server works as an
actual MCP server (not just as a plain Python function call).

Usage:
    python tests/test_mcp_client.py
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PATH = os.path.join(BASE_DIR, "mcp", "mcp_server.py")


async def run_test():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_PATH],
    )

    print(f"Launching MCP server: {SERVER_PATH}\n")

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. List available tools — confirms lookup_dtc is registered.
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print("Available tools:", tool_names)
            assert "lookup_dtc" in tool_names, "lookup_dtc not registered!"

            # 2. Call the tool with a valid code.
            print("\n--- Calling lookup_dtc('P0420') ---")
            result = await session.call_tool("lookup_dtc", {"code": "P0420"})
            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text)

            # 3. Call the tool with an invalid code.
            print("\n--- Calling lookup_dtc('P9999') ---")
            result = await session.call_tool("lookup_dtc", {"code": "P9999"})
            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text)

    print("\nMCP client test complete — server responded correctly over stdio.")


if __name__ == "__main__":
    asyncio.run(run_test())
