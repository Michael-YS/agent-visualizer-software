from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


MAX_DETAIL_BYTES = 400
VALID_STATES = {"idle", "thinking", "tool_running", "needs_input", "turn_complete", "error", "offline"}


def _payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    session_id = value.get("session_id")
    state = value.get("state")
    if (not isinstance(session_id, str) or not session_id.strip() or
            len(session_id) > 256 or not isinstance(state, str) or state not in VALID_STATES):
        return None
    detail = value.get("detail", "")
    if not isinstance(detail, str):
        return None
    detail = detail.encode("utf-8")[:MAX_DETAIL_BYTES].decode("utf-8", errors="ignore")
    return {"session_id": session_id, "state": state, "detail": detail}


def submit(payload: dict[str, Any]) -> None:
    base = os.getenv("AGENT_MONITOR_CLAUDE_ADAPTER_URL", "http://127.0.0.1:18766").rstrip("/")
    request = urllib.request.Request(
        f"{base}/v1/reports",
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=0.65):
            pass
    except (OSError, urllib.error.URLError, TimeoutError):
        pass


def main() -> None:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return
    payload = _payload(value)
    if payload is not None:
        submit(payload)


if __name__ == "__main__":
    main()
