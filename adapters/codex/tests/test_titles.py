import asyncio
import json

from agent_monitor_adapter.config import AdapterSettings
from agent_monitor_adapter.service import AdapterRuntime
from agent_monitor_adapter.state import SessionReducer
from agent_monitor_adapter.titles import SessionTitles


def write_entries(path, *entries):
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


def test_index_uses_latest_valid_title_and_ignores_malformed_entries(tmp_path):
    path = tmp_path / "session_index.jsonl"
    write_entries(path,
                  {"id": "a", "thread_name": "Old"},
                  ["not an object"],
                  {"id": "a", "thread_name": " New\n title "},
                  {"id": "b", "thread_name": 42},
                  {"id": "c", "thread_name": "   "})
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"id": "a", "thread_name":')
    titles = SessionTitles(path)
    assert titles.read() == {"a": "New title"}
    titles.read().clear()
    assert titles.read() == {"a": "New title"}
    write_entries(path, {"id": "a", "thread_name": "Renamed"})
    assert titles.read() == {"a": "Renamed"}


def test_missing_or_unreadable_index_is_nonfatal(tmp_path, monkeypatch):
    path = tmp_path / "session_index.jsonl"
    titles = SessionTitles(path)
    assert titles.read() == {}
    write_entries(path, {"id": "a", "thread_name": "Known"})
    assert titles.read() == {"a": "Known"}
    path.unlink()
    assert titles.read() == {"a": "Known"}
    write_entries(path, {"id": "a", "thread_name": "New value"})

    def denied(*args, **kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr(type(path), "open", denied)
    assert titles.read() == {"a": "Known"}


def test_index_respects_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert SessionTitles().path == tmp_path / "session_index.jsonl"


def test_runtime_publishes_title_and_renames_without_changing_activity(tmp_path, monkeypatch):
    class Bridge:
        def __init__(self):
            self.payloads = []

        async def publish(self, payload):
            self.payloads.append(payload)

    now = [0.0]
    monkeypatch.setattr("agent_monitor_adapter.state.time.monotonic", lambda: now[0])
    path = tmp_path / "session_index.jsonl"
    reducer = SessionReducer("host")
    original = reducer.ingest_hook(dict(
        session_id="thread-12345678", hook_event_name="UserPromptSubmit", cwd="/repo/demo",
        turn_id="turn-1"))
    bridge = Bridge()
    runtime = AdapterRuntime(AdapterSettings(), reducer, bridge, titles=SessionTitles(path))
    assert asyncio.run(runtime.publish_once())
    assert bridge.payloads[-1]["name"] == "Codex / demo / 12345678"

    now[0] = 119
    write_entries(path, {"id": original.session_id, "thread_name": "会话标题" * 40},
                  {"id": "other-session", "thread_name": "Unrelated"})
    assert asyncio.run(runtime.publish_once())
    titled = reducer.snapshot(original.session_id)
    assert titled.name.startswith("Codex / 会话标题")
    assert titled.name.endswith(" / 12345678")
    assert len(titled.name.encode("utf-8")) <= 96
    assert titled.id == original.id
    assert (titled.state, titled.detail, titled.timestamp, titled.current_turn) == (
        original.state, original.detail, original.timestamp, original.current_turn)
    assert bridge.payloads[-1]["name"] == titled.name
    count = len(bridge.payloads)
    assert asyncio.run(runtime.publish_once())
    assert len(bridge.payloads) == count

    write_entries(path, {"id": original.session_id, "thread_name": "Renamed"})
    assert asyncio.run(runtime.publish_once())
    assert bridge.payloads[-1]["name"] == "Codex / Renamed / 12345678"
    now[0] = 120
    assert asyncio.run(runtime.publish_once())
    assert bridge.payloads[-1]["state"] == "offline"
