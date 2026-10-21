import json
from enum import Enum
from time import time

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


MAX_MQTT_PAYLOAD_BYTES = 1024
FIELD_BYTE_LIMITS = {"name": 96, "host": 96, "detail": 512}


class AgentState(str, Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_RUNNING = "tool_running"
    NEEDS_INPUT = "needs_input"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"


class AgentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=96)
    host: str = Field(min_length=1, max_length=96)
    state: AgentState
    detail: str = Field(default="", max_length=512)
    timestamp: int = Field(default_factory=lambda: int(time()), ge=0)

    @field_validator("id", "name", "host")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("name", "host", "detail")
    @classmethod
    def enforce_firmware_byte_limits(
        cls, value: str, info: ValidationInfo
    ) -> str:
        byte_limit = FIELD_BYTE_LIMITS[info.field_name]
        if len(value.encode("utf-8")) > byte_limit:
            raise ValueError(f"must be at most {byte_limit} UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def enforce_mqtt_payload_limit(self) -> "AgentStatus":
        if len(self.to_mqtt_payload().encode("utf-8")) > MAX_MQTT_PAYLOAD_BYTES:
            raise ValueError(
                f"serialized message must be at most {MAX_MQTT_PAYLOAD_BYTES} bytes"
            )
        return self

    def to_mqtt_payload(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class PublishResponse(BaseModel):
    accepted: bool
    topic: str


class HealthResponse(BaseModel):
    status: str
    mqtt_connected: bool


class AgentListResponse(BaseModel):
    agents: list[AgentStatus]
    total: int
    mqtt_connected: bool
