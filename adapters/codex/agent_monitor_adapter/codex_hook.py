from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import psutil


def _codex_process() -> tuple[int | None, float | None]:
    """Return the nearest Codex ancestor, or no binding if it cannot be proven."""
    try:
        process = psutil.Process(os.getppid())
        while process is not None:
            if "codex" in process.name().casefold():
                return process.pid, process.create_time()
            process = process.parent()
        return None, None
    except (psutil.Error, OSError):
        return None, None


def _submit(event: dict[str, Any]) -> None:
    adapter_url = os.getenv(
        "AGENT_MONITOR_ADAPTER_URL", "http://127.0.0.1:18765"
    ).rstrip("/")
    source_pid, source_started_at = _codex_process()
    body = json.dumps(
        {
            "event": event,
            "emitted_at_ns": time.time_ns(),
            "source_pid": source_pid,
            "source_started_at": source_started_at,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{adapter_url}/v1/events/codex",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=0.75):
            pass
    except (OSError, urllib.error.URLError):
        # Monitoring must never interrupt the Codex lifecycle.
        pass


def _session_context(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("hook_event_name") != "SessionStart":
        return None
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Agent Monitor monitor_session_id = "
                f"{json.dumps(session_id)}. Pass this exact value to the agent-monitor "
                "report_status tool when the reporting skill applies."
            ),
        },
    }


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(event, dict):
        return
    _submit(event)
    context = _session_context(event)
    if context is not None:
        print(json.dumps(context, separators=(",", ":")))


if __name__ == "__main__":
    main()
