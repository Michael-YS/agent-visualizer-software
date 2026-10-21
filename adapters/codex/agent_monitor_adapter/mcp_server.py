from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Literal

from mcp.server.fastmcp import FastMCP


State = Literal[
    "offline",
    "idle",
    "thinking",
    "tool_running",
    "needs_input",
    "turn_complete",
    "error",
]

mcp = FastMCP("agent-monitor")


@mcp.tool()
def report_status(session_id: str, state: State, detail: str = "") -> str:
    """Report a meaningful status change for the current Codex session."""
    if not session_id.strip():
        raise ValueError("session_id is required; use the ID injected at SessionStart")
    adapter_url = os.getenv(
        "AGENT_MONITOR_ADAPTER_URL", "http://127.0.0.1:18765"
    ).rstrip("/")
    body = json.dumps(
        {"session_id": session_id, "state": state, "detail": detail},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{adapter_url}/v1/reports",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            result = json.load(response)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"Agent Monitor adapter is unavailable: {error}") from error
    return f"Reported {result['state']} for {result['id']}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
