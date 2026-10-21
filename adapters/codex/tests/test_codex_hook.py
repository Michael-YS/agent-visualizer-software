import json

from agent_monitor_adapter.codex_hook import _session_context


def test_session_start_injects_exact_monitor_session_id() -> None:
    context = _session_context(
        {"hook_event_name": "SessionStart", "session_id": "thread-123"}
    )
    message = context["hookSpecificOutput"]["additionalContext"]
    assert 'monitor_session_id = "thread-123"' in message


def test_other_events_do_not_write_hook_output() -> None:
    assert _session_context({"hook_event_name": "Stop", "session_id": "x"}) is None
