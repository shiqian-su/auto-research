from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from auto_research.cli import main
from auto_research.codex import build_exec_invocation
from auto_research.reports import ensure_report_files, validate_report_readiness
from auto_research.state import RunState, StateStore


class ReportBootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_required_report_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            reports = ensure_report_files(workspace)
            self.assertTrue(reports.skill_file.exists())
            self.assertTrue(reports.task_file.exists())
            self.assertTrue(reports.ideas_file.exists())
            self.assertTrue(reports.iteration_file.exists())

    def test_exec_invocation_contains_workspace_model_and_reasoning_effort(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            reports = ensure_report_files(workspace)
            invocation = build_exec_invocation(
                codex_bin="codex",
                workspace=workspace,
                model="gpt-5.4",
                reasoning_effort="high",
                sandbox="workspace-write",
                full_auto=True,
                bypass_sandbox=False,
                skip_git_repo_check=True,
                output_file=reports.runtime_dir / "last_message.txt",
                extra_instructions="keep iterating",
                reports=reports,
            )
            command = invocation.command
            self.assertIn("-C", command)
            self.assertIn(str(workspace), command)
            self.assertIn("-m", command)
            self.assertIn("gpt-5.4", command)
            self.assertIn('model_reasoning_effort="high"', command)
            self.assertIn("--full-auto", command)
            self.assertIn("--skip-git-repo-check", command)

    def test_state_roundtrip_preserves_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            reports = ensure_report_files(workspace)
            store = StateStore(reports.runtime_dir / "state.json")
            state = RunState.default(workspace, reports)
            state.session_id = "session-123"
            state.status = "interrupted"
            state.started_at = datetime.now(timezone.utc).isoformat()
            store.save(state)

            restored = store.load(workspace, reports)
            self.assertEqual(restored.session_id, "session-123")
            self.assertEqual(restored.status, "interrupted")

    def test_readiness_requires_task_but_allows_other_templates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            ensure_report_files(workspace)

            readiness = validate_report_readiness(workspace)

            self.assertFalse(readiness.is_ready)
            self.assertEqual(
                {path.name for path in readiness.unfilled_required_files},
                {"TASK.md"},
            )

    def test_run_refuses_when_reports_are_missing_or_unfilled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            stderr = StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["run", "--workspace", str(workspace)])

            self.assertEqual(exit_code, 1)
            message = stderr.getvalue()
            self.assertIn("not ready for run/resume", message)
            self.assertIn("auto-research init", message)


if __name__ == "__main__":
    unittest.main()
