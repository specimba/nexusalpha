"""
tests/cron/test_agent_cycle.py — Agent Cycle Runner Tests

Tests the automated CI/self-check pipeline:
  - Test suite execution and result parsing
  - Git auto-backup behavior
  - Log rotation logic
  - Canary health check (mocked)
  - Full pipeline orchestration
"""

import pytest
import os
import sys
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from cron.agent_cycle import AgentCycleRunner, CycleResult


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory with test structure."""
    project = tmp_path / "nexus-os-hardening"
    project.mkdir()
    (project / "tests").mkdir()

    # Create a dummy conftest.py and simple test
    (project / "tests" / "__init__.py").write_text("")
    (project / "tests" / "test_dummy.py").write_text("""
import pytest

def test_dummy_passes():
    assert True

def test_dummy_math():
    assert 2 + 2 == 4
""")

    return project


@pytest.fixture
def runner(temp_project):
    """Create an AgentCycleRunner with temp project."""
    log_file = temp_project / "cron" / "cycle.log"
    report_file = temp_project / "cron" / "cycle_report.json"
    return AgentCycleRunner(
        project_root=temp_project,
        log_file=log_file,
        report_file=report_file,
        enable_canary=False,
        git_backup_enabled=False,
    )


class TestCycleResult:
    def test_to_dict(self):
        result = CycleResult(
            cycle_number=1,
            timestamp="2025-01-01 00:00:00",
            tests_passed=True,
            test_count=10,
            test_duration_s=2.5,
        )
        d = result.to_dict()
        assert d["cycle"] == 1
        assert d["tests_passed"] is True
        assert d["test_count"] == 10
        assert d["test_duration_s"] == 2.5
        assert d["error"] is None


class TestRunTests:
    def test_run_passing_tests(self, runner, temp_project):
        """Should detect passing tests."""
        passed, total, failures, errors, duration, stderr = runner.run_tests()

        assert passed is True
        assert total >= 2  # At least our dummy tests
        assert failures == 0
        assert errors == 0
        assert duration > 0

    def test_run_missing_test_dir(self, tmp_path):
        """Should handle missing test directory gracefully."""
        runner = AgentCycleRunner(
            project_root=tmp_path,
            git_backup_enabled=False,
        )
        passed, total, failures, errors, duration, stderr = runner.run_tests()

        assert passed is False
        assert total == 0

    def test_run_failing_tests(self, temp_project):
        """Should detect test failures."""
        (temp_project / "tests" / "test_fail.py").write_text("""
import pytest

def test_this_fails():
    assert 1 == 2
""")
        runner = AgentCycleRunner(
            project_root=temp_project,
            git_backup_enabled=False,
        )
        passed, total, failures, errors, duration, stderr = runner.run_tests()

        assert passed is False


class TestGitBackup:
    def test_git_init_and_commit(self, runner, temp_project):
        """Should initialize git repo and create commit."""
        runner.git_backup_enabled = True

        backed, msg = runner.git_backup()

        assert backed is True
        assert "cycle" in msg.lower() or "checkpoint" in msg.lower()

        # Verify git commit exists
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(temp_project),
            capture_output=True,
            text=True,
        )
        assert "auto-backup" in result.stdout

    def test_git_no_changes(self, runner, temp_project):
        """Second commit with no changes still commits (allow-empty flag)."""
        runner.git_backup_enabled = True

        # First commit
        runner.git_backup()
        # Second commit (no changes, but --allow-empty means it still commits)
        backed2, msg2 = runner.git_backup()
        assert backed2 is True
        assert "cycle" in msg2.lower()

    def test_git_disabled(self, runner):
        """Should skip when git backup is disabled."""
        backed, msg = runner.git_backup()
        assert backed is False
        assert "disabled" in msg.lower()


class TestLogRotation:
    def test_rotate_oversized_log(self, runner, temp_project):
        """Should rotate log file exceeding size limit."""
        runner.max_log_size_bytes = 100  # 100 bytes = tiny threshold
        runner.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Create a log file larger than threshold
        runner.log_file.write_text("x" * 200)

        rotated = runner.rotate_logs()

        assert rotated is True
        assert not runner.log_file.exists()
        # Archive should exist
        archives = list(runner.log_file.parent.glob("cycle.*.log"))
        assert len(archives) >= 1

    def test_no_rotation_for_small_log(self, runner, temp_project):
        """Should not rotate log file under size limit."""
        runner.max_log_size_bytes = 1024 * 1024  # 1 MB
        runner.log_file.parent.mkdir(parents=True, exist_ok=True)
        runner.log_file.write_text("small log")

        rotated = runner.rotate_logs()

        assert rotated is False
        assert runner.log_file.exists()


class TestCanaryCheck:
    def test_canary_disabled(self, runner):
        """Canary should not run when disabled."""
        assert runner.enable_canary is False
        result = runner.run_cycle()
        assert result.canary_passed is None

    def test_canary_healthy(self, temp_project):
        """Should report healthy when server responds 200."""
        runner = AgentCycleRunner(
            project_root=temp_project,
            enable_canary=True,
            git_backup_enabled=False,
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            healthy, msg = runner.run_canary()
            assert healthy is True

    def test_canary_unreachable(self, temp_project):
        """Should report unhealthy when server unreachable."""
        runner = AgentCycleRunner(
            project_root=temp_project,
            enable_canary=True,
            git_backup_enabled=False,
        )
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            healthy, msg = runner.run_canary()
            assert healthy is False
            assert "unreachable" in msg.lower() or "refused" in msg.lower()


class TestFullPipeline:
    def test_successful_cycle(self, runner):
        """Full pipeline should pass with clean tests."""
        result = runner.run_cycle()

        assert result.tests_passed is True
        assert result.test_count >= 2
        assert result.error is None

    def test_failed_cycle_reports_error(self, temp_project):
        """Pipeline should report error when tests fail."""
        (temp_project / "tests" / "test_break.py").write_text("""
def test_break():
    raise ValueError("intentional break")
""")
        runner = AgentCycleRunner(
            project_root=temp_project,
            git_backup_enabled=False,
        )
        result = runner.run_cycle()

        assert result.tests_passed is False
        assert result.error is not None
        assert "failed" in result.error.lower()

    def test_report_file_created(self, runner):
        """Cycle should create a JSON report file."""
        runner.run_cycle()

        assert runner.report_file.exists()
        with open(runner.report_file) as f:
            data = json.load(f)
        assert "last_cycle" in data
        assert "last_result" in data

    def test_cycle_count_increments(self, runner):
        """Cycle number should increment across runs."""
        r1 = runner.run_cycle()
        # Manually reload to simulate a fresh runner reading the report
        runner._cycle_count = runner._load_cycle_count()
        r2 = runner.run_cycle()

        assert r2.cycle_number > r1.cycle_number

    def test_canary_failure_stops_pipeline(self, temp_project):
        """Canary failure should stop before git backup."""
        runner = AgentCycleRunner(
            project_root=temp_project,
            enable_canary=True,
            git_backup_enabled=True,
        )
        with patch.object(runner, "run_canary", return_value=(False, "Bridge down")):
            result = runner.run_cycle()

        assert result.canary_passed is False
        assert result.error is not None
        assert result.git_backup is False  # Should not reach git step


class TestCLIMain:
    def test_main_exits_zero_on_success(self, runner, temp_project, capsys):
        """CLI should exit 0 when tests pass."""
        with patch("sys.argv", ["agent_cycle.py", "--root", str(temp_project), "--no-git"]):
            with pytest.raises(SystemExit) as exc_info:
                from cron.agent_cycle import main
                main()
            assert exc_info.value.code == 0

    def test_main_exits_one_on_failure(self, temp_project, capsys):
        """CLI should exit 1 when tests fail."""
        (temp_project / "tests" / "test_fail.py").write_text("""
def test_fail(): assert False
""")
        with patch("sys.argv", ["agent_cycle.py", "--root", str(temp_project), "--no-git"]):
            with pytest.raises(SystemExit) as exc_info:
                from cron.agent_cycle import main
                main()
            assert exc_info.value.code == 1
