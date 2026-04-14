from __future__ import annotations

import json
import shlex
import threading
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_logs_dir(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[2]
    return root / "logs"


def build_log_file_path(
    workspace: Path,
    *,
    project_root: Path | None = None,
    started_at: datetime | None = None,
) -> Path:
    logs_dir = build_logs_dir(project_root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (started_at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    workspace_slug = _slugify_workspace(workspace)
    return logs_dir / f"{timestamp}-{workspace_slug}.log"


def shell_join(parts: list[str]) -> str:
    return shlex.join(parts)


class TaskLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def event(self, event: str, **fields) -> None:
        payload = {"ts": utc_now(), "event": event}
        payload.update({key: value for key, value in fields.items() if value is not None})
        self._write_json(payload)

    def output_line(self, line: str) -> None:
        self._write_json(
            {
                "ts": utc_now(),
                "event": "codex_output",
                "text": line.rstrip("\n"),
            }
        )

    def close(self) -> None:
        with self._lock:
            if self._handle.closed:
                return
            self._handle.close()

    def _write_json(self, payload: dict) -> None:
        with self._lock:
            if self._handle.closed:
                return
            self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._handle.flush()


def _slugify_workspace(workspace: Path) -> str:
    raw = workspace.resolve().name or "workspace"
    slug = "".join(ch if ch.isalnum() else "-" for ch in raw.lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "workspace"
