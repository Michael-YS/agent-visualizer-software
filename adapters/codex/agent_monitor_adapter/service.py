from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, status

from agent_monitor_adapter.client import BridgeClient, BridgeUnavailable
from agent_monitor_adapter.config import AdapterSettings
from agent_monitor_adapter.state import SessionReducer, SessionSnapshot


def _process_matches(pid: int, created_at: float) -> bool:
    try:
        process = psutil.Process(pid)
        return (
            process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
            and abs(process.create_time() - created_at) < 0.01
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except (psutil.AccessDenied, OSError):
        # Lack of permission is not proof that the monitored process exited.
        return True


class AdapterRuntime:
    def __init__(
        self,
        settings: AdapterSettings,
        reducer: SessionReducer,
        bridge: BridgeClient,
        process_matches: Callable[[int, float], bool] = _process_matches,
    ) -> None:
        self.settings = settings
        self.reducer = reducer
        self.bridge = bridge
        self.process_matches = process_matches
        self._changed = asyncio.Event()
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def notify(self) -> None:
        self._changed.set()

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._publish_loop(), name="agent-monitor-publisher"),
            asyncio.create_task(self._process_loop(), name="agent-monitor-process-check"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        self._changed.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.bridge.close()

    def _due(self, snapshot: SessionSnapshot, now: float) -> bool:
        if snapshot.published_revision < snapshot.revision:
            return True
        return (
            snapshot.state != "offline"
            and snapshot.source_pid is not None
            and snapshot.source_create_time is not None
            and snapshot.last_published_at is not None
            and now - snapshot.last_published_at >= self.settings.heartbeat_seconds
        )

    async def publish_once(self) -> bool:
        """Publish each dirty or heartbeat-due session; return whether all succeeded."""
        now = time.time()
        success = True
        for snapshot in self.reducer.snapshots():
            if not self._due(snapshot, now):
                continue
            try:
                await self.bridge.publish(snapshot.as_status())
            except BridgeUnavailable:
                success = False
                continue
            self.reducer.mark_published(snapshot.id, snapshot.revision, now)
        return success

    async def check_processes_once(self) -> None:
        for snapshot in self.reducer.snapshots():
            if snapshot.state == "offline":
                continue
            if snapshot.source_pid is None or snapshot.source_create_time is None:
                continue
            if self.process_matches(snapshot.source_pid, snapshot.source_create_time):
                continue
            changed = self.reducer.mark_offline_if_source(
                snapshot.session_id,
                snapshot.source_pid,
                snapshot.source_create_time,
                "Codex process exited",
            )
            if changed is not None:
                self.notify()

    async def _publish_loop(self) -> None:
        while not self._stopping.is_set():
            self._changed.clear()
            await self.publish_once()
            try:
                await asyncio.wait_for(
                    self._changed.wait(), timeout=self.settings.retry_seconds
                )
            except TimeoutError:
                pass

    async def _process_loop(self) -> None:
        while not self._stopping.is_set():
            await self.check_processes_once()
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self.settings.process_check_seconds,
                )
            except TimeoutError:
                pass


def _merged_hook(body: Mapping[str, Any]) -> dict[str, Any]:
    event = body.get("event")
    if not isinstance(event, Mapping):
        raise ValueError("event must be an object")
    merged = dict(event)
    for key in ("emitted_at_ns", "source_pid", "source_started_at"):
        if body.get(key) is not None:
            merged[key] = body[key]
    if "source_started_at" in merged:
        merged["source_create_time"] = merged.pop("source_started_at")
    return merged


def create_app(
    settings: AdapterSettings | None = None,
    reducer: SessionReducer | None = None,
    bridge: BridgeClient | None = None,
    process_matches: Callable[[int, float], bool] = _process_matches,
) -> FastAPI:
    resolved = settings or AdapterSettings.from_env()
    sessions = reducer or SessionReducer(socket.gethostname())
    client = bridge or BridgeClient(
        resolved.bridge_url, resolved.bridge_timeout_seconds
    )
    runtime = AdapterRuntime(resolved, sessions, client, process_matches)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Agent Monitor Adapter", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "sessions": len(sessions.snapshots())}

    @app.post("/v1/events/codex", status_code=status.HTTP_202_ACCEPTED)
    def codex_event(body: dict[str, Any]) -> dict[str, Any]:
        try:
            snapshot = sessions.ingest_hook(_merged_hook(body))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        runtime.notify()
        return {"accepted": True, "id": snapshot.id, "state": snapshot.state}

    @app.post("/v1/reports", status_code=status.HTTP_202_ACCEPTED)
    def report(body: dict[str, Any]) -> dict[str, Any]:
        try:
            snapshot = sessions.ingest_report(body)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        runtime.notify()
        return {"accepted": True, "id": snapshot.id, "state": snapshot.state}

    return app


app = create_app()


def main() -> None:
    settings = AdapterSettings.from_env()
    uvicorn.run(
        create_app(settings), host=settings.listen_host, port=settings.listen_port
    )


if __name__ == "__main__":
    main()
