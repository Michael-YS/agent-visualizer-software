import importlib

from agent_monitor_adapter.state import SessionReducer


def test_reclaim_offline_without_resetting_on_duplicate(monkeypatch):
    state = importlib.import_module("agent_monitor_adapter.state")
    now = [0.0]
    monkeypatch.setattr(state.time, "monotonic", lambda: now[0])
    reducer = SessionReducer("host")
    payload = {"session_id": "old", "state": "offline"}
    reducer.ingest_report(payload)
    now[0] = 299
    reducer.ingest_report(payload)
    assert reducer.collect_expired() == 0
    now[0] = 300
    assert reducer.collect_expired() == 1
    assert not reducer.snapshots()
    reducer.ingest_report({"session_id": "old", "state": "idle"})
    assert len(reducer.snapshots()) == 1


def test_unbound_expiry_preserves_bound_and_revived_sessions(monkeypatch):
    state = importlib.import_module("agent_monitor_adapter.state")
    now = [0.0]
    monkeypatch.setattr(state.time, "monotonic", lambda: now[0])
    reducer = SessionReducer("host")
    reducer.ingest_report({"session_id": "unbound", "state": "idle"})
    reducer.ingest_report({"session_id": "bound", "state": "idle",
                           "source_pid": 123, "source_create_time": 10})
    now[0] = 120
    reducer.collect_expired()
    states = {s.session_id: s.state for s in reducer.snapshots()}
    assert states == {"unbound": "offline", "bound": "idle"}
    now[0] = 419
    reducer.ingest_report({"session_id": "unbound", "state": "thinking"})
    now[0] = 420
    assert reducer.collect_expired() == 0
    assert len(reducer.snapshots()) == 2
