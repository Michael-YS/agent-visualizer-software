import time
from dataclasses import dataclass
from threading import Event, RLock, Thread

import paho.mqtt.client as mqtt

from app.config import Settings
from app.models import AgentState, AgentStatus


class MqttUnavailable(RuntimeError):
    """Raised when an event cannot be handed to the MQTT client."""


@dataclass
class TrackedAgent:
    status: AgentStatus
    last_seen: float
    offline_since: float | None


class MqttPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connected = Event()
        self._stopping = Event()
        self._lock = RLock()
        self._agents: dict[str, TrackedAgent] = {}
        self._maintenance: Thread | None = None
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            self._client.username_pw_set(
                settings.mqtt_username, settings.mqtt_password
            )

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        self._stopping.clear()
        self._client.connect_async(
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            keepalive=30,
        )
        self._client.loop_start()
        self._maintenance = Thread(target=self._maintenance_loop, daemon=True)
        self._maintenance.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._maintenance is not None:
            self._maintenance.join()
        self._connected.clear()
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, status: AgentStatus) -> str:
        with self._lock:
            topic = self._publish(status.id, status.to_mqtt_payload())
            now = time.monotonic()
            previous = self._agents.get(status.id)
            offline_since = None
            if status.state == AgentState.OFFLINE:
                offline_since = (previous.offline_since if previous is not None
                                 and previous.offline_since is not None else now)
            self._agents[status.id] = TrackedAgent(status, now, offline_since)
            return topic

    def _publish(self, agent_id: str, payload: str) -> str:
        if not self.is_connected:
            raise MqttUnavailable("MQTT broker is not connected")

        topic = (
            f"{self._settings.mqtt_topic_prefix.rstrip('/')}"
            f"/agents/{agent_id}/state"
        )
        result = self._client.publish(topic, payload, qos=1, retain=True)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttUnavailable(f"MQTT publish failed with code {result.rc}")
        return topic

    def collect_expired(self) -> None:
        # Serialize cleanup and incoming updates so a revival cannot be deleted.
        with self._lock:
            now = time.monotonic()
            for agent_id, agent in list(self._agents.items()):
                try:
                    if agent.offline_since is not None:
                        if now - agent.offline_since >= self._settings.agent_offline_retention_seconds:
                            # An empty retained payload deletes the broker's saved message.
                            self._publish(agent_id, "")
                            del self._agents[agent_id]
                    elif now - agent.last_seen >= self._settings.agent_stale_seconds:
                        offline = agent.status.model_copy(update={
                            "state": AgentState.OFFLINE,
                            "detail": "Status updates timed out",
                            "timestamp": int(time.time()),
                        })
                        self._publish(agent_id, offline.to_mqtt_payload())
                        agent.status = offline
                        agent.offline_since = now
                except MqttUnavailable:
                    # Keep pending cleanup until the broker is reachable again.
                    continue

    def _maintenance_loop(self) -> None:
        while not self._stopping.wait(1):
            self.collect_expired()

    def _on_message(self, client, userdata, message) -> None:
        # Recover retained entries after a bridge restart, including older agents.
        if not message.retain or not message.payload:
            return
        try:
            status = AgentStatus.model_validate_json(message.payload)
        except ValueError:
            return
        expected_topic = f"{self._settings.mqtt_topic_prefix.rstrip('/')}/agents/{status.id}/state"
        if message.topic != expected_topic:
            return
        with self._lock:
            if status.id not in self._agents:
                now = time.monotonic()
                received_at = now - max(0, time.time() - status.timestamp)
                self._agents[status.id] = TrackedAgent(
                    status, received_at,
                    received_at if status.state == AgentState.OFFLINE else None,
                )

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self._connected.set()
            client.subscribe(f"{self._settings.mqtt_topic_prefix.rstrip('/')}/agents/+/state", qos=1)
        else:
            self._connected.clear()

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties
    ) -> None:
        self._connected.clear()
