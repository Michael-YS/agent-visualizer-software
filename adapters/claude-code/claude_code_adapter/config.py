from __future__ import annotations

import os
from dataclasses import dataclass


def _positive(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bridge_url: str = "http://127.0.0.1:8000"
    host: str = "127.0.0.1"
    port: int = 18766
    heartbeat_seconds: float = 30.0
    retry_seconds: float = 2.0
    process_check_seconds: float = 5.0
    bridge_timeout_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.getenv("AGENT_MONITOR_CLAUDE_ADAPTER_PORT", "18766"))
        if not 1 <= port <= 65535:
            raise ValueError("AGENT_MONITOR_CLAUDE_ADAPTER_PORT must be 1..65535")
        return cls(
            bridge_url=os.getenv(
                "AGENT_MONITOR_CLAUDE_BRIDGE_URL",
                os.getenv("AGENT_MONITOR_BRIDGE_URL", "http://127.0.0.1:8000"),
            ).rstrip("/"),
            host=os.getenv("AGENT_MONITOR_CLAUDE_ADAPTER_HOST", "127.0.0.1"),
            port=port,
            heartbeat_seconds=_positive("AGENT_MONITOR_CLAUDE_HEARTBEAT_SECONDS", 30),
            retry_seconds=_positive("AGENT_MONITOR_CLAUDE_RETRY_SECONDS", 2),
            process_check_seconds=_positive(
                "AGENT_MONITOR_CLAUDE_PROCESS_CHECK_SECONDS", 5
            ),
            bridge_timeout_seconds=_positive(
                "AGENT_MONITOR_CLAUDE_BRIDGE_TIMEOUT_SECONDS", 2
            ),
        )
