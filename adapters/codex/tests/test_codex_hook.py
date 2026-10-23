import json
import io
from pathlib import Path
from unittest.mock import patch

from agent_monitor_adapter.codex_hook import _approval_reviewer, _session_context, main


def test_session_start_injects_exact_monitor_session_id() -> None:
    context = _session_context(
        {"hook_event_name": "SessionStart", "session_id": "thread-123"}
    )
    message = context["hookSpecificOutput"]["additionalContext"]
    assert 'monitor_session_id = "thread-123"' in message


def test_other_events_do_not_write_hook_output() -> None:
    assert _session_context({"hook_event_name": "Stop", "session_id": "x"}) is None


def test_approval_metadata_matches_current_turn_and_explicit_field_wins() -> None:
    data = b'\n'.join(json.dumps({"type": "turn_context", "payload": {
        "turn_id": turn, "approvals_reviewer": reviewer}}).encode()
        for turn, reviewer in [("current", "auto_review"), ("old", "user")])
    event = {"turn_id": "current", "transcript_path": "unused"}
    with patch.object(Path, "open", return_value=io.BytesIO(data)):
        assert _approval_reviewer(event) == "auto_review"
    with patch.object(Path, "open", side_effect=AssertionError("must not read transcript")):
        assert _approval_reviewer(dict(event, approvals_reviewer="user")) == "user"


def test_missing_unreadable_and_changed_metadata_are_unknown() -> None:
    assert _approval_reviewer({}) is None
    event = {"turn_id": "current", "transcript_path": "unused"}
    with patch.object(Path, "open", side_effect=OSError):
        assert _approval_reviewer(event) is None
    for data in [b'', b'{"type":"turn_context",bad',
                 b'{"type":"turn_context","payload":[]}',
                 b'{"type":"turn_context","payload":{"turn_id":"old","approvals_reviewer":"user"}}']:
        with patch.object(Path, "open", return_value=io.BytesIO(data)):
            assert _approval_reviewer(event) is None


def test_permission_hook_forwards_only_resolved_route_from_metadata() -> None:
    event = {"hook_event_name": "PermissionRequest", "session_id": "s", "turn_id": "t"}
    with patch("sys.stdin", io.StringIO(json.dumps(event))), \
         patch("agent_monitor_adapter.codex_hook._approval_reviewer", return_value="auto_review"), \
         patch("agent_monitor_adapter.codex_hook._submit") as submit:
        main()
    submit.assert_called_once_with(dict(event, approvals_reviewer="auto_review"))
