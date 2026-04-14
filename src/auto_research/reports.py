from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SKILL_TEMPLATE = """# Auto Research Skill

You are a professional auto-researcher.
You are working on a project that uses a persistent report folder (`./auto-research-reports/`) to guide long-running research and coding work.

## Required research loop

1. If you are not familiar with current coding project, start by DEEPLY INVESTIGATING the codebase and experiment logs.
2. Read `TASK.md`, `SKILL.md`, `IDEAS.md`, `ITERATION.md` + other files under `./auto-research-reports/`  + git history + results log before making the next meaningful change.
3. Make ONE focused change and align with the task goal and the current optimization target in `TASK.md`.
4. Add new candidate directions to `IDEAS.md` when you discover them.
5. Git commit (before verification)
6. Run mechanical verification (tests, benchmarks, scores).
7. If improved → keep. If worse → git revert. If crashed → fix or skip.
8. Log the result to`ITERATION.md`. And you may write addition experiment logs in `./auto-research-reports/` to help you understand the current coding project and the task.
9. Repeat. Never stop until you interrupt (or N iterations complete).

## The Setup Phase

Before looping, you should perform a one-time setup:

1. Read context — reads all in-scope files
2. Define goal — extracts or asks for a mechanical metric
3. Define scope — which files can be modified vs read-only
4. Establish baseline — runs verification on current state (iteration #0)
5. Confirm and go — shows setup, then begins the loop

## Critical Rules

1. **Loop until done** — unbounded: forever. Bounded: N times then summarize
2. **Read before write** — understand full context before modifying
3. **One change per iteration** — atomic changes. If it breaks, you know why
4. **Mechanical verification only** — no subjective "looks good." Use metrics. For each experiment or meaningful step, record a series of quantitative results (e.g., metrics, counts, statistical indicators, comparison tables, etc.) to ensure results are clear, and reproducible.
5. **Automatic rollback** — failed changes revert instantly
6. **Simplicity wins** — equal results + less code = KEEP
7. **Git is memory** — experiments committed with experiment: prefix, git revert preserves failed experiments in history, agent MUST read git log + git diff before each iteration
8. **When stuck, think harder** — re-read, combine near-misses, try radical changes
9. **Most effective first** - Prioritize optimization directions that offer high cost-effectiveness, significant performance improvement, low risk, and considerable benefits.
"""


TASK_TEMPLATE = """This TASK.md is only editable by the user.
# Task

## Overview

Describe the overall context and purpose of the coding project.

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

## High priority

-

## Medium priority

-

## Low priority

-
"""


ITERATION_TEMPLATE = """# Iterations

Append one block per meaningful iteration.

## Template

### v1.0 (YYYY-MM-DD HH:MM:SS)

- Change:
- Why it matters:
- Validation results:
- Next possible steps:
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
