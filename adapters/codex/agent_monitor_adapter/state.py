"""Thread-safe reducer for Codex hook events and explicit status reports."""

from __future__ import annotations

import hashlib
import json
import ntpath
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping


STATES = frozenset(
    {"offline", "idle", "thinking", "tool_running", "needs_input", "turn_complete", "error"}
)
MAX_DETAIL_BYTES = 512
MAX_NAME_BYTES = 96
MAX_HOST_BYTES = 96


def truncate_utf8(value: Any, max_bytes: int) -> str:
    """Convert to text and truncate without returning a partial UTF-8 sequence."""
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _protocol_id(host: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{host}|codex|{session_id}".encode("utf-8")).hexdigest()
    return f"codex-{digest[:20]}"


def _tool_id(payload: Mapping[str, Any]) -> str | None:
    for key in ("tool_call_id", "call_id", "tool_use_id", "invocation_id"):
        value = payload.get(key)
        if value is not None and str(value):
            return str(value)
    return None


def _is_adapter_tool(name: Any) -> bool:
    normalized = str(name or "").lower().replace("-", "_")
    return normalized == "report_status" or (
        "agent_monitor" in normalized and "report_status" in normalized
    )


@dataclass
class _Session:
    session_id: str
    host: str
    name: str
    id: str
    state: str = "idle"
    detail: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))
    revision: int = 0
    last_activity: float = field(default_factory=time.monotonic)
    offline_since: float | None = None
    active_tool_ids: set[str] = field(default_factory=set)
    completed_tool_ids: set[str] = field(default_factory=set)
    current_turn: Any = None
    completed_turns: set[Any] = field(default_factory=set)
    turn_number: int = 0
    sticky_state: str | None = None
    sticky_source: str | None = None
    source_pid: int | None = None
    source_create_time: float | None = None
    last_published_at: float | None = None
    published_revision: int = -1
    latest_event_ns: int = 0

    def view(self) -> "SessionSnapshot":
        return SessionSnapshot(
            session_id=self.session_id,
            id=self.id,
            name=self.name,
            host=self.host,
            state=self.state,
            detail=self.detail,
            timestamp=self.timestamp,
            revision=self.revision,
            active_tool_ids=frozenset(self.active_tool_ids),
            completed_tool_ids=frozenset(self.completed_tool_ids),
            current_turn=self.current_turn,
            source_pid=self.source_pid,
            source_create_time=self.source_create_time,
            last_published_at=self.last_published_at,
            published_revision=self.published_revision,
        )


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    id: str
    name: str
    host: str
    state: str
    detail: str
    timestamp: int
    revision: int
    active_tool_ids: frozenset[str]
    completed_tool_ids: frozenset[str]
    current_turn: Any
    source_pid: int | None
    source_create_time: float | None
    last_published_at: float | None
    published_revision: int

    def as_status(self) -> dict[str, Any]:
        """Return fields accepted by the HTTP bridge AgentStatus model."""
        payload = {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "state": self.state,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }
        # Escaped quotes/control characters can exceed the MQTT limit even
        # when all individual fields satisfy their UTF-8 limits.
        for field in ("detail", "name", "host"):
            minimum = 0 if field == "detail" else 1
            while len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 1024:
                if len(payload[field]) <= minimum:
                    break
                payload[field] = payload[field][:-1]
        return payload


class SessionReducer:
    """Reduce hook and MCP report events into one snapshot per Codex session."""

    def __init__(self, host: str = "desktop") -> None:
        self.host = truncate_utf8(host.strip() or "desktop", MAX_HOST_BYTES)
        self._lock = threading.RLock()
        self._sessions: dict[str, _Session] = {}

    def _get_or_create(
        self, payload: Mapping[str, Any], *, update_source: bool = True
    ) -> _Session:
        native_id = payload.get("session_id")
        if native_id is None or not str(native_id).strip():
            raise ValueError("session_id is required")
        session_id = str(native_id)
        host = truncate_utf8(str(payload.get("host") or self.host).strip() or self.host, MAX_HOST_BYTES)
        key = f"{host}|{session_id}"
        session = self._sessions.get(key)
        if session is None:
            cwd = str(payload.get("cwd") or "").rstrip("\\/")
            project = ntpath.basename(cwd) or "session"
            name = truncate_utf8(f"Codex / {project} / {session_id[-8:]}", MAX_NAME_BYTES)
            session = _Session(
                session_id=session_id,
                host=host,
                name=name,
                id=_protocol_id(host, session_id),
            )
            self._sessions[key] = session
        if update_source:
            self._update_source(session, payload)
        return session

    @staticmethod
    def _update_source(session: _Session, payload: Mapping[str, Any]) -> None:
        pid = payload.get("source_pid", payload.get("pid"))
        created = payload.get("source_create_time", payload.get("process_create_time"))
        if pid is not None:
            try:
                session.source_pid = int(pid)
            except (TypeError, ValueError):
                pass
        if created is not None:
            try:
                session.source_create_time = float(created)
            except (TypeError, ValueError):
                pass

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
            session.detail = truncate_utf8(detail, MAX_DETAIL_BYTES)
        session.timestamp = int(time.time())
        session.revision += 1

    def ingest_hook(self, payload: Mapping[str, Any]) -> SessionSnapshot:
        event = str(payload.get("hook_event_name") or payload.get("event") or "")
        with self._lock:
            session = self._get_or_create(payload, update_source=False)
            turn = payload.get("turn_id", payload.get("turn"))
            try:
                emitted_at = int(payload.get("emitted_at_ns") or 0)
            except (TypeError, ValueError):
                emitted_at = 0
            is_tool_event = event in {"PreToolUse", "PostToolUse"}
            if (
                event != "SessionEnd"
                and turn is not None
                and turn in session.completed_turns
            ):
                return session.view()
            if (
                event == "UserPromptSubmit"
                and turn is not None
                and session.current_turn not in {None, turn}
            ):
                session.completed_turns.add(session.current_turn)
            if (
                is_tool_event
                and session.state in {"turn_complete", "idle", "offline"}
                and emitted_at
                and emitted_at < session.latest_event_ns
            ):
                return session.view()
            if (
                event != "SessionEnd"
                and not is_tool_event
                and emitted_at
                and emitted_at < session.latest_event_ns
            ):
                return session.view()
            if turn is not None and session.current_turn not in {None, turn}:
                if emitted_at and emitted_at < session.latest_event_ns:
                    return session.view()
                session.active_tool_ids.clear()
                session.completed_tool_ids.clear()
            if turn is not None:
                session.current_turn = turn
            session.latest_event_ns = max(session.latest_event_ns, emitted_at)
            if event == "SessionEnd":
                incoming_pid = payload.get("source_pid", payload.get("pid"))
                incoming_created = payload.get(
                    "source_create_time", payload.get("process_create_time")
                )
                pid_changed = (
                    session.source_pid is not None
                    and incoming_pid is not None
                    and str(incoming_pid) != str(session.source_pid)
                )
                try:
                    created_changed = (
                        session.source_create_time is not None
                        and incoming_created is not None
                        and float(incoming_created) != session.source_create_time
                    )
                except (TypeError, ValueError):
                    created_changed = True
                if pid_changed or created_changed:
                    return session.view()
            if (
                event == "SessionStart"
                and payload.get("source") != "compact"
                and payload.get("source_pid", payload.get("pid")) is None
            ):
                session.source_pid = None
                session.source_create_time = None
            self._update_source(session, payload)

            if event == "SessionStart":
                if payload.get("source") == "compact":
                    return session.view()
                self._commit(session, "idle", "Session started or resumed")
            elif event == "UserPromptSubmit":
                session.turn_number += 1
                if turn is None:
                    session.current_turn = session.turn_number
                session.sticky_state = None
                session.sticky_source = None
                session.active_tool_ids.clear()
                session.completed_tool_ids.clear()
                self._commit(session, "thinking", "Working on request")
            elif event == "PreToolUse":
                if _is_adapter_tool(payload.get("tool_name")):
                    return session.view()
                call_id = _tool_id(payload)
                if call_id:
                    if call_id in session.completed_tool_ids:
                        return session.view()
                    session.active_tool_ids.add(call_id)
                self._commit(session, "tool_running", payload.get("tool_name") or "Running tool")
            elif event == "PostToolUse":
                if _is_adapter_tool(payload.get("tool_name")):
                    return session.view()
                call_id = _tool_id(payload)
                if call_id:
                    session.active_tool_ids.discard(call_id)
                    session.completed_tool_ids.add(call_id)
                if session.sticky_source == "hook":
                    session.sticky_state = None
                    session.sticky_source = None
                if session.sticky_state:
                    self._commit(session, session.sticky_state)
                elif session.active_tool_ids:
                    self._commit(session, "tool_running")
                else:
                    self._commit(session, "thinking", "Working on request")
            elif event == "PermissionRequest":
                session.sticky_state = "needs_input"
                session.sticky_source = "hook"
                tool_input = payload.get("tool_input")
                description = (
                    tool_input.get("description")
                    if isinstance(tool_input, Mapping)
                    else None
                )
                self._commit(
                    session,
                    "needs_input",
                    payload.get("detail") or description or "Permission required",
                )
            elif event == "Stop":
                if turn is not None:
                    session.completed_turns.add(turn)
                if session.sticky_state:
                    self._commit(session, session.sticky_state)
                else:
                    self._commit(session, "turn_complete", "Turn complete")
            elif event == "Interrupt":
                if turn is not None:
                    session.completed_turns.add(turn)
                self._commit(session, "idle", "Interrupted")
            elif event == "SessionEnd":
                self._commit(session, "offline", "Session ended")
            else:
                raise ValueError(f"unsupported hook event: {event}")
            return session.view()

    def ingest_report(self, payload: Mapping[str, Any]) -> SessionSnapshot:
        state = str(payload.get("state") or "")
        if state not in STATES:
            raise ValueError(f"unsupported state: {state}")
        with self._lock:
            session = self._get_or_create(payload)
            session.current_turn = payload.get("turn_id", payload.get("turn", session.current_turn))
            if state in {"needs_input", "error"}:
                session.sticky_state = state
                session.sticky_source = "report"
            else:
                session.sticky_state = None
                session.sticky_source = None
            self._commit(session, state, payload.get("detail", ""))
            return session.view()

    def snapshot(self, session_id: str) -> SessionSnapshot | None:
        with self._lock:
            for session in self._sessions.values():
                if session.session_id == session_id or session.id == session_id:
                    return session.view()
            return None

    def update_title(self, session_id: str, title: str) -> None:
        """Update display metadata without changing activity or turn state."""
        with self._lock:
            for session in self._sessions.values():
                if session.session_id != session_id:
                    continue
                prefix = "Codex / "
                suffix = f" / {session_id[-8:]}"
                name = prefix + truncate_utf8(
                    title, MAX_NAME_BYTES - len((prefix + suffix).encode("utf-8"))
                ) + suffix
                if session.name != name:
                    session.name = name
                    session.revision += 1

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

    def snapshots(self) -> tuple[SessionSnapshot, ...]:
        with self._lock:
            return tuple(session.view() for session in self._sessions.values())

    def mark_published(
        self,
        session_id: str,
        revision: int,
        published_at: float | None = None,
    ) -> None:
        """Record a successful publication by native session or protocol ID."""
        with self._lock:
            session = next(
                (item for item in self._sessions.values() if item.session_id == session_id or item.id == session_id),
                None,
            )
            if session is None:
                raise KeyError(session_id)
            session.last_published_at = time.time() if published_at is None else published_at
            session.published_revision = max(session.published_revision, revision)

    def mark_offline_if_source(
        self,
        session_id: str,
        source_pid: int,
        source_create_time: float,
        detail: str,
    ) -> SessionSnapshot | None:
        """Mark offline only if the process binding has not changed since inspection."""
        with self._lock:
            session = next(
                (
                    item
                    for item in self._sessions.values()
                    if item.session_id == session_id or item.id == session_id
                ),
                None,
            )
            if (
                session is None
                or session.state == "offline"
                or session.source_pid != source_pid
                or session.source_create_time != source_create_time
            ):
                return None
            self._commit(session, "offline", detail)
            return session.view()
