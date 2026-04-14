from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .reports import ReportPaths


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunState:
    version: int = 1
    workspace: str = ""
    status: str = "idle"
    run_id: str = ""
    session_id: str = ""
    child_pid: int | None = None
    started_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    restart_count: int = 0
    last_exit_code: int | None = None
    last_error: str = ""
    last_command: list[str] = field(default_factory=list)
    last_prompt_kind: str = ""
    reports_dir: str = ""
    skill_file: str = ""
    task_file: str = ""
    ideas_file: str = ""
    iteration_file: str = ""

    @classmethod
    def default(cls, workspace: Path, reports: ReportPaths) -> "RunState":
        return cls(
            workspace=str(workspace),
            reports_dir=str(reports.reports_dir),
            skill_file=str(reports.skill_file),
            task_file=str(reports.task_file),
            ideas_file=str(reports.ideas_file),
            iteration_file=str(reports.iteration_file),
            updated_at=utc_now(),
        )

    def update_report_paths(self, reports: ReportPaths) -> None:
        self.reports_dir = str(reports.reports_dir)
        self.skill_file = str(reports.skill_file)
        self.task_file = str(reports.task_file)
        self.ideas_file = str(reports.ideas_file)
        self.iteration_file = str(reports.iteration_file)

    def mark_launching(
        self,
        *,
        run_id: str,
        prompt_kind: str,
        command: list[str],
        child_pid: int,
        session_id: str = "",
    ) -> None:
        now = utc_now()
        if prompt_kind == "initial":
            self.started_at = now
            self.restart_count = 0
        self.updated_at = now
        self.completed_at = ""
        self.status = "running"
        self.run_id = run_id
        self.last_prompt_kind = prompt_kind
        self.last_command = command
        self.child_pid = child_pid
        self.last_error = ""
        self.last_exit_code = None
        self.session_id = session_id

    def mark_interrupted(self, *, exit_code: int | None, error: str = "") -> None:
        self.status = "interrupted"
        self.last_exit_code = exit_code
        self.last_error = error
        self.child_pid = None
        self.updated_at = utc_now()

    def mark_completed(self, *, exit_code: int) -> None:
        now = utc_now()
        self.status = "completed"
        self.last_exit_code = exit_code
        self.child_pid = None
        self.updated_at = now
        self.completed_at = now
        self.last_error = ""

    def mark_failed(self, *, exit_code: int | None, error: str = "") -> None:
        self.status = "failed"
        self.last_exit_code = exit_code
        self.last_error = error
        self.child_pid = None
        self.updated_at = utc_now()

    def can_resume(self) -> bool:
        return self.status in {"running", "interrupted", "failed"} and bool(
            self.session_id
        )


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self, workspace: Path, reports: ReportPaths) -> RunState:
        if not self.path.exists():
            return RunState.default(workspace, reports)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        state = RunState(**data)
        state.workspace = str(workspace)
        state.update_report_paths(reports)
        if not state.updated_at:
            state.updated_at = utc_now()
        return state

    def save(self, state: RunState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        fd, temp_path = tempfile.mkstemp(
            prefix=f"{self.path.name}.", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))
