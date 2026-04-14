from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .codex import (
    CodexInvocation,
    CodexSessionLocator,
    build_exec_invocation,
    build_resume_invocation,
)
from .reports import build_report_paths
from .state import RunState, StateStore


@dataclass(frozen=True)
class RunnerConfig:
    workspace: Path
    codex_bin: str = "codex"
    model: str = "gpt-5.4"
    reasoning_effort: str = "high"
    sandbox: str = "workspace-write"
    full_auto: bool = True
    bypass_sandbox: bool = False
    skip_git_repo_check: bool = False
    max_restarts: int = 3
    restart_backoff_seconds: float = 3.0
    extra_instructions: str | None = None
    fresh: bool = False


class WorkspaceLock:
    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            stale_pid = _read_pid(self.path)
            if stale_pid and _is_pid_alive(stale_pid):
                raise RuntimeError(
                    f"another auto-research runner is active for this workspace (pid {stale_pid})"
                )
            self.path.unlink(missing_ok=True)

        self._fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.write(self._fd, str(os.getpid()).encode("utf-8"))
        os.fsync(self._fd)

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> "WorkspaceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class AutoResearchRunner:
    def __init__(
        self,
        config: RunnerConfig,
        *,
        codex_home: Path | None = None,
    ) -> None:
        self.config = config
        self.workspace = config.workspace.resolve()
        self.reports = build_report_paths(self.workspace)
        self.state_store = StateStore(self.reports.runtime_dir / "state.json")
        self.session_locator = CodexSessionLocator(codex_home=codex_home)
        self.state = self.state_store.load(self.workspace, self.reports)
        self.lock = WorkspaceLock(self.reports.runtime_dir / "runner.lock")
        self.stop_requested = False
        self.current_process: subprocess.Popen[str] | None = None

    def run(self, *, force_resume: bool = False) -> int:
        self.state.update_report_paths(self.reports)
        self.state_store.save(self.state)

        with self.lock, self._signal_guard():
            session_id = self._pick_resume_session(force_resume=force_resume)
            return self._run_loop(session_id=session_id)

    def print_status(self, *, stream=None) -> None:
        stream = stream or sys.stdout
        state = self.state_store.load(self.workspace, self.reports)
        resumable = "yes" if state.can_resume() else "no"
        print(f"workspace: {state.workspace}", file=stream)
        print(f"reports_dir: {state.reports_dir}", file=stream)
        print(f"status: {state.status}", file=stream)
        print(f"session_id: {state.session_id or '-'}", file=stream)
        print(f"child_pid: {state.child_pid or '-'}", file=stream)
        print(f"restart_count: {state.restart_count}", file=stream)
        print(f"last_exit_code: {state.last_exit_code if state.last_exit_code is not None else '-'}", file=stream)
        print(f"updated_at: {state.updated_at or '-'}", file=stream)
        print(f"resumable: {resumable}", file=stream)

    def _run_loop(self, *, session_id: str | None) -> int:
        attempt = self.state.restart_count if session_id else 0
        active_session_id = session_id or ""

        while True:
            output_file = self.reports.runtime_dir / "last_message.txt"
            if active_session_id:
                invocation = build_resume_invocation(
                    codex_bin=self.config.codex_bin,
                    session_id=active_session_id,
                    workspace=self.workspace,
                    model=self.config.model,
                    reasoning_effort=self.config.reasoning_effort,
                    full_auto=self.config.full_auto,
                    bypass_sandbox=self.config.bypass_sandbox,
                    output_file=output_file,
                    extra_instructions=self.config.extra_instructions,
                    reports=self.reports,
                )
            else:
                invocation = build_exec_invocation(
                    codex_bin=self.config.codex_bin,
                    workspace=self.workspace,
                    model=self.config.model,
                    reasoning_effort=self.config.reasoning_effort,
                    sandbox=self.config.sandbox,
                    full_auto=self.config.full_auto,
                    bypass_sandbox=self.config.bypass_sandbox,
                    skip_git_repo_check=self.config.skip_git_repo_check,
                    output_file=output_file,
                    extra_instructions=self.config.extra_instructions,
                    reports=self.reports,
                )

            started_after = datetime.now(timezone.utc)
            run_id = str(uuid.uuid4())
            process = self._start_process(invocation, run_id=run_id, session_id=active_session_id)
            exit_code = self._wait_for_process(process, started_after=started_after)

            discovered = self._discover_session(
                started_after=started_after,
                preferred_session_id=active_session_id or self.state.session_id,
            )
            if discovered and self.state.session_id != discovered:
                self.state.session_id = discovered
                self.state_store.save(self.state)

            if exit_code == 0:
                self.state.mark_completed(exit_code=exit_code)
                self.state_store.save(self.state)
                return exit_code

            if self.stop_requested:
                self.state.mark_interrupted(
                    exit_code=exit_code,
                    error="runner interrupted by signal",
                )
                self.state_store.save(self.state)
                return exit_code if exit_code != 0 else 130

            if not self.state.session_id:
                self.state.mark_failed(
                    exit_code=exit_code,
                    error="codex exited without a recoverable session id",
                )
                self.state_store.save(self.state)
                return exit_code if exit_code != 0 else 1

            if attempt >= self.config.max_restarts:
                self.state.mark_failed(
                    exit_code=exit_code,
                    error="maximum automatic resume attempts reached",
                )
                self.state_store.save(self.state)
                return exit_code if exit_code != 0 else 1

            attempt += 1
            self.state.restart_count = attempt
            self.state.mark_interrupted(
                exit_code=exit_code,
                error="codex exited unexpectedly; attempting automatic resume",
            )
            self.state_store.save(self.state)
            time.sleep(self.config.restart_backoff_seconds)
            active_session_id = self.state.session_id

    def _start_process(
        self,
        invocation: CodexInvocation,
        *,
        run_id: str,
        session_id: str,
    ) -> subprocess.Popen[str]:
        try:
            process = subprocess.Popen(
                invocation.command,
                cwd=str(self.workspace),
                stdin=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise RuntimeError(
                f"failed to start Codex CLI with command: {' '.join(invocation.command)}"
            ) from exc
        self.current_process = process
        self.state.mark_launching(
            run_id=run_id,
            prompt_kind=invocation.prompt_kind,
            command=invocation.command,
            child_pid=process.pid,
            session_id=session_id,
        )
        self.state_store.save(self.state)
        assert process.stdin is not None
        process.stdin.write(invocation.prompt)
        process.stdin.close()
        return process

    def _wait_for_process(
        self,
        process: subprocess.Popen[str],
        *,
        started_after: datetime,
    ) -> int:
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                self.current_process = None
                return exit_code
            discovered = self._discover_session(
                started_after=started_after,
                preferred_session_id=self.state.session_id,
            )
            if discovered and self.state.session_id != discovered:
                self.state.session_id = discovered
                self.state_store.save(self.state)
            time.sleep(2.0)

    def _discover_session(
        self,
        *,
        started_after: datetime,
        preferred_session_id: str,
    ) -> str:
        candidate = self.session_locator.find_best_candidate(
            workspace=self.workspace,
            started_after=started_after,
            preferred_session_id=preferred_session_id,
        )
        return candidate.session_id if candidate else ""

    def _pick_resume_session(self, *, force_resume: bool) -> str | None:
        if self.config.fresh:
            return None
        if self.state.can_resume():
            return self.state.session_id
        if force_resume:
            started_after = _state_started_at(self.state)
            candidate = self.session_locator.find_best_candidate(
                workspace=self.workspace,
                started_after=started_after,
                preferred_session_id=self.state.session_id,
            )
            if candidate is not None:
                self.state.session_id = candidate.session_id
                self.state_store.save(self.state)
                return candidate.session_id
        return None

    @contextmanager
    def _signal_guard(self):
        previous_handlers = {}

        def handler(signum, frame):
            del frame
            self.stop_requested = True
            if self.current_process is not None and self.current_process.poll() is None:
                try:
                    self.current_process.terminate()
                except OSError:
                    pass

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, handler)
        try:
            yield
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _state_started_at(state: RunState) -> datetime:
    if state.started_at:
        raw = state.started_at
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    return datetime.now(timezone.utc)
