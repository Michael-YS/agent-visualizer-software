"""Read display names from Codex's local session index, never transcripts."""

from __future__ import annotations

import json
import os
from pathlib import Path


class SessionTitles:
    def __init__(self, path: Path | None = None) -> None:
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        self.path = path if path is not None else home / "session_index.jsonl"
        self._signature: tuple[int, int] | None = None
        self._titles: dict[str, str] = {}

    def read(self) -> dict[str, str]:
        """Use the latest valid entry per ID; keep the cache on read failures."""
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature == self._signature:
                return self._titles.copy()
            titles: dict[str, str] = {}
            with self.path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        # A concurrent writer can leave the last line incomplete.
                        continue
                    if not isinstance(entry, dict):
                        continue
                    session_id, title = entry.get("id"), entry.get("thread_name")
                    if isinstance(session_id, str) and isinstance(title, str):
                        title = " ".join(title.split())
                        if title:
                            titles[session_id] = title.encode("utf-8", errors="replace").decode("utf-8")
        except OSError:
            return self._titles.copy()
        self._titles = titles
        self._signature = signature
        return titles.copy()
