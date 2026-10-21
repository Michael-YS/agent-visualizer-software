import asyncio
from typing import Any

from fastapi.testclient import TestClient

from agent_monitor_adapter.client import BridgeUnavailable
from agent_monitor_adapter.config import AdapterSettings
from agent_monitor_adapter.service import AdapterRuntime, create_app
from agent_monitor_adapter.state import SessionReducer


class FakeBridge:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.payloads: list[dict[str, Any]] = []
        self.closed = False

    async def publish(self, payload: dict[str, Any]) -> None:
        if self.fail:
            raise BridgeUnavailable("bridge down")
        self.payloads.append(payload)

    async def close(self) -> None:
        self.closed = True


def settings() -> AdapterSettings:
    return AdapterSettings(
        heartbeat_seconds=30,
        retry_seconds=60,
        process_check_seconds=60,
    )


def test_api_accepts_hook_and_report_for_same_session() -> None:
    reducer = SessionReducer("test-host")
    bridge = FakeBridge()
    app = create_app(settings(), reducer, bridge, lambda _pid, _created: True)

    with TestClient(app) as client:
        hook_response = client.post(
            "/v1/events/codex",
            json={
                "event": {
                    "hook_event_name": "SessionStart",
                    "session_id": "thread-1",
                    "cwd": r"C:\repo\demo",
                    "source": "startup",
                },
                "source_pid": 123,
                "source_started_at": 10.0,
            },
        )
        report_response = client.post(
            "/v1/reports",
            json={
                "session_id": "thread-1",
                "state": "needs_input",
                "detail": "Choose an option",
            },
        )

    assert hook_response.status_code == 202
    assert report_response.status_code == 202
    assert hook_response.json()["id"] == report_response.json()["id"]
    assert reducer.snapshot("thread-1").state == "needs_input"
    assert bridge.closed


def test_api_rejects_missing_session_and_unknown_event() -> None:
    app = create_app(settings(), SessionReducer(), FakeBridge())
    with TestClient(app) as client:
        missing = client.post(
            "/v1/events/codex", json={"event": {"hook_event_name": "Stop"}}
        )
        unknown = client.post(
            "/v1/events/codex",
            json={"event": {"hook_event_name": "Other", "session_id": "x"}},
        )
    assert missing.status_code == 422
    assert unknown.status_code == 422


def test_runtime_retries_latest_state_and_heartbeats_only_bound_sessions() -> None:
    reducer = SessionReducer("host")
    reducer.ingest_hook(
        {
            "hook_event_name": "SessionStart",
            "session_id": "hooked",
            "source": "startup",
            "source_pid": 12,
            "source_create_time": 3.0,
        }
    )
    reducer.ingest_report({"session_id": "report-only", "state": "thinking"})
    bridge = FakeBridge(fail=True)
    runtime = AdapterRuntime(settings(), reducer, bridge)

    assert asyncio.run(runtime.publish_once()) is False
    assert reducer.snapshot("hooked").published_revision == -1
    reducer.ingest_hook(
        {"hook_event_name": "UserPromptSubmit", "session_id": "hooked"}
    )
    bridge.fail = False
    assert asyncio.run(runtime.publish_once()) is True
    assert {item["state"] for item in bridge.payloads} == {"thinking"}

    bridge.payloads.clear()
    reducer.mark_published("hooked", reducer.snapshot("hooked").revision, 0)
    reducer.mark_published("report-only", reducer.snapshot("report-only").revision, 0)
    assert asyncio.run(runtime.publish_once()) is True
    assert [item["id"] for item in bridge.payloads] == [reducer.snapshot("hooked").id]


def test_dead_bound_process_marks_session_offline() -> None:
    reducer = SessionReducer()
    reducer.ingest_hook(
        {
            "hook_event_name": "SessionStart",
            "session_id": "dead",
            "source": "startup",
            "source_pid": 99,
            "source_create_time": 1.0,
        }
    )
    runtime = AdapterRuntime(settings(), reducer, FakeBridge(), lambda _pid, _created: False)
    asyncio.run(runtime.check_processes_once())
    assert reducer.snapshot("dead").state == "offline"
