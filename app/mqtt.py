from threading import Event

import paho.mqtt.client as mqtt

from app.config import Settings
from app.models import AgentStatus


class MqttUnavailable(RuntimeError):
    """Raised when an event cannot be handed to the MQTT client."""


class MqttPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connected = Event()
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            self._client.username_pw_set(
                settings.mqtt_username, settings.mqtt_password
            )

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        self._client.connect_async(
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            keepalive=30,
        )
        self._client.loop_start()

    def stop(self) -> None:
        self._connected.clear()
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, status: AgentStatus) -> str:
        if not self.is_connected:
            raise MqttUnavailable("MQTT broker is not connected")

        topic = (
            f"{self._settings.mqtt_topic_prefix.rstrip('/')}"
            f"/agents/{status.id}/state"
        )
        payload = status.to_mqtt_payload()
        result = self._client.publish(topic, payload, qos=1, retain=True)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttUnavailable(f"MQTT publish failed with code {result.rc}")
        return topic

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self._connected.set()
        else:
            self._connected.clear()

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties
    ) -> None:
        self._connected.clear()
