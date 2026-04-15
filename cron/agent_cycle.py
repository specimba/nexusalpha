#!/usr/bin/env python3
"""
cron/agent_cycle.py — Automated CI / Self-Check for Nexus OS Agents

Designed to be run by a system cron job every 15 minutes (configurable).
Implements the Git-Backup Mindset: every successful cycle commits the
current state, providing a granular, recoverable history.

Cycle Pipeline:
  1. Run pytest on all tests — fail fast on any error
  2. (Optional) Canary health check on Bridge server
  3. Git auto-backup with timestamped commit message
  4. Log rotation to prevent unbounded growth
  5. Summary report (stdout + log)

Exit Codes:
  0 — All checks passed, backup created
  1 — Tests failed
  2 — Environment error (missing dependencies, bad config)
  3 — Canary check failed (Bridge health)

Deployment:
  */15 * * * * cd /path/to/nexus-os-hardening && python3 cron/agent_cycle.py
"""

import os
import sys
import subprocess
import datetime
import logging
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).parent.parent
LOG_FILE = PROJECT_ROOT / "cron" / "cycle.log"
REPORT_FILE = PROJECT_ROOT / "cron" / "cycle_report.json"


@dataclass
class CycleResult:
    """Result of a single cycle execution."""
    cycle_number: int
    timestamp: str
    tests_passed: bool
    test_count: int = 0
    test_failures: int = 0
    test_errors: int = 0
    test_duration_s: float = 0.0
    canary_passed: Optional[bool] = None
    canary_url: Optional[str] = None
    git_backup: bool = False
    git_message: Optional[str] = None
    log_rotated: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle_number,
            "timestamp": self.timestamp,
            "tests_passed": self.tests_passed,
            "test_count": self.test_count,
            "test_failures": self.test_failures,
            "test_errors": self.test_errors,
            "test_duration_s": round(self.test_duration_s, 2),
            "canary_passed": self.canary_passed,
            "git_backup": self.git_backup,
            "git_message": self.git_message,
            "log_rotated": self.log_rotated,
            "error": self.error,
        }


class AgentCycleRunner:
    """
    Automated self-check runner for Nexus OS.

    Coordinates test execution, health checks, git backups,
    and log rotation in a single cron-friendly pipeline.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        log_file: Optional[Path] = None,
        report_file: Optional[Path] = None,
        bridge_url: str = "http://localhost:8000/health",
        enable_canary: bool = False,
        max_log_size_mb: float = 10,
        git_backup_enabled: bool = True,
    ):
        self.project_root = project_root or PROJECT_ROOT
        self.log_file = log_file or LOG_FILE
        self.report_file = report_file or REPORT_FILE
        self.bridge_url = bridge_url
        self.enable_canary = enable_canary
        self.max_log_size_bytes = max_log_size_mb * 1024 * 1024
        self.git_backup_enabled = git_backup_enabled
        self._cycle_count = self._load_cycle_count()

        os.makedirs(self.log_file.parent, exist_ok=True)

        logging.basicConfig(
            filename=str(self.log_file),
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger("agent_cycle")

    def _load_cycle_count(self) -> int:
        """Load the last cycle number from the report file."""
        if self.report_file.exists():
            try:
                with open(self.report_file) as f:
                    data = json.load(f)
                return data.get("last_cycle", 0) + 1
            except (json.JSONDecodeError, KeyError):
                return 1
        return 1

    def _save_report(self, result: CycleResult):
        """Save cycle result to the report file."""
        data = {"last_cycle": result.cycle_number, "last_result": result.to_dict()}
        with open(self.report_file, "w") as f:
            json.dump(data, f, indent=2)

    # ── Step 1: Test Suite ──────────────────────────────────────

    def run_tests(self) -> Tuple[bool, int, int, int, float, str]:
        """
        Execute pytest on the full test suite.

        Returns:
            (passed, total, failures, errors, duration_seconds, stderr)
        """
        self.logger.info("Starting test suite...")

        test_dir = self.project_root / "tests"
        if not test_dir.exists():
            self.logger.error("Test directory not found: %s", test_dir)
            return False, 0, 0, 0, 0.0, "Test directory missing"

        start = datetime.datetime.now()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute hard timeout
        )
        duration = (datetime.datetime.now() - start).total_seconds()

        passed = result.returncode == 0
        stderr = result.stderr or ""
        stdout = result.stdout or ""

        # Parse test counts from output
        total = 0
        failures = 0
        errors = 0

        # pytest -q output: "X passed, Y failed, Z errors in W.WWs"
        import re
        summary_match = re.search(
            r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) errors?)?",
            stdout + stderr
        )
        if summary_match:
            total = int(summary_match.group(1))
            failures = int(summary_match.group(2) or 0)
            errors = int(summary_match.group(3) or 0)
            total += failures + errors

        if passed:
            self.logger.info(
                "All tests passed. (%d tests, %.1fs)", total, duration
            )
        else:
            self.logger.error(
                "Tests FAILED. (%d passed, %d failed, %d errors, %.1fs)\n%s",
                total - failures - errors, failures, errors, duration,
                stderr[-2000:] if stderr else stdout[-2000:],
            )

        return passed, total, failures, errors, duration, stderr

    # ── Step 2: Canary Health Check ─────────────────────────────

    def run_canary(self) -> Tuple[bool, str]:
        """
        Check Bridge server health via HTTP.

        Returns:
            (healthy, error_message)
        """
        self.logger.info("Running canary health check: %s", self.bridge_url)

        try:
            from urllib.request import urlopen, Request
            req = Request(self.bridge_url, method="GET")
            with urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    self.logger.info("Canary: Bridge healthy (200 OK)")
                    return True, ""
                else:
                    msg = f"Canary: Bridge returned {resp.status}"
                    self.logger.warning(msg)
                    return False, msg
        except Exception as e:
            msg = f"Canary: Bridge unreachable — {e}"
            self.logger.error(msg)
            return False, msg

    # ── Step 3: Git Auto-Backup ─────────────────────────────────

    def git_backup(self) -> Tuple[bool, str]:
        """
        Commit all current changes with a timestamped message.

        Returns:
            (committed, message)
        """
        if not self.git_backup_enabled:
            return False, "Git backup disabled"

        self.logger.info("Creating git backup...")

        try:
            # Check if we're in a git repo
            git_dir = self.project_root / ".git"
            if not git_dir.exists():
                # Initialize git repo if needed
                subprocess.run(
                    ["git", "init"],
                    cwd=str(self.project_root),
                    capture_output=True,
                    check=True,
                )
                self.logger.info("Initialized new git repository.")

            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(self.project_root),
                check=True,
                capture_output=True,
            )

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = f"auto-backup: cycle {self._cycle_count} checkpoint {timestamp}"

            result = subprocess.run(
                ["git", "commit", "-m", msg, "--allow-empty"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self.logger.info("Git commit created: %s", msg)
                return True, msg
            else:
                # "nothing to commit" is fine — not an error
                if "nothing to commit" in result.stdout:
                    self.logger.info("Git: no changes to commit.")
                    return False, "No changes to commit"
                self.logger.warning("Git commit issue: %s", result.stderr)
                return False, result.stderr.strip()

        except subprocess.CalledProcessError as e:
            msg = f"Git error: {e}"
            self.logger.warning(msg)
            return False, msg
        except FileNotFoundError:
            msg = "Git not installed — skipping backup"
            self.logger.warning(msg)
            return False, msg

    # ── Step 4: Log Rotation ────────────────────────────────────

    def rotate_logs(self) -> bool:
        """
        Rename log file if it exceeds the size limit.

        Returns:
            True if rotation occurred
        """
        if not self.log_file.exists():
            return False

        size = self.log_file.stat().st_size
        if size <= self.max_log_size_bytes:
            return False

        archive_name = (
            self.log_file.stem
            + f".{int(datetime.datetime.now().timestamp())}"
            + self.log_file.suffix
        )
        archive_path = self.log_file.parent / archive_name
        self.log_file.rename(archive_path)

        self.logger.info("Log rotated to %s (was %.1f MB)", archive_path, size / 1024 / 1024)

        # Keep only last 5 log archives
        archives = sorted(
            self.log_file.parent.glob(f"{self.log_file.stem}.*{self.log_file.suffix}"),
            key=lambda p: p.stat().st_mtime,
        )
        for old_archive in archives[:-5]:
            old_archive.unlink()
            self.logger.info("Removed old archive: %s", old_archive)

        return True

    # ── Main Pipeline ───────────────────────────────────────────

    def run_cycle(self) -> CycleResult:
        """
        Execute the full self-check pipeline.

        Returns:
            CycleResult with all step outcomes.
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = CycleResult(
            cycle_number=self._cycle_count,
            timestamp=timestamp,
            tests_passed=False,
        )

        self.logger.info("=" * 60)
        self.logger.info("=== Agent Cycle #%d Started ===", self._cycle_count)
        self.logger.info("=" * 60)

        # Step 1: Tests
        passed, total, failures, errors, duration, stderr = self.run_tests()
        result.tests_passed = passed
        result.test_count = total
        result.test_failures = failures
        result.test_errors = errors
        result.test_duration_s = duration

        if not passed:
            result.error = f"Tests failed: {failures} failures, {errors} errors"
            self._save_report(result)
            self.logger.info("=== Cycle #%d FAILED (tests) ===", self._cycle_count)
            return result

        # Step 2: Canary (optional)
        if self.enable_canary:
            canary_ok, canary_msg = self.run_canary()
            result.canary_passed = canary_ok
            result.canary_url = self.bridge_url
            if not canary_ok:
                result.error = f"Canary failed: {canary_msg}"
                self._save_report(result)
                self.logger.info("=== Cycle #%d FAILED (canary) ===", self._cycle_count)
                return result

        # Step 3: Git backup
        backed, git_msg = self.git_backup()
        result.git_backup = backed
        result.git_message = git_msg

        # Step 4: Log rotation
        result.log_rotated = self.rotate_logs()

        self._save_report(result)
        self.logger.info("=== Cycle #%d Completed Successfully ===", self._cycle_count)

        # Console summary
        print(f"\n{'=' * 50}")
        print(f"  Nexus OS — Cycle #{result.cycle_number} Report")
        print(f"{'=' * 50}")
        print(f"  Timestamp:     {result.timestamp}")
        print(f"  Tests:         {result.test_count} passed ({result.test_duration_s:.1f}s)")
        if result.canary_passed is not None:
            status = "HEALTHY" if result.canary_passed else "FAILED"
            print(f"  Bridge Canary: {status}")
        backup_status = "COMMITTED" if result.git_backup else "skipped"
        print(f"  Git Backup:    {backup_status}")
        if result.git_message:
            print(f"    {result.git_message}")
        print(f"{'=' * 50}\n")

        return result


def main():
    """CLI entry point for cron execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Nexus OS Agent Cycle Runner")
    parser.add_argument("--root", type=str, default=None, help="Project root directory")
    parser.add_argument("--canary", action="store_true", help="Enable Bridge health check")
    parser.add_argument("--bridge-url", type=str, default="http://localhost:8000/health")
    parser.add_argument("--no-git", action="store_true", help="Disable git auto-backup")
    parser.add_argument("--max-log-mb", type=float, default=10.0)
    args = parser.parse_args()

    runner = AgentCycleRunner(
        project_root=Path(args.root) if args.root else None,
        enable_canary=args.canary,
        bridge_url=args.bridge_url,
        git_backup_enabled=not args.no_git,
        max_log_size_mb=args.max_log_mb,
    )

    result = runner.run_cycle()

    sys.exit(0 if result.tests_passed else 1)


if __name__ == "__main__":
    main()
