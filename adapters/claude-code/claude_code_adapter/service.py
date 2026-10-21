from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, status

from claude_code_adapter.client import BridgeClient, BridgeUnavailable
from claude_code_adapter.config import Settings
from claude_code_adapter.state import SessionReducer, Snapshot


def _process_matches(pid: int, created: float) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE and abs(process.create_time() - created) < 0.01
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except (psutil.AccessDenied, OSError):
        return True


class Runtime:
    def __init__(self, settings: Settings, reducer: SessionReducer, bridge: BridgeClient,
                 process_matches: Callable[[int, float], bool] = _process_matches) -> None:
        self.settings, self.reducer, self.bridge = settings, reducer, bridge
        self.process_matches = process_matches
        self.changed = asyncio.Event()
        self.stopping = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []

    def notify(self) -> None:
        self.changed.set()

    async def start(self) -> None:
        self.tasks = [asyncio.create_task(self._publish_loop()),
                      asyncio.create_task(self._process_loop())]

    async def stop(self) -> None:
        self.stopping.set()
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.bridge.close()

    @staticmethod
    def _due(snapshot: Snapshot, now: float, heartbeat: float) -> bool:
        if snapshot.published_revision < snapshot.revision:
            return True
        # Never fabricate liveness for an unbound session; SessionEnd clears binding.
        return (snapshot.state != "offline" and snapshot.source_pid is not None and
                snapshot.source_create_time is not None and snapshot.last_published_at is not None and
                now - snapshot.last_published_at >= heartbeat)

    async def publish_once(self) -> bool:
        now, success = time.time(), True
        for snapshot in self.reducer.snapshots():
            if not self._due(snapshot, now, self.settings.heartbeat_seconds):
                continue
            try:
                await self.bridge.publish(snapshot.as_status())
            except BridgeUnavailable:
                success = False
                continue
            self.reducer.mark_published(snapshot.session_id, snapshot.revision, now)
        return success

    async def check_processes_once(self) -> None:
        for snapshot in self.reducer.snapshots():
            if snapshot.state == "offline" or snapshot.source_pid is None or snapshot.source_create_time is None:
                continue
            if not self.process_matches(snapshot.source_pid, snapshot.source_create_time):
                if self.reducer.mark_offline_if_source(snapshot.session_id, snapshot.source_pid,
                                                       snapshot.source_create_time) is not None:
                    self.notify()

    async def _publish_loop(self) -> None:
        while not self.stopping.is_set():
            self.changed.clear()
            await self.publish_once()
            try:
                await asyncio.wait_for(self.changed.wait(), self.settings.retry_seconds)
            except TimeoutError:
                pass

    async def _process_loop(self) -> None:
        while not self.stopping.is_set():
            await self.check_processes_once()
            try:
                await asyncio.wait_for(self.stopping.wait(), self.settings.process_check_seconds)
            except TimeoutError:
                pass


def create_app(settings: Settings | None = None, reducer: SessionReducer | None = None,
               bridge: BridgeClient | None = None,
               process_matches: Callable[[int, float], bool] = _process_matches) -> FastAPI:
    resolved = settings or Settings.from_env()
    sessions = reducer or SessionReducer(socket.gethostname())
    client = bridge or BridgeClient(resolved.bridge_url, resolved.bridge_timeout_seconds)
    runtime = Runtime(resolved, sessions, client, process_matches)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Claude Code Agent Monitor Adapter", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "sessions": len(sessions.snapshots())}

    @app.post("/v1/events/claude-code", status_code=status.HTTP_202_ACCEPTED)
    def claude_event(body: dict[str, Any]) -> dict[str, Any]:
        event = body.get("event")
        if not isinstance(event, dict):
            raise HTTPException(status_code=422, detail="event must be an object")
        for key in ("source_pid", "source_create_time"):
            if key in body:
                event[key] = body[key]
        try:
            snapshot = sessions.ingest_hook(event)
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


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
