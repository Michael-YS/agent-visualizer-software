from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import psutil


def _claude_ancestor() -> tuple[int | None, float | None]:
    """Bind only to an ancestor recognizable as the Claude Code CLI itself."""
    try:
        process = psutil.Process(os.getppid())
        while process is not None:
            name = process.name().casefold()
            if name in {"claude", "claude.exe"}:
                return process.pid, process.create_time()
            if name in {"node", "node.exe"}:
                command = " ".join(process.cmdline()).replace("\\", "/").casefold()
                if re.search(r"(?:^|/)@anthropic-ai/claude-code/(?:cli(?:\.js)?|sdk(?:\.js)?)(?:\s|$)", command):
                    return process.pid, process.create_time()
            process = process.parent()
    except (psutil.Error, OSError):
        pass
    return None, None


def submit(event: dict[str, Any]) -> None:
    url = os.getenv("AGENT_MONITOR_CLAUDE_ADAPTER_URL", "http://127.0.0.1:18766").rstrip("/")
    pid, created = _claude_ancestor()
    body = json.dumps({
        "event": event,
        "emitted_at_ns": time.time_ns(),
        "source_pid": pid,
        "source_create_time": created,
    }, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/v1/events/claude-code", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=0.65):
            pass
    except (OSError, urllib.error.URLError, TimeoutError):
        # Telemetry is fail-open and must not delay Claude Code's hook lifecycle.
        pass


def session_context(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("hook_event_name") != "SessionStart":
        return None
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    exact = json.dumps(session_id, ensure_ascii=False)
    return {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": (
            "Agent Monitor session_id = " + exact +
            ". When a meaningful status change needs reporting, invoke "
            "/agent-monitor-claude-code:report-status and pass this exact "
            "session_id so the status is attached to this Claude Code session."
        ),
    }}


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return
    if not isinstance(event, dict):
        return
    submit(event)
    output = session_context(event)
    if output is not None:
        print(json.dumps(output, separators=(",", ":")))


if __name__ == "__main__":
    main()
