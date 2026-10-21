from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_client_id: str = "agent-monitor-bridge"
    mqtt_topic_prefix: str = "agent-monitor/v1"
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    agent_stale_seconds: float = Field(default=120, gt=0)
    agent_offline_retention_seconds: float = Field(default=300, gt=0)
