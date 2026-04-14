from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .reports import initialize_report_files, validate_report_readiness
from .runner import AutoResearchRunner, RunnerConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto-research",
        description="Run a resumable Codex-based auto-research loop.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Create the shared auto-research report files for a workspace.",
    )
    _add_workspace_argument(init_parser)

    run_parser = subparsers.add_parser(
        "run",
        help="Start the auto-research runner, or resume an unfinished session.",
    )
    _add_workspace_argument(run_parser)
    _add_runner_arguments(run_parser)

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume the most recent unfinished auto-research session.",
    )
    _add_workspace_argument(resume_parser)
    _add_runner_arguments(resume_parser)

    status_parser = subparsers.add_parser(
        "status",
        help="Print the persisted state for this workspace.",
    )
    _add_workspace_argument(status_parser)

    return parser


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace root. The shared report folder is created under workspace/auto-research-reports.",
    )


def _add_runner_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-bin", default="codex", help="Codex CLI binary name.")
    parser.add_argument("--model", default="gpt-5.4", help="Codex model name.")
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        choices=["low", "medium", "high"],
        help="Value passed through -c model_reasoning_effort=...",
    )
    parser.add_argument(
        "--sandbox",
        default="workspace-write",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="Sandbox mode for fresh codex exec runs.",
    )
    parser.add_argument(
        "--no-full-auto",
        action="store_true",
        help="Do not add --full-auto when launching a fresh session.",
    )
    parser.add_argument(
        "--dangerously-bypass-approvals-and-sandbox",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to run Codex with no sandbox and no approval gate. Defaults to enabled; use --no-dangerously-bypass-approvals-and-sandbox to opt out.",
    )
    parser.add_argument(
        "--skip-git-repo-check",
        action="store_true",
        help="Pass through --skip-git-repo-check for fresh runs.",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=3,
        help="Maximum number of automatic resume attempts after an unexpected exit.",
    )
    parser.add_argument(
        "--restart-backoff-seconds",
        type=float,
        default=3.0,
        help="Delay before each automatic resume attempt.",
    )
    parser.add_argument(
        "--extra-instructions",
        default="",
        help="Extra instructions appended to the initial or resume prompt.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore any unfinished session and start a new one.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()

    if args.command == "init":
        result = initialize_report_files(workspace)
        print(f"report_dir: {result.paths.reports_dir}")
        if result.created_files:
            print("created:")
            for path in result.created_files:
                print(f"  - {path.name}")
        if result.existing_files:
            print("kept_existing:")
            for path in result.existing_files:
                print(f"  - {path.name}")
        return 0

    if args.command == "status":
        runner = AutoResearchRunner(RunnerConfig(workspace=workspace))
        runner.print_status()
        return 0

    readiness = validate_report_readiness(workspace)
    if not readiness.is_ready:
        _print_report_readiness_error(readiness, stream=sys.stderr)
        return 1

    config = RunnerConfig(
        workspace=workspace,
        codex_bin=args.codex_bin,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        sandbox=args.sandbox,
        full_auto=not args.no_full_auto,
        bypass_sandbox=args.dangerously_bypass_approvals_and_sandbox,
        skip_git_repo_check=args.skip_git_repo_check,
        max_restarts=args.max_restarts,
        restart_backoff_seconds=args.restart_backoff_seconds,
        extra_instructions=args.extra_instructions or None,
        fresh=args.fresh,
    )
    runner = AutoResearchRunner(config)
    force_resume = args.command == "resume"
    try:
        return runner.run(force_resume=force_resume)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _print_report_readiness_error(readiness, *, stream) -> None:
    print("auto-research report files are not ready for run/resume.", file=stream)
    print(
        f"expected directory: {readiness.paths.reports_dir}",
        file=stream,
    )
    if readiness.missing_files:
        print("missing files:", file=stream)
        for path in readiness.missing_files:
            print(f"  - {path.name}", file=stream)
    if readiness.empty_files:
        print("empty files:", file=stream)
        for path in readiness.empty_files:
            print(f"  - {path.name}", file=stream)
    if readiness.unfilled_required_files:
        print("files that must be filled before run:", file=stream)
        for path in readiness.unfilled_required_files:
            print(f"  - {path.name}", file=stream)
    print(
        f"run `auto-research init --workspace {readiness.paths.reports_dir.parent}` to scaffold missing files, then fill in the markdown content before running again.",
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
