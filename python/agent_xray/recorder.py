"""JSONL recording: one file per run, one event per line, flushed per event."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import IO

import orjson

from .schema import Event, RunStartEvent, parse_event


def event_to_json(event: Event) -> bytes:
    return orjson.dumps(event.model_dump(mode="json"))


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:40] or "graph"


def recording_filename(event: RunStartEvent, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    name = _safe_name(event.data.meta.graph_name)
    return f"{stamp}_{name}_{event.run_id.replace('-', '')[:8]}.jsonl"


class Recorder:
    """Writes events to ``{record_dir}/{timestamp}_{graph_name}_{run_id8}.jsonl``.

    Thread-safe; several runs may be recorded at the same time.
    """

    def __init__(self, record_dir: str | Path) -> None:
        self.record_dir = Path(record_dir)
        self._files: dict[str, IO[bytes]] = {}
        self._paths: dict[str, Path] = {}
        self._lock = threading.Lock()

    def path_for(self, run_id: str) -> Path | None:
        return self._paths.get(run_id)

    def write(self, event: Event) -> None:
        with self._lock:
            if event.type == "run_start":
                self.record_dir.mkdir(parents=True, exist_ok=True)
                path = self.record_dir / recording_filename(event)
                self._paths[event.run_id] = path
                self._files[event.run_id] = path.open("wb")
            fh = self._files.get(event.run_id)
            if fh is None:
                return  # run started before recording was enabled
            fh.write(event_to_json(event) + b"\n")
            fh.flush()
            if event.type == "run_end":
                fh.close()
                del self._files[event.run_id]

    def close(self) -> None:
        with self._lock:
            for fh in self._files.values():
                fh.close()
            self._files.clear()


def iter_events(path: str | Path) -> Iterator[Event]:
    """Yield events from a JSONL recording, skipping blank or truncated lines."""
    with Path(path).open("rb") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield parse_event(line)
            except ValueError:
                continue  # a partially written last line while the run is still going


def read_events(path: str | Path) -> list[Event]:
    return list(iter_events(path))


def latest_recording(record_dir: str | Path) -> Path | None:
    files = sorted(Path(record_dir).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
