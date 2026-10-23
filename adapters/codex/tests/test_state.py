import hashlib
import json
import threading

import pytest

from agent_monitor_adapter.state import SessionReducer, truncate_utf8


def test_json_escaping_cannot_exceed_bridge_payload_limit() -> None:
    reducer = SessionReducer("\\" * 96)
    snapshot = reducer.ingest_report(
        {"session_id": "escape", "state": "thinking", "detail": "\x00" * 512}
    )
    payload = snapshot.as_status()
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) <= 1024
    assert payload["name"].strip()
    assert payload["host"].strip()


def hook(event: str, **values: object) -> dict[str, object]:
    return {"hook_event_name": event, "session_id": "native-session-123456", "cwd": r"C:\repo\demo", **values}


def test_protocol_identity_name_and_bridge_projection() -> None:
    reducer = SessionReducer("workstation")
    snapshot = reducer.ingest_hook(hook("SessionStart", source="startup", pid=42, process_create_time=17.5))

    expected = hashlib.sha256(b"workstation|codex|native-session-123456").hexdigest()[:20]
    assert snapshot.id == f"codex-{expected}"
    assert snapshot.name == "Codex / demo / n-123456"
    assert snapshot.as_status() == {
        "id": snapshot.id,
        "name": snapshot.name,
        "host": "workstation",
        "state": "idle",
        "detail": "Session started or resumed",
        "timestamp": snapshot.timestamp,
    }
    assert (snapshot.source_pid, snapshot.source_create_time) == (42, 17.5)


def test_hook_lifecycle_tracks_tools_and_compact_preserves_state() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("SessionStart", source="startup"))
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="turn-a"))
    first = reducer.ingest_hook(hook("PreToolUse", tool_name="shell", tool_call_id="tool-1"))
    assert first.state == "tool_running"
    assert first.active_tool_ids == {"tool-1"}
    assert first.current_turn == "turn-a"

    compact = reducer.ingest_hook(hook("SessionStart", source="compact"))
    assert compact.revision == first.revision
    assert compact.state == "tool_running"

    post = reducer.ingest_hook(hook("PostToolUse", tool_name="shell", tool_call_id="tool-1"))
    assert post.state == "thinking"
    assert not post.active_tool_ids
    assert post.completed_tool_ids == {"tool-1"}
    assert reducer.ingest_hook(hook("Stop")).state == "turn_complete"
    assert reducer.ingest_hook(hook("Interrupt")).state == "idle"
    assert reducer.ingest_hook(hook("SessionEnd")).state == "offline"


def test_parallel_tools_and_adapter_tool_do_not_flash_state() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit"))
    one = reducer.ingest_hook(hook("PreToolUse", tool_name="shell", tool_call_id="a"))
    own = reducer.ingest_hook(hook("PreToolUse", tool_name="mcp__agent_monitor__report_status"))
    assert own.revision == one.revision
    reducer.ingest_hook(hook("PreToolUse", tool_name="browser", tool_call_id="b"))
    after_one = reducer.ingest_hook(hook("PostToolUse", tool_call_id="a"))
    assert after_one.state == "tool_running"
    assert after_one.active_tool_ids == {"b"}
    assert reducer.ingest_hook(hook("PostToolUse", tool_call_id="b")).state == "thinking"


@pytest.mark.parametrize("state", ["needs_input", "error"])
def test_report_attention_state_stays_through_hooks_until_user_prompt(state: str) -> None:
    reducer = SessionReducer()
    reported = reducer.ingest_report({"session_id": "native-session-123456", "state": state, "detail": "等待用户" * 200})
    assert reported.state == state
    assert len(reported.detail.encode("utf-8")) <= 512
    assert reducer.ingest_hook(hook("PreToolUse", tool_name="shell", tool_call_id="x")).state == state
    assert reducer.ingest_hook(hook("PostToolUse", tool_call_id="x")).state == state
    assert reducer.ingest_hook(hook("Stop")).state == state
    assert reducer.ingest_hook(hook("UserPromptSubmit")).state == "thinking"
    assert reducer.ingest_hook(hook("Stop")).state == "turn_complete"


def test_permission_and_invalid_inputs() -> None:
    reducer = SessionReducer()
    assert reducer.ingest_hook(hook("PermissionRequest", approvals_reviewer="user")).state == "needs_input"
    assert reducer.ingest_hook(hook("Stop")).state == "turn_complete"
    assert reducer.ingest_hook(hook("PostToolUse", tool_use_id="approved")).state == "thinking"
    with pytest.raises(ValueError):
        reducer.ingest_report({"session_id": "s", "state": "running"})
    with pytest.raises(ValueError):
        reducer.ingest_hook({"hook_event_name": "Stop"})


@pytest.mark.parametrize("reviewer", ["auto_review", "guardian_subagent", None])
def test_nonhuman_or_unknown_approval_does_not_request_attention(reviewer) -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="t"))
    reducer.ingest_hook(hook("PreToolUse", turn_id="t", tool_use_id="a"))
    snapshot = reducer.ingest_hook(hook("PermissionRequest", turn_id="t", approvals_reviewer=reviewer))
    assert snapshot.state == "tool_running"
    assert reducer.ingest_hook(hook("Stop", turn_id="t")).state == "turn_complete"


def test_approval_route_is_cached_only_for_current_turn() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="manual", approvals_reviewer="user"))
    assert reducer.ingest_hook(hook("PermissionRequest", turn_id="manual")).state == "needs_input"
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="unknown"))
    assert reducer.ingest_hook(hook("PermissionRequest", turn_id="unknown")).state == "thinking"


def test_review_route_can_arrive_late_or_switch_to_human() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="t"))
    assert reducer.ingest_hook(hook("PermissionRequest", turn_id="t")).state == "thinking"
    assert reducer.ingest_hook(hook("PermissionRequest", turn_id="t", approvals_reviewer="auto_review")).state == "thinking"
    assert reducer.ingest_hook(hook("PermissionRequest", turn_id="t", approvals_reviewer="user")).state == "needs_input"


def test_auto_review_preserves_explicit_question_and_error() -> None:
    for state in ("needs_input", "error"):
        reducer = SessionReducer()
        reducer.ingest_report({"session_id": "native-session-123456", "state": state})
        assert reducer.ingest_hook(hook("PermissionRequest", approvals_reviewer="auto_review")).state == state
        assert reducer.ingest_hook(hook("Stop")).state == state


def test_completed_tool_tombstone_prevents_late_pre_event() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit"))
    reducer.ingest_hook(hook("PostToolUse", tool_use_id="late"))
    snapshot = reducer.ingest_hook(hook("PreToolUse", tool_use_id="late", tool_name="Bash"))
    assert snapshot.state == "thinking"
    assert not snapshot.active_tool_ids


def test_non_attention_report_clears_previous_sticky_state() -> None:
    reducer = SessionReducer()
    reducer.ingest_report({"session_id": "native-session-123456", "state": "error"})
    reducer.ingest_report({"session_id": "native-session-123456", "state": "thinking"})
    assert reducer.ingest_hook(hook("Stop")).state == "turn_complete"


def test_late_previous_turn_stop_cannot_overwrite_new_turn() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="old", emitted_at_ns=100))
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="new", emitted_at_ns=300))
    snapshot = reducer.ingest_hook(hook("Stop", turn_id="old", emitted_at_ns=400))
    assert snapshot.state == "thinking"
    assert snapshot.current_turn == "new"


def test_late_tool_event_cannot_reopen_completed_turn() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="turn", emitted_at_ns=100))
    reducer.ingest_hook(hook("Stop", turn_id="turn", emitted_at_ns=300))
    snapshot = reducer.ingest_hook(
        hook(
            "PreToolUse",
            turn_id="turn",
            emitted_at_ns=200,
            tool_use_id="late",
            tool_name="Bash",
        )
    )
    assert snapshot.state == "turn_complete"
    assert not snapshot.active_tool_ids


def test_offline_compare_and_set_rejects_changed_process_binding() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(
        hook("SessionStart", source="startup", source_pid=1, source_create_time=2.0)
    )
    reducer.ingest_hook(
        hook("SessionStart", source="resume", source_pid=3, source_create_time=4.0)
    )
    assert reducer.mark_offline_if_source(
        "native-session-123456", 1, 2.0, "old process exited"
    ) is None
    assert reducer.snapshot("native-session-123456").state == "idle"


def test_stale_hook_cannot_replace_resumed_process_binding() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(
        hook(
            "UserPromptSubmit",
            turn_id="old",
            emitted_at_ns=100,
            source_pid=1,
            source_create_time=2.0,
        )
    )
    reducer.ingest_hook(
        hook(
            "UserPromptSubmit",
            turn_id="new",
            emitted_at_ns=300,
            source_pid=3,
            source_create_time=4.0,
        )
    )
    reducer.ingest_hook(
        hook(
            "Stop",
            turn_id="old",
            emitted_at_ns=400,
            source_pid=1,
            source_create_time=2.0,
        )
    )
    snapshot = reducer.snapshot("native-session-123456")
    assert snapshot.state == "thinking"
    assert (snapshot.source_pid, snapshot.source_create_time) == (3, 4.0)


def test_retired_prompt_cannot_switch_back_to_previous_turn() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="old", emitted_at_ns=100))
    reducer.ingest_hook(hook("UserPromptSubmit", turn_id="new", emitted_at_ns=300))
    snapshot = reducer.ingest_hook(
        hook("UserPromptSubmit", turn_id="old", emitted_at_ns=400)
    )
    assert snapshot.state == "thinking"
    assert snapshot.current_turn == "new"


def test_unbound_resume_clears_old_process_binding() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(
        hook(
            "SessionStart",
            source="startup",
            source_pid=1,
            source_create_time=2.0,
        )
    )
    snapshot = reducer.ingest_hook(hook("SessionStart", source="resume"))
    assert snapshot.source_pid is None
    assert snapshot.source_create_time is None


def test_utf8_truncation_and_snapshot_thread_safety() -> None:
    assert truncate_utf8("你a", 3) == "你"
    reducer = SessionReducer()
    errors: list[Exception] = []

    def update() -> None:
        try:
            for _ in range(50):
                reducer.ingest_report({"session_id": "parallel", "state": "thinking"})
                reducer.snapshots()
        except Exception as exc:  # pragma: no cover - asserted empty below
            errors.append(exc)

    threads = [threading.Thread(target=update) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert reducer.snapshot("parallel").revision == 200
    reducer.mark_published("parallel", reducer.snapshot("parallel").revision, 123.0)
    assert reducer.snapshot("parallel").last_published_at == 123.0
    assert reducer.snapshot("parallel").published_revision == 200
    assert len(reducer.snapshots()) == 1
