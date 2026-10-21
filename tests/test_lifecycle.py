from types import SimpleNamespace
from unittest.mock import Mock

import paho.mqtt.client as mqtt
import pytest

from app.config import Settings
from app.models import AgentStatus
from app.mqtt import MqttPublisher


def status(state="idle", timestamp=1000):
    return AgentStatus(id="test-agent", name="Test", host="host",
                       state=state, timestamp=timestamp)


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.mqtt.time.monotonic", lambda: now[0])
    return now


@pytest.fixture
def publisher():
    publisher = MqttPublisher(Settings())
    publisher._client = Mock()
    publisher._client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    publisher._connected.set()
    return publisher


def test_stale_then_delete_retained_message_and_memory(publisher, clock):
    publisher.publish(status())
    clock[0] = 119
    publisher.collect_expired()
    assert publisher._client.publish.call_count == 1
    clock[0] = 120
    publisher.collect_expired()
    assert publisher._agents["test-agent"].status.state == "offline"
    clock[0] = 419
    publisher.collect_expired()
    assert publisher._agents
    clock[0] = 420
    publisher.collect_expired()
    assert not publisher._agents
    publisher._client.publish.assert_called_with(
        "agent-monitor/v1/agents/test-agent/state", "", qos=1, retain=True)


def test_offline_repeats_do_not_reset_timer_and_revival_cancels(publisher, clock):
    publisher.publish(status("offline"))
    clock[0] = 299
    publisher.publish(status("offline"))
    clock[0] = 300
    publisher.collect_expired()
    assert not publisher._agents
    publisher.publish(status("offline"))
    clock[0] = 599
    publisher.publish(status("thinking"))
    clock[0] = 600
    publisher.collect_expired()
    assert publisher._agents["test-agent"].status.state == "thinking"
    assert publisher._agents["test-agent"].offline_since is None


def test_disconnected_cleanup_is_retried(publisher, clock):
    publisher.publish(status("offline"))
    clock[0] = 300
    publisher._connected.clear()
    publisher.collect_expired()
    assert publisher._agents
    publisher._connected.set()
    publisher._client.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
    publisher.collect_expired()
    assert publisher._agents
    publisher._client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    publisher.collect_expired()
    assert not publisher._agents


def test_restart_recovers_old_retained_entries(publisher, clock, monkeypatch):
    monkeypatch.setattr("app.mqtt.time.time", lambda: 1300)
    publisher._on_message(None, None, SimpleNamespace(
        retain=True, topic="agent-monitor/v1/agents/test-agent/state",
        payload=status("offline", timestamp=1000).to_mqtt_payload().encode()))
    publisher.collect_expired()
    assert not publisher._agents


def test_retained_replay_cannot_override_live_update(publisher, clock):
    publisher.publish(status("thinking"))
    publisher._on_message(None, None, SimpleNamespace(
        retain=True, topic="agent-monitor/v1/agents/test-agent/state",
        payload=status("offline").to_mqtt_payload().encode()))
    assert publisher._agents["test-agent"].status.state == "thinking"
