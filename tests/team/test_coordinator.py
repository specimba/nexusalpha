"""
tests/team/test_coordinator.py — Team Coordinator Tests

Comprehensive tests for the Agentic Team Coordinator covering:
  - Initialisation (with and without optional subsystems)
  - Full dispatch pipeline
  - Skill-driven dispatch
  - Status checking across worker queues
  - Result collection
  - Team status reporting
  - Outcome recording (Hermes + mem0)
  - Foreman patrol (stall detection, load balancing)
  - Worker cycle monitoring
  - Cron generation
  - Graceful degradation when mem0 or skill_adapter are unavailable
  - Worker selection logic (explicit, domain-based, least-loaded)
  - Task file parsing and creation
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

import pytest

# Ensure project source is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.engine.hermes import (
    HermesRouter, ModelProfile, TaskDomain, TaskComplexity, RoutingDecision,
)
from nexus_os.team.coordinator import (
    TeamCoordinator,
    WorkerProfile,
    DOMAIN_WORKER_MAP,
    STALL_THRESHOLD,
    WORKER_DEFINITIONS,
)


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """Create an in-memory DatabaseManager for testing."""
    config = DBConfig(db_path=":memory:", passphrase="test", encrypted=False)
    db_mgr = DatabaseManager(config)
    db_mgr.setup_schema()
    yield db_mgr


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project root with the expected directory structure."""
    project = tmp_path / "nexus-os"
    project.mkdir()
    (project / "src").mkdir()
    return project


@pytest.fixture
def openclaw_base(tmp_path):
    """Create a temporary OpenClaw agents directory with worker structures."""
    base = tmp_path / "openclaw-agents"
    base.mkdir()
    for wdef in WORKER_DEFINITIONS:
        worker_dir = base / wdef["agent_dir"]
        for sub in ["tasks/pending", "tasks/done", "tasks/failed", "workspaces"]:
            (worker_dir / sub).mkdir(parents=True)
    return base


@pytest.fixture
def coordinator(db, tmp_project, openclaw_base):
    """Create a TeamCoordinator with test fixtures."""
    return TeamCoordinator(
        project_root=str(tmp_project),
        db=db,
        openclaw_base=str(openclaw_base),
    )


@pytest.fixture
def coordinator_no_db(tmp_project, openclaw_base):
    """Create a TeamCoordinator without a pre-built DB (uses in-memory)."""
    return TeamCoordinator(
        project_root=str(tmp_project),
        openclaw_base=str(openclaw_base),
    )


# ── Mock Fixtures for Optional Subsystems ─────────────────────────────

@pytest.fixture
def mock_memory():
    """Mock the mem0 memory adapter."""
    mock = MagicMock()
    mock.search.return_value = [
        {"content": "Previously fixed similar encryption issue in db/manager.py"},
        {"content": "Worker-1 handles security tasks with 95% success rate"},
    ]
    mock.add.return_value = None
    return mock


@pytest.fixture
def mock_skill_registry():
    """Mock the skill registry."""
    mock = MagicMock()
    mock.find_skill.return_value = "skill-security-audit"
    mock.search.return_value = ["skill-security-audit"]
    return mock


# ── Test Classes ───────────────────────────────────────────────────────

class TestCoordinatorInit:
    """Tests for coordinator initialisation."""

    def test_init_creates_workers(self, coordinator):
        """Should create worker profiles for each defined worker."""
        assert len(coordinator.workers) == 2
        assert "glm5-worker-1" in coordinator.workers
        assert "glm5-worker-2" in coordinator.workers

    def test_init_creates_worker_directories(self, coordinator, openclaw_base):
        """Should create pending/done/failed directories for each worker."""
        for wid, worker in coordinator.workers.items():
            assert worker.pending_queue.exists()
            assert worker.done_queue.exists()
            assert worker.failed_queue.exists()

    def test_init_with_prebuilt_db(self, db, tmp_project, openclaw_base):
        """Should accept a pre-built DatabaseManager."""
        coord = TeamCoordinator(
            project_root=str(tmp_project), db=db,
            openclaw_base=str(openclaw_base),
        )
        assert coord.db is db

    def test_init_without_db(self, tmp_project, openclaw_base):
        """Should create an in-memory DB when none is provided."""
        coord = TeamCoordinator(
            project_root=str(tmp_project), openclaw_base=str(openclaw_base),
        )
        assert coord.db is not None

    def test_init_hermes_router(self, coordinator):
        """Should have a working HermesRouter with models registered."""
        assert hasattr(coordinator, "hermes")
        assert isinstance(coordinator.hermes, HermesRouter)
        # Verify models are registered directly (avoiding get_stats which
        # requires a successful routing decision on a persistent DB)
        assert len(coordinator.hermes._models) == 2
        assert "glm5-worker-1" in coordinator.hermes._models
        assert "glm5-worker-2" in coordinator.hermes._models

    def test_init_default_openclaw_base(self, tmp_project):
        """Should default to ~/.openclaw/agents when no base is given."""
        coord = TeamCoordinator(project_root=str(tmp_project))
        expected = Path.home() / ".openclaw" / "agents"
        assert coord.openclaw_base == expected


class TestDispatch:
    """Tests for the main dispatch pipeline."""

    def test_dispatch_returns_required_keys(self, coordinator):
        """Dispatch result must contain all required keys."""
        result = coordinator.dispatch("Fix the encryption module")
        required = {"task_id", "assigned_worker", "hermes_decision", "skill_match", "status"}
        assert required.issubset(result.keys())

    def test_dispatch_creates_task_file(self, coordinator, openclaw_base):
        """Dispatch should create a .task.md file in the worker's pending queue."""
        result = coordinator.dispatch("Implement REST API endpoint")
        worker_id = result["assigned_worker"]
        task_file = Path(result["task_file"])
        assert task_file.exists()
        assert task_file.suffix == ".md"
        assert "pending" in str(task_file)

    def test_dispatch_task_file_has_frontmatter(self, coordinator):
        """Task file should contain valid YAML frontmatter."""
        result = coordinator.dispatch("Add unit tests for auth module")
        task_file = Path(result["task_file"])
        content = task_file.read_text()
        assert content.startswith("---")
        assert "id:" in content
        assert "status: pending" in content
        assert "hermes_domain:" in content
        assert "hermes_complexity:" in content

    def test_dispatch_assigns_to_known_worker(self, coordinator):
        """Task should always be assigned to a known worker."""
        result = coordinator.dispatch("Refactor database schema")
        assert result["assigned_worker"] in coordinator.workers

    def test_dispatch_with_explicit_assignment(self, coordinator):
        """Explicit assigned_to should override Hermes routing."""
        result = coordinator.dispatch(
            "Security audit", assigned_to="glm5-worker-2"
        )
        assert result["assigned_worker"] == "glm5-worker-2"

    def test_dispatch_hermes_decision_has_domain(self, coordinator):
        """Hermes decision should include domain classification."""
        result = coordinator.dispatch("Analyze performance metrics")
        hd = result["hermes_decision"]
        assert "domain" in hd
        assert "complexity" in hd
        assert "score" in hd

    def test_dispatch_unique_task_ids(self, coordinator):
        """Each dispatch should generate a unique task ID."""
        ids = set()
        for _ in range(10):
            result = coordinator.dispatch("Test task")
            ids.add(result["task_id"])
        assert len(ids) == 10

    def test_dispatch_with_priority(self, coordinator):
        """Priority should be written into the task file frontmatter."""
        result = coordinator.dispatch("Critical fix", priority="high")
        task_file = Path(result["task_file"])
        content = task_file.read_text()
        assert "priority: high" in content


class TestDispatchWithSkill:
    """Tests for skill-driven dispatch."""

    def test_dispatch_with_skill_returns_skill_match(self, coordinator):
        """Skill-driven dispatch should include the skill ID."""
        result = coordinator.dispatch_with_skill(
            skill_id="skill-lint",
            params={"target": "src/"},
            description="Run linting",
        )
        assert result["skill_match"] == "skill-lint"
        assert result["dispatch_mode"] == "skill-driven"

    def test_dispatch_with_skill_sets_high_priority(self, coordinator):
        """Skill-driven dispatch should default to high priority."""
        result = coordinator.dispatch_with_skill(
            skill_id="skill-test",
            params={},
        )
        task_file = Path(result["task_file"])
        content = task_file.read_text()
        assert "priority: high" in content

    def test_dispatch_with_skill_creates_task_file(self, coordinator):
        """Skill dispatch should still create a .task.md file."""
        result = coordinator.dispatch_with_skill(
            skill_id="skill-deploy",
            params={"env": "prod"},
            description="Deploy to production",
        )
        assert Path(result["task_file"]).exists()


class TestCheckStatus:
    """Tests for task status checking."""

    def test_check_status_pending(self, coordinator):
        """Just-dispatched task should be in 'pending' status."""
        result = coordinator.dispatch("Status check task")
        status = coordinator.check_status(result["task_id"])
        assert status["status"] == "pending"

    def test_check_status_unknown_task(self, coordinator):
        """Nonexistent task should return 'unknown' status."""
        status = coordinator.check_status("task-nonexistent-999")
        assert status["status"] == "unknown"

    def test_check_status_completed(self, coordinator, openclaw_base):
        """Task moved to done queue should show 'completed'."""
        result = coordinator.dispatch("Completion check task")
        worker_id = result["assigned_worker"]
        worker = coordinator.workers[worker_id]

        # Move task file from pending to done
        task_file = Path(result["task_file"])
        dest = worker.done_queue / task_file.name
        task_file.rename(dest)

        status = coordinator.check_status(result["task_id"])
        assert status["status"] == "completed"

    def test_check_status_failed(self, coordinator, openclaw_base):
        """Task in failed queue should show 'failed'."""
        result = coordinator.dispatch("Failure check task")
        worker_id = result["assigned_worker"]
        worker = coordinator.workers[worker_id]

        task_file = Path(result["task_file"])
        dest = worker.failed_queue / task_file.name
        task_file.rename(dest)

        status = coordinator.check_status(result["task_id"])
        assert status["status"] == "failed"


class TestCollectResults:
    """Tests for result collection."""

    def test_collect_empty(self, coordinator):
        """No completed tasks should return empty list."""
        results = coordinator.collect_results()
        assert results == []

    def test_collect_completed_tasks(self, coordinator, openclaw_base):
        """Should collect tasks from done queues."""
        # Dispatch and move to done
        for i in range(3):
            result = coordinator.dispatch(f"Result task {i}")
            worker = coordinator.workers[result["assigned_worker"]]
            task_file = Path(result["task_file"])
            task_file.rename(worker.done_queue / task_file.name)

        results = coordinator.collect_results()
        assert len(results) == 3
        for r in results:
            assert "task_id" in r
            assert "worker" in r

    def test_collect_with_since_filter(self, coordinator, openclaw_base):
        """Should filter results by timestamp."""
        # Create a task and move to done
        result = coordinator.dispatch("Filtered result task")
        worker = coordinator.workers[result["assigned_worker"]]
        task_file = Path(result["task_file"])
        task_file.rename(worker.done_queue / task_file.name)

        # Filter for future timestamps — should return empty
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        results = coordinator.collect_results(since=future)
        assert len(results) == 0

        # Filter for past timestamps — should return the task
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        results = coordinator.collect_results(since=past)
        assert len(results) == 1


class TestRecordOutcome:
    """Tests for outcome recording."""

    def test_record_success(self, coordinator):
        """Recording a successful outcome should update Hermes and worker stats."""
        result = coordinator.dispatch("Outcome test task")
        outcome = coordinator.record_outcome(
            task_id=result["task_id"],
            success=True,
            duration_ms=500.0,
            result_summary="Task completed successfully",
        )
        assert outcome["hermes_recorded"] is True
        assert outcome["success"] is True

    def test_record_failure(self, coordinator):
        """Recording a failure should update Hermes and worker stats."""
        result = coordinator.dispatch("Failure outcome test")
        outcome = coordinator.record_outcome(
            task_id=result["task_id"],
            success=False,
            duration_ms=2000.0,
        )
        assert outcome["hermes_recorded"] is True
        assert outcome["success"] is False

    def test_record_outcome_updates_worker_trust(self, coordinator):
        """Successful outcomes should increase worker trust score."""
        worker = coordinator.workers["glm5-worker-1"]
        initial_trust = worker.trust_score

        result = coordinator.dispatch(
            "Trust test task", assigned_to="glm5-worker-1"
        )
        coordinator.record_outcome(result["task_id"], success=True, duration_ms=100.0)

        assert worker.trust_score > initial_trust

    def test_record_failure_decreases_trust(self, coordinator):
        """Failed outcomes should decrease worker trust score."""
        worker = coordinator.workers["glm5-worker-1"]
        initial_trust = worker.trust_score

        result = coordinator.dispatch(
            "Trust decay test", assigned_to="glm5-worker-1"
        )
        coordinator.record_outcome(result["task_id"], success=False, duration_ms=5000.0)

        assert worker.trust_score < initial_trust

    def test_record_outcome_updates_index(self, coordinator):
        """Recording should update the in-memory task index."""
        result = coordinator.dispatch("Index update test")
        coordinator.record_outcome(result["task_id"], success=True, duration_ms=300.0)

        entry = coordinator._task_index[result["task_id"]]
        assert entry["status"] == "completed"
        assert "outcome" in entry


class TestForemanPatrol:
    """Tests for the foreman patrol cycle."""

    def test_patrol_returns_report(self, coordinator):
        """Patrol should return a valid report structure."""
        report = coordinator.run_foreman_patrol()
        required = {"timestamp", "stalled_tasks", "load_balanced", "recommendations"}
        assert required.issubset(report.keys())

    def test_patrol_detects_load_imbalance(self, coordinator, openclaw_base):
        """Patrol should detect imbalance when one worker has many more tasks."""
        worker1 = coordinator.workers["glm5-worker-1"]
        worker2 = coordinator.workers["glm5-worker-2"]

        # Create 5 tasks in worker-1, 0 in worker-2
        for i in range(5):
            task_file = worker1.pending_queue / f"imbalance-{i}.task.md"
            task_file.write_text(f"---\nid: imbalance-{i}\nstatus: pending\n---\n\n# Task {i}\n")

        report = coordinator.run_foreman_patrol()
        assert report["load_balanced"] is False
        assert any("imbalance" in r.lower() for r in report["recommendations"])

    def test_patrol_balanced_when_equal(self, coordinator, openclaw_base):
        """Patrol should report balanced when workers have similar load."""
        report = coordinator.run_foreman_patrol()
        assert report["load_balanced"] is True

    def test_patrol_detects_stalled_tasks(self, coordinator, openclaw_base):
        """Patrol should detect tasks stuck in_progress beyond STALL_THRESHOLD."""
        worker = coordinator.workers["glm5-worker-1"]

        # Create a task with a stale timestamp
        stale_time = (datetime.now(timezone.utc) - STALL_THRESHOLD - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        task_file = worker.pending_queue / "stalled-task.task.md"
        task_file.write_text(
            f"---\nid: stalled-task\nstatus: in_progress\ncreated: {stale_time}\n---\n\n# Stale task\n"
        )

        report = coordinator.run_foreman_patrol()
        assert len(report["stalled_tasks"]) == 1
        assert report["stalled_tasks"][0]["task_file"] == "stalled-task.task.md"


class TestWorkerCycle:
    """Tests for the worker cycle monitoring."""

    def test_worker_cycle_finds_pending_tasks(self, coordinator):
        """Worker cycle should find pending tasks."""
        coordinator.dispatch("Cycle test task 1")
        coordinator.dispatch("Cycle test task 2")

        cycle = coordinator.run_worker_cycle()
        assert cycle["tasks_found"] >= 2

    def test_worker_cycle_specific_worker(self, coordinator):
        """Worker cycle should filter to a specific worker when requested."""
        coordinator.dispatch("Worker-1 task", assigned_to="glm5-worker-1")
        coordinator.dispatch("Worker-2 task", assigned_to="glm5-worker-2")

        cycle = coordinator.run_worker_cycle(worker_id="glm5-worker-1")
        assert cycle["workers_checked"] == ["glm5-worker-1"]
        assert len(cycle["workers"]["glm5-worker-1"]) >= 1

    def test_worker_cycle_empty_queues(self, coordinator):
        """Worker cycle with no pending tasks should return empty."""
        cycle = coordinator.run_worker_cycle()
        assert cycle["tasks_found"] == 0


class TestGetTeamStatus:
    """Tests for team status reporting."""

    def test_team_status_has_workers(self, coordinator):
        """Team status should include per-worker information."""
        status = coordinator.get_team_status()
        assert "workers" in status
        assert "glm5-worker-1" in status["workers"]
        assert "glm5-worker-2" in status["workers"]

    def test_team_status_has_hermes_stats(self, coordinator):
        """Team status should include Hermes router statistics."""
        status = coordinator.get_team_status()
        assert "hermes" in status
        assert status["hermes"]["total_decisions"] == 0

    def test_team_status_shows_subsystem_availability(self, coordinator):
        """Team status should indicate whether mem0 and skill_registry are available."""
        status = coordinator.get_team_status()
        assert "memory_available" in status
        assert "skill_registry_available" in status


class TestCronSetup:
    """Tests for cron job configuration generation."""

    def test_cron_contains_patrol_schedule(self, coordinator):
        """Generated cron should include a patrol schedule."""
        cron = coordinator.setup_cron_jobs()
        assert "*/30" in cron
        assert "--patrol" in cron

    def test_cron_contains_worker_cycle_schedule(self, coordinator):
        """Generated cron should include a worker cycle schedule."""
        cron = coordinator.setup_cron_jobs()
        assert "*/5" in cron
        assert "--worker-cycle" in cron

    def test_cron_contains_project_paths(self, coordinator):
        """Generated cron should reference the project root."""
        cron = coordinator.setup_cron_jobs()
        assert str(coordinator.project_root) in cron


class TestWorkerProfile:
    """Tests for the WorkerProfile dataclass."""

    def test_worker_profile_queue_paths(self, tmp_path):
        """Queue properties should return correct paths."""
        agent_dir = tmp_path / "test-agent"
        profile = WorkerProfile(
            worker_id="test-worker",
            agent_dir=agent_dir,
            specializations=["code"],
        )
        assert profile.pending_queue.parts[-2:] == ("tasks", "pending")  # Windows-safe
        assert profile.done_queue.parts[-2:] == ("tasks", "done")  # Windows-safe
        assert profile.failed_queue.parts[-2:] == ("tasks", "failed")  # Windows-safe

    def test_worker_profile_default_stats(self):
        """Default stats should all be zero."""
        profile = WorkerProfile(
            worker_id="test", agent_dir=Path("/tmp/test"),
        )
        assert profile.stats["completed"] == 0
        assert profile.stats["failed"] == 0
        assert profile.stats["stalled"] == 0


class TestTaskFileParsing:
    """Tests for .task.md file parsing."""

    def test_parse_valid_task_file(self, coordinator, tmp_path):
        """Should correctly parse frontmatter and body from a task file."""
        task_file = tmp_path / "test.task.md"
        task_file.write_text(
            "---\n"
            "id: task-001\n"
            "priority: high\n"
            "status: pending\n"
            "hermes_domain: code\n"
            "---\n"
            "\n"
            "# Fix encryption bug\n"
            "\n"
            "Description here.\n"
        )
        parsed = coordinator._parse_task_file(task_file)
        assert parsed is not None
        assert parsed["id"] == "task-001"
        assert parsed["priority"] == "high"
        assert parsed["title"] == "Fix encryption bug"
        assert parsed["hermes_domain"] == "code"

    def test_parse_file_without_frontmatter(self, coordinator, tmp_path):
        """Should handle files without YAML frontmatter."""
        task_file = tmp_path / "no-fm.task.md"
        task_file.write_text("# Plain task\n\nNo frontmatter here.")
        parsed = coordinator._parse_task_file(task_file)
        assert parsed is not None
        assert parsed["title"] == "Plain task"

    def test_parse_nonexistent_file(self, coordinator):
        """Should return None for nonexistent files."""
        result = coordinator._parse_task_file(Path("/nonexistent/task.task.md"))
        assert result is None


class TestGracefulDegradation:
    """Tests for graceful degradation when optional subsystems are missing."""

    def test_dispatch_without_mem0(self, coordinator_no_db):
        """Dispatch should work even without mem0 adapter."""
        assert coordinator_no_db.memory is None
        result = coordinator_no_db.dispatch("Test without mem0")
        assert result["status"] == "pending"
        assert result["memories_found"] == 0

    def test_dispatch_without_skill_registry(self, coordinator_no_db):
        """Dispatch should work even without skill registry.

        We mock the skill_registry attribute to None to simulate the
        import failing at module level.  The coordinator should still
        dispatch tasks normally.
        """
        coordinator_no_db.skill_registry = None
        result = coordinator_no_db.dispatch("Test without skills")
        assert result["skill_match"] is None
        assert result["status"] == "pending"

    def test_record_outcome_without_mem0(self, coordinator_no_db):
        """Outcome recording should work without mem0."""
        result = coordinator_no_db.dispatch("Outcome without mem0")
        outcome = coordinator_no_db.record_outcome(
            result["task_id"], True, 100.0, "All good"
        )
        assert outcome["hermes_recorded"] is True
        assert outcome["mem0_recorded"] is False


class TestDomainWorkerMap:
    """Tests for the domain-to-worker default mapping."""

    def test_all_domains_mapped(self):
        """Every TaskDomain value should have a worker mapping."""
        for domain in TaskDomain:
            assert domain.value in DOMAIN_WORKER_MAP

    def test_mappings_point_to_valid_workers(self):
        """All mapped workers should exist in WORKER_DEFINITIONS."""
        valid_workers = {w["worker_id"] for w in WORKER_DEFINITIONS}
        for wid in DOMAIN_WORKER_MAP.values():
            assert wid in valid_workers


class TestLeastLoadedWorkerSelection:
    """Tests for load-balancing worker selection."""

    def test_selects_worker_with_fewest_tasks(self, coordinator, openclaw_base):
        """Should select the worker with the smallest pending queue."""
        w1 = coordinator.workers["glm5-worker-1"]
        w2 = coordinator.workers["glm5-worker-2"]

        # Add tasks to worker-1
        for i in range(5):
            (w1.pending_queue / f"load-{i}.task.md").write_text("---\nid: load-{i}\n---\n")

        selected = coordinator._select_least_loaded_worker()
        assert selected.worker_id == "glm5-worker-2"

    def test_balanced_selects_any(self, coordinator):
        """When balanced, should select a valid worker (either is fine)."""
        selected = coordinator._select_least_loaded_worker()
        assert selected.worker_id in coordinator.workers
