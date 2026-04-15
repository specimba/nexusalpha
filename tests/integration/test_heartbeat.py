"""
tests/integration/test_heartbeat.py — Heartbeat Monitor Integration Tests

Tests task reclamation, agent suspension, and lifecycle management.
"""

import pytest
import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.engine.heartbeat import HeartbeatMonitor


@pytest.fixture
def db():
    config = DBConfig(db_path="test_heartbeat.db", passphrase="x", encrypted=False)
    db_mgr = DatabaseManager(config)
    db_mgr.setup_schema()
    # Register test agents
    conn = db_mgr.get_connection()
    conn.execute(
        "INSERT INTO agent_registry (agent_id, model_id, status) VALUES (?, ?, 'active')",
        ("agent-good", "osman-coder")
    )
    conn.execute(
        "INSERT INTO agent_registry (agent_id, model_id, status) VALUES (?, ?, 'active')",
        ("agent-stale", "osman-coder")
    )
    conn.commit()
    yield db_mgr
    db_mgr.close()
    if os.path.exists("test_heartbeat.db"):
        os.remove("test_heartbeat.db")


@pytest.fixture
def monitor(db):
    return HeartbeatMonitor(db, check_interval=10, heartbeat_timeout_multiplier=2.0)


class TestTaskReclamation:
    def test_reclaim_stale_task(self, db, monitor):
        """Task with stale heartbeat should be reclaimed."""
        conn = db.get_connection()
        now = time.time()
        # Create a task with a very old heartbeat
        conn.execute(
            """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
               VALUES (?, ?, ?, 'in_progress', ?, ?)""",
            ("task-stale", "proj-1", "agent-stale", now - 100, now - 50)
        )
        # Create a fresh task (should NOT be reclaimed)
        conn.execute(
            """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
               VALUES (?, ?, ?, 'in_progress', ?, ?)""",
            ("task-fresh", "proj-1", "agent-good", now, now)
        )
        conn.commit()

        events = monitor.check_now()
        assert len(events) == 1
        assert events[0].task_id == "task-stale"

        # Verify task was reset
        row = conn.execute(
            "SELECT status, agent_id FROM tasks WHERE task_id = 'task-stale'"
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] is None

        # Verify fresh task was NOT affected
        row = conn.execute(
            "SELECT status, agent_id FROM tasks WHERE task_id = 'task-fresh'"
        ).fetchone()
        assert row[0] == "in_progress"
        assert row[1] == "agent-good"

    def test_suspended_agent_after_reclamation(self, db, monitor):
        """Agent should be suspended after its task is reclaimed."""
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
               VALUES (?, ?, ?, 'in_progress', ?, ?)""",
            ("task-susp", "proj-1", "agent-stale", time.time() - 100, time.time() - 50)
        )
        conn.commit()

        monitor.check_now()

        row = conn.execute(
            "SELECT status FROM agent_registry WHERE agent_id = 'agent-stale'"
        ).fetchone()
        assert row[0] == "suspended"

    def test_no_reclamation_for_pending_tasks(self, db, monitor):
        """Pending tasks should never be reclaimed."""
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            ("task-pending", "proj-1", "agent-1", time.time() - 200, time.time() - 200)
        )
        conn.commit()

        events = monitor.check_now()
        assert len(events) == 0


class TestMonitorLifecycle:
    def test_start_and_stop(self, monitor):
        """Monitor should start and stop cleanly."""
        assert not monitor.is_running
        monitor.start()
        assert monitor.is_running
        monitor.stop()
        assert not monitor.is_running

    def test_double_start_ignored(self, monitor):
        """Starting an already running monitor should be a no-op."""
        monitor.start()
        monitor.start()  # Should log warning, not crash
        assert monitor.is_running
        monitor.stop()

    def test_stats(self, db, monitor):
        """get_stats should return current monitor state."""
        monitor.start()
        time.sleep(0.5)
        stats = monitor.get_stats()
        assert stats["is_running"] is True
        assert stats["check_interval"] == 10
        assert stats["timeout"] == 20.0
        monitor.stop()


class TestAgentUnsuspend:
    def test_unsuspend_agent(self, db, monitor):
        """Should re-activate a suspended agent."""
        conn = db.get_connection()
        conn.execute(
            "UPDATE agent_registry SET status = 'suspended' WHERE agent_id = 'agent-stale'"
        )
        conn.commit()

        result = monitor.unsuspend_agent("agent-stale")
        assert result is True

        row = conn.execute(
            "SELECT status FROM agent_registry WHERE agent_id = 'agent-stale'"
        ).fetchone()
        assert row[0] == "active"

    def test_unsuspend_nonexistent(self, monitor):
        result = monitor.unsuspend_agent("ghost-agent")
        assert result is False


class TestReclamationEvents:
    def test_events_accumulate(self, db, monitor):
        """Events should accumulate across multiple check cycles."""
        conn = db.get_connection()
        for i in range(3):
            conn.execute(
                """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
                   VALUES (?, ?, ?, 'in_progress', ?, ?)""",
                (f"task-evt-{i}", "proj-1", f"agent-{i}", time.time() - 100, time.time() - 50)
            )
        conn.commit()

        monitor.check_now()
        assert len(monitor.events) == 3

    def test_suspended_agents_tracked(self, db, monitor):
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO tasks (task_id, project_id, agent_id, status, heartbeat, created_at)
               VALUES (?, ?, ?, 'in_progress', ?, ?)""",
            ("task-track", "proj-1", "agent-stale", time.time() - 100, time.time() - 50)
        )
        conn.commit()

        monitor.check_now()
        assert "agent-stale" in monitor.suspended_agents
