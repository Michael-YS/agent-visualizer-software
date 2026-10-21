import asyncio

from claude_code_adapter.config import Settings
from claude_code_adapter.service import Runtime
from claude_code_adapter.state import SessionReducer


class Bridge:
    def __init__(self):
        self.calls = []
        self.fail = True

    async def publish(self, payload):
        self.calls.append(payload)
        if self.fail:
            from claude_code_adapter.client import BridgeUnavailable
            raise BridgeUnavailable("offline")

    async def close(self):
        pass


def test_bridge_failure_retries_latest_and_unbound_session_has_no_heartbeat():
    async def run():
        reducer, bridge = SessionReducer(), Bridge()
        reducer.ingest_hook({"session_id": "s", "hook_event_name": "SessionStart"})
        settings = Settings(heartbeat_seconds=30)
        runtime = Runtime(settings, reducer, bridge)
        assert not await runtime.publish_once()
        reducer.ingest_hook({"session_id": "s", "hook_event_name": "UserPromptSubmit"})
        bridge.fail = False
        assert await runtime.publish_once()
        assert len(bridge.calls) == 2
        assert bridge.calls[1]["state"] == "thinking"
        assert not Runtime._due(reducer.snapshots()[0], 10**9, 30)
        reducer.ingest_hook({"session_id": "s", "hook_event_name": "UserPromptSubmit",
                             "source_pid": 44, "source_create_time": 50.0})
        assert Runtime._due(reducer.snapshots()[0], 10**9, 30)
        reducer.ingest_hook({"session_id": "s", "hook_event_name": "SessionEnd"})
        assert Runtime._due(reducer.snapshots()[0], 10**9, 30)  # final offline update
        assert await runtime.publish_once()
        assert not Runtime._due(reducer.snapshots()[0], 10**9, 30)
    asyncio.run(run())
