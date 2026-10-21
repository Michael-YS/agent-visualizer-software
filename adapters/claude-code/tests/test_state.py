from claude_code_adapter.state import SessionReducer


def event(name, **values):
    return {"session_id": "session-12345678", "cwd": r"C:\work\demo",
            "hook_event_name": name, **values}


def test_tool_failure_is_recoverable_but_stop_failure_is_error():
    reducer = SessionReducer("host")
    reducer.ingest_hook(event("UserPromptSubmit"))
    reducer.ingest_hook(event("PreToolUse", tool_name="Bash", tool_use_id="tool-1"))
    failed_tool = reducer.ingest_hook(event("PostToolUseFailure", tool_name="Bash",
                                            tool_use_id="tool-1", error="Exit code 1"))
    assert failed_tool.state == "thinking"
    api_failure = reducer.ingest_hook(event("StopFailure", error="overloaded"))
    assert api_failure.state == "error"
    assert reducer.ingest_hook(event("Stop")).state == "error"


def test_notification_wait_survives_stop_and_new_prompt_clears_it():
    reducer = SessionReducer()
    reducer.ingest_hook(event("Notification", notification_type="permission_prompt",
                              message="Claude needs your permission"))
    assert reducer.ingest_hook(event("Stop")).state == "needs_input"
    assert reducer.ingest_hook(event("UserPromptSubmit")).state == "thinking"


def test_permission_resolution_clears_hook_wait_but_manual_wait_sticks():
    reducer = SessionReducer()
    reducer.ingest_hook(event("PreToolUse", tool_name="Bash", tool_use_id="t1"))
    reducer.ingest_hook(event("PermissionRequest", tool_name="Bash",
                              tool_input={"description": "sensitive shell command"}))
    assert reducer.ingest_hook(event("PostToolUse", tool_name="Bash", tool_use_id="t1")).state == "thinking"
    assert reducer.ingest_hook(event("Stop")).state == "turn_complete"
    reducer.ingest_report({"session_id": "session-12345678", "state": "needs_input",
                           "detail": "Please choose"})
    assert reducer.ingest_hook(event("Stop")).state == "needs_input"


def test_hook_errors_and_notifications_do_not_copy_possible_secrets():
    reducer = SessionReducer()
    reducer.ingest_hook(event("StopFailure", error="token=secret prompt payload"))
    assert reducer.snapshots()[0].detail == "Claude request failed"
    reducer.ingest_hook(event("Notification", notification_type="idle_prompt",
                              message="private prompt contents"))
    assert reducer.snapshots()[0].detail == "Waiting for user input"


def test_unbound_resume_drops_previous_process_binding():
    reducer = SessionReducer()
    reducer.ingest_hook(event("SessionStart", source_pid=10, source_create_time=20))
    resumed = reducer.ingest_hook(event("SessionStart", source="resume"))
    assert resumed.source_pid is None
    assert resumed.source_create_time is None


def test_manual_wait_state_and_detail_survive_later_tool_lifecycle():
    reducer = SessionReducer()
    manual = reducer.ingest_report({"session_id": "session-12345678", "state": "needs_input",
                                    "detail": "Waiting for design approval"})
    reducer.ingest_hook(event("PreToolUse", tool_name="Bash", tool_use_id="t2"))
    reducer.ingest_hook(event("PostToolUse", tool_name="Bash", tool_use_id="t2"))
    stopped = reducer.ingest_hook(event("Stop"))
    assert stopped.state == manual.state
    assert stopped.detail == manual.detail


def test_identity_required_and_bridge_frame_bounded():
    reducer = SessionReducer("host")
    try:
        reducer.ingest_hook({"hook_event_name": "SessionStart"})
    except ValueError as error:
        assert "session_id" in str(error)
    else:
        raise AssertionError("missing session_id accepted")
    snapshot = reducer.ingest_hook(event("SessionStart", source_pid=4,
                                         source_create_time=123.0))
    import json
    assert snapshot.id.startswith("claude-")
    assert len(json.dumps(snapshot.as_status(), ensure_ascii=True,
                          separators=(",", ":"))) <= 1024
    assert snapshot.source_pid == 4
