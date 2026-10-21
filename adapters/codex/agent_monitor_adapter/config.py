from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class AdapterSettings:
    bridge_url: str = "http://127.0.0.1:8000"
    listen_host: str = "127.0.0.1"
    listen_port: int = 18765
    heartbeat_seconds: float = 30.0
    retry_seconds: float = 2.0
    process_check_seconds: float = 5.0
    bridge_timeout_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "AdapterSettings":
        load_dotenv()
        port = int(os.getenv("AGENT_MONITOR_ADAPTER_PORT", "18765"))
        if not 1 <= port <= 65535:
            raise ValueError("AGENT_MONITOR_ADAPTER_PORT must be between 1 and 65535")
        return cls(
            bridge_url=os.getenv(
                "AGENT_MONITOR_BRIDGE_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            listen_host=os.getenv("AGENT_MONITOR_ADAPTER_HOST", "127.0.0.1"),
            listen_port=port,
            heartbeat_seconds=_positive_float(
                "AGENT_MONITOR_HEARTBEAT_SECONDS", 30.0
            ),
            retry_seconds=_positive_float("AGENT_MONITOR_RETRY_SECONDS", 2.0),
            process_check_seconds=_positive_float(
                "AGENT_MONITOR_PROCESS_CHECK_SECONDS", 5.0
            ),
            bridge_timeout_seconds=_positive_float(
                "AGENT_MONITOR_BRIDGE_TIMEOUT_SECONDS", 2.0
            ),
        )
