from types import SimpleNamespace
from unittest.mock import Mock

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AgentState, AgentStatus
from app.mqtt import MqttPublisher


@pytest.fixture
def monitor(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.mqtt.time.monotonic", lambda: now[0])
    publisher = MqttPublisher(Settings())
    publisher._client = Mock()
    publisher._client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    publisher._connected.set()
    monkeypatch.setattr(publisher, "start", lambda: None)
    monkeypatch.setattr(publisher, "stop", lambda: None)
    with TestClient(create_app(Settings(), publisher)) as client:
        yield client, publisher, now


def test_dashboard_and_assets_are_served(monitor):
    client, _, _ = monitor
    page = client.get("/")
    assert page.status_code == 200
    assert "Agent 运行状态" in page.text
    assert "no-store" in page.headers["cache-control"]
    for path, content_type in [("style.css", "text/css"), ("dashboard.js", "javascript")]:
        response = client.get(f"/static/{path}")
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]


def test_empty_list_and_unknown_agent(monitor):
    client, _, _ = monitor
    response = client.get("/v1/agents")
    assert response.json() == {"agents": [], "total": 0, "mqtt_connected": True}
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/v1/agents/missing").status_code == 404


def test_queries_follow_reports_for_every_state(monitor):
    client, _, _ = monitor
    for index, state in enumerate(AgentState):
        payload = dict(id=f"agent-{index}", name="测试 Agent", host="desktop",
                       state=state.value, detail="<script>untrusted</script>", timestamp=1000)
        assert client.post("/v1/agents/state", json=payload).status_code == 202
        response = client.get(f"/v1/agents/agent-{index}")
        assert response.json() == payload
        assert response.headers["cache-control"] == "no-store"
    listing = client.get("/v1/agents").json()
    assert listing["total"] == len(AgentState)
    assert [a["state"] for a in listing["agents"]] == [s.value for s in AgentState]
    assert client.post("/v1/agents/state", json=dict(
        id="agent-0", name="Updated", host="desktop", state="thinking"
    )).status_code == 202
    assert client.get("/v1/agents/agent-0").json()["name"] == "Updated"
    assert client.get("/v1/agents").json()["total"] == len(AgentState)


def test_api_shares_lifecycle_and_retained_recovery(monitor):
    client, publisher, now = monitor
    recovered = AgentStatus(id="recovered", name="Recovered", host="pc", state="thinking")
    publisher._on_message(None, None, SimpleNamespace(
        retain=True, topic="agent-monitor/v1/agents/recovered/state",
        payload=recovered.to_mqtt_payload().encode()))
    assert client.get("/v1/agents/recovered").json()["state"] == "thinking"
    now[0] = 120
    publisher.collect_expired()
    assert client.get("/v1/agents/recovered").json()["state"] == "offline"
    now[0] = 420
    publisher.collect_expired()
    assert client.get("/v1/agents/recovered").status_code == 404
    assert client.get("/v1/agents").json()["total"] == 0


def test_reads_remain_available_during_mqtt_outage(monitor):
    client, publisher, _ = monitor
    publisher.publish(AgentStatus(id="test", name="Test", host="pc", state="idle"))
    publisher._connected.clear()
    listing = client.get("/v1/agents").json()
    assert listing["mqtt_connected"] is False
    assert listing["agents"][0]["state"] == "idle"
    assert client.get("/v1/agents/test").status_code == 200
    assert client.post("/v1/agents/state", json=dict(
        id="test", name="Test", host="pc", state="error"
    )).status_code == 503
    assert client.get("/v1/agents/test").json()["state"] == "idle"


def test_snapshot_is_isolated_and_sorted(monitor):
    _, publisher, _ = monitor
    for agent_id in ["z", "a"]:
        publisher.publish(AgentStatus(id=agent_id, name="Test", host="pc", state="idle"))
    snapshot = publisher.snapshot()
    assert [agent.id for agent in snapshot] == ["a", "z"]
    snapshot[0].detail = "mutated"
    snapshot.clear()
    assert len(publisher.snapshot()) == 2
    assert publisher.snapshot()[0].detail == ""
