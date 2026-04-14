from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .reports import ReportPaths


@dataclass(frozen=True)
class CodexInvocation:
    command: list[str]
    prompt: str
    prompt_kind: str


@dataclass(frozen=True)
class SessionCandidate:
    session_id: str
    timestamp: datetime
    path: Path


def build_initial_prompt(
    *,
    workspace: Path,
    reports: ReportPaths,
    extra_instructions: str | None,
) -> str:
    prompt = f"""You are the dedicated auto-research agent for this workspace.

Workspace: {workspace}
Report directory: {reports.reports_dir}

Shared files that must be used and maintained:
- {reports.skill_file}
- {reports.task_file}
- {reports.ideas_file}
- {reports.iteration_file}

Operating rules:
1. Read all four report files before making the next meaningful code change.
2. Treat the report files as shared state between the user and the agent.
3. Keep TASK.md aligned with the final goal and the current optimization target.
4. Add new candidate improvements to IDEAS.md.
5. After each meaningful iteration, append a concise entry to ITERATION.md with change, impact, validation, and next step.
6. If the working method itself should improve, update SKILL.md.
7. Prefer small, testable iterations and keep the framework easy to maintain.

Start by reading the report files, summarizing the current state to yourself, and then continue the next best implementation step.
"""
    if extra_instructions:
        prompt = f"{prompt}\nAdditional instructions:\n{extra_instructions.strip()}\n"
    return prompt


def build_resume_prompt(
    *,
    workspace: Path,
    reports: ReportPaths,
    extra_instructions: str | None,
) -> str:
    prompt = f"""Resume the existing auto-research session for workspace {workspace}.

Before changing code:
1. Re-read {reports.skill_file}, {reports.task_file}, {reports.ideas_file}, and {reports.iteration_file}.
2. Reconstruct the latest goal, current optimization target, unfinished work, and highest-risk next step.
3. Continue with the next small implementation step.
4. Update the markdown reports as the shared state changes.
"""
    if extra_instructions:
        prompt = f"{prompt}\nAdditional instructions:\n{extra_instructions.strip()}\n"
    return prompt


def build_exec_invocation(
    *,
    codex_bin: str,
    workspace: Path,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    full_auto: bool,
    bypass_sandbox: bool,
    skip_git_repo_check: bool,
    output_file: Path,
    extra_instructions: str | None,
    reports: ReportPaths,
) -> CodexInvocation:
    command = [
        codex_bin,
        "exec",
        "-C",
        str(workspace),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-o",
        str(output_file),
    ]
    if bypass_sandbox:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend(["-s", sandbox])
        if full_auto:
            command.append("--full-auto")
    if skip_git_repo_check:
        command.append("--skip-git-repo-check")
    command.append("-")
    prompt = build_initial_prompt(
        workspace=workspace,
        reports=reports,
        extra_instructions=extra_instructions,
    )
    return CodexInvocation(command=command, prompt=prompt, prompt_kind="initial")


def build_resume_invocation(
    *,
    codex_bin: str,
    session_id: str,
    workspace: Path,
    model: str,
    reasoning_effort: str,
    full_auto: bool,
    bypass_sandbox: bool,
    output_file: Path,
    extra_instructions: str | None,
    reports: ReportPaths,
) -> CodexInvocation:
    command = [
        codex_bin,
        "exec",
        "resume",
        session_id,
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-o",
        str(output_file),
    ]
    if bypass_sandbox:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif full_auto:
        command.append("--full-auto")
    command.append("-")
    prompt = build_resume_prompt(
        workspace=workspace,
        reports=reports,
        extra_instructions=extra_instructions,
    )
    return CodexInvocation(command=command, prompt=prompt, prompt_kind="resume")


class CodexSessionLocator:
    def __init__(self, codex_home: Path | None = None):
        self.codex_home = codex_home or (Path.home() / ".codex")
        self.sessions_root = self.codex_home / "sessions"

    def find_best_candidate(
        self,
        *,
        workspace: Path,
        started_after: datetime,
        preferred_session_id: str = "",
        lookback_hours: int = 48,
    ) -> SessionCandidate | None:
        if preferred_session_id:
            direct = self.find_by_session_id(preferred_session_id)
            if direct is not None:
                return direct

        threshold = started_after - timedelta(minutes=10)
        candidates: list[SessionCandidate] = []
        if not self.sessions_root.exists():
            return None

        earliest_date = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).date()
        for path in sorted(self.sessions_root.glob("*/*/*/*.jsonl"), reverse=True):
            try:
                file_date = _parse_session_file_date(path)
            except ValueError:
                continue
            if file_date < earliest_date:
                break
            candidate = self._read_candidate(path)
            if candidate is None:
                continue
            if candidate.timestamp < threshold:
                continue
            if self._session_workspace(path) != str(workspace):
                continue
            candidates.append(candidate)

        if not candidates:
            return None
        candidates.sort(key=lambda item: item.timestamp, reverse=True)
        return candidates[0]

    def find_by_session_id(self, session_id: str) -> SessionCandidate | None:
        if not session_id or not self.sessions_root.exists():
            return None
        matches = sorted(
            self.sessions_root.glob(f"*/*/*/*{session_id}.jsonl"),
            reverse=True,
        )
        for path in matches:
            candidate = self._read_candidate(path)
            if candidate is not None:
                return candidate
        return None

    def _read_candidate(self, path: Path) -> SessionCandidate | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                line = handle.readline()
        except OSError:
            return None
        if not line:
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if payload.get("type") != "session_meta":
            return None
        session_id = payload.get("payload", {}).get("id", "")
        timestamp_raw = payload.get("payload", {}).get("timestamp", "")
        if not session_id or not timestamp_raw:
            return None
        return SessionCandidate(
            session_id=session_id,
            timestamp=_parse_datetime(timestamp_raw),
            path=path,
        )

    def _session_workspace(self, path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8") as handle:
                line = handle.readline()
        except OSError:
            return ""
        if not line:
            return ""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return ""
        return str(payload.get("payload", {}).get("cwd", ""))


def _parse_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _parse_session_file_date(path: Path):
    try:
        year = int(path.parts[-4])
        month = int(path.parts[-3])
        day = int(path.parts[-2])
    except (ValueError, IndexError) as exc:
        raise ValueError("invalid session date path") from exc
    return datetime(year, month, day, tzinfo=timezone.utc).date()
