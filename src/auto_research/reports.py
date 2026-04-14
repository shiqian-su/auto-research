from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SKILL_TEMPLATE = """# Auto Research Skill

This workspace uses a persistent report folder to guide long-running research and coding work.

## Required loop

1. Read `TASK.md`, `SKILL.md`, `IDEAS.md`, and `ITERATION.md` before making the next meaningful change.
2. Keep the implementation aligned with the task goal and the current optimization target in `TASK.md`.
3. Add new candidate directions to `IDEAS.md` when you discover them.
4. After each meaningful code or design iteration, append a concise record to `ITERATION.md`.
5. If the workflow itself should improve, update this `SKILL.md`.

## Working style

- Prefer small, testable iterations over large rewrites.
- Keep the framework simple, explicit, and recoverable.
- Treat the markdown files as shared state: both the user and the agent may edit them.
- When resuming after an interruption, reread all report files before changing code.
"""


TASK_TEMPLATE = """# Task

## Final goal

Describe the final outcome the auto-research loop should achieve.

## Optimization target

Describe the current bottleneck or the next improvement target.

## Constraints

- Keep the solution simple and maintainable.
- Preserve user edits in both code and report files.
- Favor resumable work over one-shot execution.

## Success signals

- The framework can launch a Codex agent from the CLI.
- The agent keeps using and updating the shared report files.
- The runner can recover from interrupted or failed sessions.
"""


IDEAS_TEMPLATE = """# Ideas

Record possible improvements here before they are implemented.

- Add idea:
  - Why it may help
  - Expected cost
  - Risk level
"""


ITERATION_TEMPLATE = """# Iterations

Append one block per meaningful iteration.

## Template

### YYYY-MM-DD HH:MM:SS

- Change:
- Why it matters:
- Validation:
- Next step:
"""


@dataclass(frozen=True)
class ReportPaths:
    reports_dir: Path
    skill_file: Path
    task_file: Path
    ideas_file: Path
    iteration_file: Path
    runtime_dir: Path


@dataclass(frozen=True)
class ReportInitResult:
    paths: ReportPaths
    created_files: tuple[Path, ...]
    existing_files: tuple[Path, ...]


@dataclass(frozen=True)
class ReportReadiness:
    paths: ReportPaths
    missing_files: tuple[Path, ...]
    empty_files: tuple[Path, ...]
    unfilled_required_files: tuple[Path, ...]

    @property
    def is_ready(self) -> bool:
        return not (
            self.missing_files
            or self.empty_files
            or self.unfilled_required_files
        )


def build_report_paths(workspace: Path) -> ReportPaths:
    reports_dir = workspace / "auto-research-reports"
    runtime_dir = reports_dir / ".auto-research"
    return ReportPaths(
        reports_dir=reports_dir,
        skill_file=reports_dir / "SKILL.md",
        task_file=reports_dir / "TASK.md",
        ideas_file=reports_dir / "IDEAS.md",
        iteration_file=reports_dir / "ITERATION.md",
        runtime_dir=runtime_dir,
    )


def initialize_report_files(workspace: Path) -> ReportInitResult:
    paths = build_report_paths(workspace)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)

    created_files: list[Path] = []
    existing_files: list[Path] = []
    for path, template in _required_report_templates(paths):
        if path.exists():
            existing_files.append(path)
            continue
        path.write_text(template, encoding="utf-8")
        created_files.append(path)

    return ReportInitResult(
        paths=paths,
        created_files=tuple(created_files),
        existing_files=tuple(existing_files),
    )


def ensure_report_files(workspace: Path) -> ReportPaths:
    return initialize_report_files(workspace).paths


def validate_report_readiness(workspace: Path) -> ReportReadiness:
    paths = build_report_paths(workspace)
    missing_files: list[Path] = []
    empty_files: list[Path] = []
    unfilled_required_files: list[Path] = []

    for path, template in _required_report_templates(paths):
        if not path.exists():
            missing_files.append(path)
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            empty_files.append(path)
            continue
        if _template_must_be_filled_before_run(path) and content == template.strip():
            unfilled_required_files.append(path)

    return ReportReadiness(
        paths=paths,
        missing_files=tuple(missing_files),
        empty_files=tuple(empty_files),
        unfilled_required_files=tuple(unfilled_required_files),
    )


def _required_report_templates(paths: ReportPaths) -> tuple[tuple[Path, str], ...]:
    return (
        (paths.skill_file, SKILL_TEMPLATE),
        (paths.task_file, TASK_TEMPLATE),
        (paths.ideas_file, IDEAS_TEMPLATE),
        (paths.iteration_file, ITERATION_TEMPLATE),
    )


def _template_must_be_filled_before_run(path: Path) -> bool:
    return path.name == "TASK.md"
