from __future__ import annotations

import hashlib
import json
import ntpath
import threading
import time
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any


STATES = frozenset(
    {"offline", "idle", "thinking", "tool_running", "needs_input", "turn_complete", "error"}
)


def _protocol_id(host: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{host}|claude-code|{session_id}".encode()).hexdigest()
    return f"claude-{digest[:20]}"


def _short(value: Any, limit: int = 512) -> str:
    text = str(value or "")
    raw = text.encode("utf-8")
    return raw[:limit].decode("utf-8", errors="ignore")


@dataclass
class _Session:
    session_id: str
    id: str
    name: str
    host: str
    state: str = "idle"
    detail: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))
    revision: int = 0
    last_activity: float = field(default_factory=time.monotonic)
    offline_since: float | None = None
    source_pid: int | None = None
    source_create_time: float | None = None
    active_tools: set[str] = field(default_factory=set)
    sticky_wait: bool = False
    sticky_state: str | None = None
    sticky_source: str | None = None
    sticky_detail: str | None = None
    last_published_at: float | None = None
    published_revision: int = -1

    def view(self) -> Snapshot:
        return Snapshot(self.session_id, self.id, self.name, self.host, self.state,
                        self.detail, self.timestamp, self.revision, self.source_pid,
                        self.source_create_time, self.last_published_at,
                        self.published_revision)


@dataclass(frozen=True, slots=True)
class Snapshot:
    session_id: str
    id: str
    name: str
    host: str
    state: str
    detail: str
    timestamp: int
    revision: int
    source_pid: int | None
    source_create_time: float | None
    last_published_at: float | None
    published_revision: int

    def as_status(self) -> dict[str, Any]:
        result = {"id": self.id, "name": self.name, "host": self.host,
                  "state": self.state, "detail": self.detail,
                  "timestamp": self.timestamp}
        while len(json.dumps(result, ensure_ascii=True, separators=(",", ":"))) > 1024:
            if result["detail"]:
                result["detail"] = result["detail"][:-16]
            elif result["name"]:
                result["name"] = result["name"][:-8]
            else:
                break
        return result


class SessionReducer:
    """Reduce documented Claude Code hook events into bridge agent statuses."""

    def __init__(self, host: str = "desktop") -> None:
        self.host = _short(host.strip() or "desktop", 96)
        self._lock = threading.RLock()
        self._sessions: dict[str, _Session] = {}

    def _get(self, payload: Mapping[str, Any]) -> _Session:
        native_id = payload.get("session_id")
        if not isinstance(native_id, str) or not native_id.strip():
            raise ValueError("session_id is required")
        key = native_id
        session = self._sessions.get(key)
        if session is None:
            cwd = str(payload.get("cwd") or "").rstrip("\\/")
            project = ntpath.basename(cwd) or "session"
            session = _Session(native_id, _protocol_id(self.host, native_id),
                               _short(f"Claude Code / {project} / {native_id[-8:]}", 96),
                               self.host)
            self._sessions[key] = session
        pid, created = payload.get("source_pid"), payload.get("source_create_time")
        if pid is not None and created is not None:
            try:
                session.source_pid = int(pid)
                session.source_create_time = float(created)
            except (TypeError, ValueError):
                pass
        return session

    @staticmethod
    def _commit(session: _Session, state: str, detail: Any = None) -> None:
        now = time.monotonic()
        session.last_activity = now
        if state == "offline":
            if session.offline_since is None:
                session.offline_since = now
        else:
            session.offline_since = None
        session.state = state
        if detail is not None:
            session.detail = _short(detail)
        session.timestamp = int(time.time())
        session.revision += 1

    def ingest_hook(self, payload: Mapping[str, Any]) -> Snapshot:
        event = str(payload.get("hook_event_name") or "")
        with self._lock:
            session = self._get(payload)
            tool_id = str(payload.get("tool_use_id") or payload.get("tool_name") or "tool")
            tool_name = str(payload.get("tool_name") or "tool")
            if event in {"PreToolUse", "PostToolUse", "PostToolUseFailure"} and "report_status" in tool_name.casefold():
                return session.view()
            if event == "SessionStart":
                if payload.get("source") != "compact":
                    session.sticky_wait = False
                    session.sticky_state = None
                    session.sticky_source = None
                    session.sticky_detail = None
                    if payload.get("source_pid") is None or payload.get("source_create_time") is None:
                        session.source_pid = None
                        session.source_create_time = None
                    self._commit(session, "idle", "Session started or resumed")
            elif event == "UserPromptSubmit":
                session.sticky_wait = False
                session.sticky_state = None
                session.sticky_source = None
                session.sticky_detail = None
                session.active_tools.clear()
                self._commit(session, "thinking", "Working on request")
            elif event == "PreToolUse":
                if session.sticky_source == "hook":
                    session.sticky_wait = False
                    session.sticky_state = None
                    session.sticky_source = None
                if "report_status" not in tool_name.casefold():
                    session.active_tools.add(tool_id)
                    if session.sticky_source == "report":
                        self._commit(session, session.sticky_state or session.state,
                                     session.sticky_detail)
                    else:
                        self._commit(session, "tool_running", tool_name)
            elif event in {"PostToolUse", "PostToolUseFailure"}:
                session.active_tools.discard(tool_id)
                if session.sticky_source == "hook":
                    session.sticky_wait = False
                    session.sticky_state = None
                    session.sticky_source = None
                if session.sticky_wait:
                    self._commit(session, session.sticky_state or "needs_input",
                                 session.sticky_detail)
                elif session.active_tools:
                    self._commit(session, "tool_running")
                else:
                    # A failed tool is part of the task's work, not a task failure.
                    label = "Tool failed; continuing" if event == "PostToolUseFailure" else "Working on request"
                    self._commit(session, "thinking", label)
            elif event == "PermissionRequest":
                session.sticky_wait = True
                session.sticky_state = "needs_input"
                session.sticky_source = "hook"
                session.sticky_detail = None
                self._commit(session, "needs_input", f"Permission required: {tool_name}")
            elif event == "Notification":
                notification_type = payload.get("notification_type")
                if notification_type in {"permission_prompt", "idle_prompt"}:
                    session.sticky_wait = True
                    session.sticky_state = "needs_input"
                    session.sticky_source = "hook"
                    session.sticky_detail = None
                    self._commit(session, "needs_input", "Waiting for user input")
            elif event == "Stop":
                if session.sticky_wait:
                    self._commit(session, session.sticky_state or "needs_input",
                                 session.sticky_detail)
                else:
                    self._commit(session, "turn_complete", "Turn complete")
            elif event == "StopFailure":
                session.sticky_wait = True
                session.sticky_state = "error"
                session.sticky_source = "hook"
                session.sticky_detail = "Claude request failed"
                self._commit(session, "error", "Claude request failed")
            elif event == "SessionEnd":
                session.source_pid = None
                session.source_create_time = None
                self._commit(session, "offline", "Session ended")
            else:
                raise ValueError(f"unsupported Claude Code hook event: {event}")
            return session.view()

    def ingest_report(self, payload: Mapping[str, Any]) -> Snapshot:
        state = str(payload.get("state") or "")
        if state not in STATES:
            raise ValueError(f"unsupported state: {state}")
        with self._lock:
            session = self._get(payload)
            session.sticky_wait = state in {"needs_input", "error"}
            session.sticky_state = state if state in {"needs_input", "error"} else None
            session.sticky_source = "report" if session.sticky_wait else None
            session.sticky_detail = str(payload.get("detail") or "") if session.sticky_wait else None
            self._commit(session, state, payload.get("detail", ""))
            return session.view()

    def collect_expired(self, stale_seconds: float = 120,
                        retention_seconds: float = 300) -> int:
        """Expire unbound sessions and reclaim continuously offline records."""
        with self._lock:
            now = time.monotonic()
            removed = 0
            for key, session in list(self._sessions.items()):
                if session.offline_since is not None:
                    if now - session.offline_since >= retention_seconds:
                        del self._sessions[key]
                        removed += 1
                elif (session.source_pid is None or session.source_create_time is None) and now - session.last_activity >= stale_seconds:
                    self._commit(session, "offline", "Status updates timed out")
            return removed

    def snapshots(self) -> tuple[Snapshot, ...]:
        with self._lock:
            return tuple(session.view() for session in self._sessions.values())

    def mark_published(self, session_id: str, revision: int, at: float) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.last_published_at = at
            session.published_revision = max(session.published_revision, revision)

    def mark_offline_if_source(self, session_id: str, pid: int, created: float) -> Snapshot | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if (session is None or session.state == "offline" or
                    session.source_pid != pid or session.source_create_time != created):
                return None
            self._commit(session, "offline", "Claude Code process exited")
            return session.view()
