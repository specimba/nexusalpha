"""
tests/engine/test_router.py — EngineRouter Unit Tests

Tests DAG-based dependency resolution, task lifecycle management,
and ready-task discovery.
"""

import pytest
import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class FakeDBManager:
    """Lightweight in-memory SQLite wrapper for router tests."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    def get_connection(self):
        return self._conn

    def close(self):
        self._conn.close()


@pytest.fixture
def db():
    mgr = FakeDBManager()
    yield mgr
    mgr.close()


@pytest.fixture
def router(db):
    from nexus_os.engine.router import EngineRouter
    return EngineRouter(db)


class TestTaskRegistration:
    def test_add_task_no_deps(self, router):
        ok = router.add_task("t1", "proj-1", "Task 1", priority=5)
        assert ok is True

    def test_add_task_with_deps(self, router):
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        blocked = router.get_blocked_tasks("proj-1")
        assert any(t["task_id"] == "t-child" for t in blocked)

    def test_add_duplicate_task_fails(self, router):
        router.add_task("t1", "proj-1", "First")
        ok = router.add_task("t1", "proj-1", "Duplicate")
        assert ok is False

    def test_add_task_with_context(self, router):
        router.add_task("t1", "proj-1", "Ctx task", context={"key": "value"})
        tasks = router.get_project_tasks("proj-1")
        assert tasks[0]["context"] == {"key": "value"}


class TestReadyTasks:
    def test_no_deps_is_ready(self, router):
        router.add_task("t1", "proj-1", "Standalone")
        ready = router.get_ready_tasks("proj-1")
        assert len(ready) == 1
        assert ready[0]["task_id"] == "t1"

    def test_with_unmet_deps_not_ready(self, router):
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        ready = router.get_ready_tasks("proj-1")
        assert len(ready) == 1
        assert ready[0]["task_id"] == "t-parent"

    def test_deps_met_becomes_ready(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        router.update_task_status("t-parent", TaskStatus.COMPLETED)
        ready = router.get_ready_tasks("proj-1")
        ready_ids = [t["task_id"] for t in ready]
        assert "t-child" in ready_ids

    def test_failed_parent_blocks_child(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        router.update_task_status("t-parent", TaskStatus.FAILED)
        ready = router.get_ready_tasks("proj-1")
        ready_ids = [t["task_id"] for t in ready]
        assert "t-child" not in ready_ids

    def test_cancelled_parent_blocks_child(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        router.update_task_status("t-parent", TaskStatus.CANCELLED)
        ready = router.get_ready_tasks("proj-1")
        ready_ids = [t["task_id"] for t in ready]
        assert "t-child" not in ready_ids

    def test_in_progress_parent_blocks_child(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t-parent", "proj-1", "Parent")
        router.add_task("t-child", "proj-1", "Child", dependencies=["t-parent"])
        router.update_task_status("t-parent", TaskStatus.IN_PROGRESS)
        ready = router.get_ready_tasks("proj-1")
        ready_ids = [t["task_id"] for t in ready]
        assert "t-child" not in ready_ids

    def test_priority_ordering(self, router):
        router.add_task("t-low", "proj-1", "Low priority", priority=1)
        router.add_task("t-high", "proj-1", "High priority", priority=10)
        ready = router.get_ready_tasks("proj-1")
        assert ready[0]["task_id"] == "t-high"

    def test_multi_project_isolation(self, router):
        router.add_task("t-a", "proj-a", "Task A")
        router.add_task("t-b", "proj-b", "Task B")
        ready_a = router.get_ready_tasks("proj-a")
        ready_b = router.get_ready_tasks("proj-b")
        assert len(ready_a) == 1 and ready_a[0]["task_id"] == "t-a"
        assert len(ready_b) == 1 and ready_b[0]["task_id"] == "t-b"

    def test_diamond_dependency(self, router):
        """Diamond: parent -> [child-a, child-b] -> grandchild"""
        from nexus_os.engine.router import TaskStatus
        router.add_task("parent", "proj-1", "Parent")
        router.add_task("child-a", "proj-1", "Child A", dependencies=["parent"])
        router.add_task("child-b", "proj-1", "Child B", dependencies=["parent"])
        router.add_task("grandchild", "proj-1", "Grandchild",
                        dependencies=["child-a", "child-b"])

        # Initially only parent is ready
        ready = router.get_ready_tasks("proj-1")
        assert len(ready) == 1

        # Complete parent
        router.update_task_status("parent", TaskStatus.COMPLETED)
        ready = router.get_ready_tasks("proj-1")
        assert len(ready) == 2

        # Complete both children
        router.update_task_status("child-a", TaskStatus.COMPLETED)
        router.update_task_status("child-b", TaskStatus.COMPLETED)
        ready = router.get_ready_tasks("proj-1")
        assert len(ready) == 1
        assert ready[0]["task_id"] == "grandchild"

    def test_one_of_many_deps_unmet(self, router):
        """Task with 3 deps: only 2 completed -> still blocked."""
        from nexus_os.engine.router import TaskStatus
        router.add_task("dep1", "proj-1", "Dep 1")
        router.add_task("dep2", "proj-1", "Dep 2")
        router.add_task("dep3", "proj-1", "Dep 3")
        router.add_task("child", "proj-1", "Child",
                        dependencies=["dep1", "dep2", "dep3"])
        router.update_task_status("dep1", TaskStatus.COMPLETED)
        router.update_task_status("dep2", TaskStatus.COMPLETED)
        ready = router.get_ready_tasks("proj-1")
        ready_ids = [t["task_id"] for t in ready]
        assert "child" not in ready_ids
        # dep3 should still be ready
        assert "dep3" in ready_ids


class TestBlockedTasks:
    def test_blocked_returns_blocking_parents(self, router):
        router.add_task("t-p", "proj-1", "Parent")
        router.add_task("t-c", "proj-1", "Child", dependencies=["t-p"])
        blocked = router.get_blocked_tasks("proj-1")
        assert len(blocked) == 1
        assert "t-p" in blocked[0]["blocking_parents"]

    def test_completed_not_in_blocked(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t-p", "proj-1", "Parent")
        router.add_task("t-c", "proj-1", "Child", dependencies=["t-p"])
        router.update_task_status("t-p", TaskStatus.COMPLETED)
        blocked = router.get_blocked_tasks("proj-1")
        assert len(blocked) == 0

    def test_multiple_blocking_parents(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("dep1", "proj-1", "Dep 1")
        router.add_task("dep2", "proj-1", "Dep 2")
        router.add_task("child", "proj-1", "Child",
                        dependencies=["dep1", "dep2"])
        router.update_task_status("dep1", TaskStatus.COMPLETED)
        blocked = router.get_blocked_tasks("proj-1")
        assert len(blocked) == 1
        assert "dep2" in blocked[0]["blocking_parents"]


class TestTaskStatus:
    def test_get_status(self, router):
        router.add_task("t1", "proj-1", "Task")
        from nexus_os.engine.router import TaskStatus
        status = router.get_task_status("t1")
        assert status == TaskStatus.PENDING

    def test_get_nonexistent_status(self, router):
        status = router.get_task_status("nonexistent")
        assert status is None

    def test_status_transitions(self, router):
        from nexus_os.engine.router import TaskStatus
        router.add_task("t1", "proj-1", "Task")
        router.update_task_status("t1", TaskStatus.IN_PROGRESS)
        assert router.get_task_status("t1") == TaskStatus.IN_PROGRESS
        router.update_task_status("t1", TaskStatus.COMPLETED)
        assert router.get_task_status("t1") == TaskStatus.COMPLETED

    def test_all_status_values(self, router):
        from nexus_os.engine.router import TaskStatus
        for ts in TaskStatus:
            router.add_task(f"task-{ts.value}", "proj-1", ts.value)
            router.update_task_status(f"task-{ts.value}", ts)
            assert router.get_task_status(f"task-{ts.value}") == ts


class TestProjectTasks:
    def test_get_all_project_tasks(self, router):
        router.add_task("t1", "proj-1", "A")
        router.add_task("t2", "proj-1", "B")
        router.add_task("t3", "proj-2", "C")
        tasks = router.get_project_tasks("proj-1")
        assert len(tasks) == 2

    def test_priority_sorted(self, router):
        router.add_task("t1", "proj-1", "Low", priority=1)
        router.add_task("t2", "proj-1", "High", priority=10)
        tasks = router.get_project_tasks("proj-1")
        assert tasks[0]["priority"] >= tasks[1]["priority"]
