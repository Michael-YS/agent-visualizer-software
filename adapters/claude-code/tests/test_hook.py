import json

from claude_code_adapter import hook


def test_session_start_returns_exact_session_context(monkeypatch, capsys):
    monkeypatch.setattr(hook, "submit", lambda event: None)
    event = {"hook_event_name": "SessionStart", "session_id": "exact/quoted\"id"}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(event)))
    hook.main()
    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert json.loads(context.split("session_id = ", 1)[1].split(". When", 1)[0]) == event["session_id"]


def test_transport_error_is_fail_open(monkeypatch):
    monkeypatch.setattr(hook, "_claude_ancestor", lambda: (None, None))
    def unavailable(*args, **kwargs):
        raise OSError("adapter is down")
    monkeypatch.setattr(hook.urllib.request, "urlopen", unavailable)
    hook.submit({"hook_event_name": "Stop", "session_id": "s"})
