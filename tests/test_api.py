from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AgentStatus
from app.mqtt import MqttUnavailable


class FakePublisher:
    def __init__(self, connected: bool = True) -> None:
        self.is_connected = connected
        self.messages: list[AgentStatus] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def publish(self, status: AgentStatus) -> str:
        if not self.is_connected:
            raise MqttUnavailable("MQTT broker is not connected")
        self.messages.append(status)
        return f"agent-monitor/v1/agents/{status.id}/state"


def test_publishes_normalized_status() -> None:
    publisher = FakePublisher()
    app = create_app(Settings(), publisher)

    with TestClient(app) as client:
        response = client.post(
            "/v1/agents/state",
            json={
                "id": "codex-m3u8",
                "name": "Codex / M3U8",
                "host": "desktop",
                "state": "needs_input",
                "detail": "Approve command",
                "timestamp": 1789940000,
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "topic": "agent-monitor/v1/agents/codex-m3u8/state",
    }
    assert publisher.messages[0].state.value == "needs_input"


def test_rejects_unknown_state() -> None:
    app = create_app(Settings(), FakePublisher())
    with TestClient(app) as client:
        response = client.post(
            "/v1/agents/state",
            json={
                "id": "agent-1",
                "name": "Agent",
                "host": "desktop",
                "state": "running",
            },
        )

    assert response.status_code == 422


def test_rejects_topic_injection_in_agent_id() -> None:
    app = create_app(Settings(), FakePublisher())
    with TestClient(app) as client:
        response = client.post(
            "/v1/agents/state",
            json={
                "id": "../../other-topic",
                "name": "Agent",
                "host": "desktop",
                "state": "idle",
            },
        )

    assert response.status_code == 422


def test_rejects_utf8_field_that_exceeds_firmware_limit() -> None:
    app = create_app(Settings(), FakePublisher())
    with TestClient(app) as client:
        response = client.post(
            "/v1/agents/state",
            json={
                "id": "agent-1",
                "name": "Agent",
                "host": "desktop",
                "state": "thinking",
                "detail": "界" * 200,
            },
        )

    assert response.status_code == 422


def test_returns_503_while_mqtt_is_disconnected() -> None:
    app = create_app(Settings(), FakePublisher(connected=False))
    with TestClient(app) as client:
        response = client.post(
            "/v1/agents/state",
            json={
                "id": "agent-1",
                "name": "Agent",
                "host": "desktop",
                "state": "idle",
            },
        )

    assert response.status_code == 503


def test_health_reports_mqtt_state() -> None:
    app = create_app(Settings(), FakePublisher(connected=False))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "mqtt_connected": False}
