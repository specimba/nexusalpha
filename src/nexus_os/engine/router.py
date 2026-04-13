"""
engine/router.py — Engine Router

Manages task lifecycle and DAG-based dependency resolution.
Provides the EngineRouter class used by TaskExecutor to discover
ready-to-execute tasks based on dependency ordering.

Part of Nexus OS A2A System — Engine Pillar
"""

import enum
import logging
import sqlite3
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class TaskStatus(enum.Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class EngineRouter:
    """
    Routes tasks to executors based on dependency DAG and priority.

    Tracks task dependencies (parent -> child), ensures children only
    become ready after all parents complete successfully. Provides
    get_ready_tasks() for executor consumption and status transitions
    for lifecycle management.
    """

    def __init__(self, db_manager):
        """
        Initialize the router with a DatabaseManager instance.
        Creates the tasks and task_dependencies tables if they don't exist.
        """
        self.db = db_manager
        self._ensure_tables()

    def _ensure_tables(self):
        """Create tasks and dependency tables if missing."""
        conn = self.db.get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 5,
                context TEXT DEFAULT '{}',
                heartbeat REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS task_dependencies (
                parent_task_id TEXT NOT NULL,
                child_task_id TEXT NOT NULL,
                PRIMARY KEY (parent_task_id, child_task_id),
                FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id),
                FOREIGN KEY (child_task_id) REFERENCES tasks(task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_project_status
                ON tasks(project_id, status);
        """)
        conn.commit()

    def add_task(
        self,
        task_id: str,
        project_id: str,
        description: str = "",
        priority: int = 5,
        context: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None,
    ) -> bool:
        """
        Register a new task with optional dependencies.
        Returns True if the task was created successfully.
        """
        import json
        conn = self.db.get_connection()
        try:
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, description, priority, context) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, project_id, description, priority,
                 json.dumps(context or {})),
            )
            if dependencies:
                for dep_id in dependencies:
                    conn.execute(
                        "INSERT OR IGNORE INTO task_dependencies (parent_task_id, child_task_id) "
                        "VALUES (?, ?)",
                        (dep_id, task_id),
                    )
            conn.commit()
            logger.debug("Task registered: %s (deps=%s)", task_id, dependencies)
            return True
        except sqlite3.IntegrityError as e:
            logger.warning("Failed to register task %s: %s", task_id, e)
            return False

    def get_ready_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get all tasks that are ready for execution.

        A task is ready if:
        1. Its status is 'pending'
        2. It belongs to the given project
        3. All of its parent dependencies have status 'completed'
        4. It has no failed or cancelled parents

        Results are ordered by priority (higher first) then creation time.
        """
        import json
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row

        # Tasks with no dependencies that are pending
        no_deps = conn.execute("""
            SELECT t.* FROM tasks t
            WHERE t.project_id = ? AND t.status = 'pending'
            AND t.task_id NOT IN (
                SELECT DISTINCT child_task_id FROM task_dependencies
            )
            ORDER BY t.priority DESC, t.created_at ASC
        """, (project_id,)).fetchall()

        # Tasks whose all parents are completed (none in-progress/pending/failed/cancelled)
        with_deps = conn.execute("""
            SELECT t.* FROM tasks t
            WHERE t.project_id = ? AND t.status = 'pending'
            AND t.task_id IN (
                SELECT d.child_task_id FROM task_dependencies d
                WHERE NOT EXISTS (
                    SELECT 1 FROM task_dependencies d2
                    JOIN tasks p ON p.task_id = d2.parent_task_id
                    WHERE d2.child_task_id = d.child_task_id
                    AND p.status NOT IN ('completed')
                )
            )
            ORDER BY t.priority DESC, t.created_at ASC
        """, (project_id,)).fetchall()

        results = []
        for row in list(no_deps) + list(with_deps):
            results.append({
                "task_id": row["task_id"],
                "project_id": row["project_id"],
                "description": row["description"],
                "priority": row["priority"],
                "context": json.loads(row["context"]) if row["context"] else {},
                "status": row["status"],
            })
        return results

    def get_blocked_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        """Get tasks blocked by incomplete dependencies."""
        import json
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT t.* FROM tasks t
            JOIN task_dependencies d ON d.child_task_id = t.task_id
            JOIN tasks pt ON pt.task_id = d.parent_task_id
            WHERE t.project_id = ? AND t.status = 'pending'
            AND pt.status != 'completed'
            GROUP BY t.task_id
        """, (project_id,)).fetchall()

        return [
            {
                "task_id": row["task_id"],
                "description": row["description"],
                "blocking_parents": self._get_blocking_parents(row["task_id"]),
            }
            for row in rows
        ]

    def _get_blocking_parents(self, task_id: str) -> List[str]:
        """Get IDs of parent tasks that haven't completed yet."""
        conn = self.db.get_connection()
        rows = conn.execute("""
            SELECT pt.task_id FROM tasks pt
            JOIN task_dependencies d ON d.parent_task_id = pt.task_id
            WHERE d.child_task_id = ? AND pt.status != 'completed'
        """, (task_id,)).fetchall()
        return [r[0] for r in rows]

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get the current status of a task."""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row:
            return TaskStatus(row[0])
        return None

    def update_task_status(self, task_id: str, status: TaskStatus):
        """Transition a task to a new status."""
        import time
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE task_id = ?",
            (status.value, task_id),
        )
        conn.commit()

    def get_project_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all tasks for a project with their statuses."""
        import json
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY priority DESC",
            (project_id,),
        ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "description": row["description"],
                "status": row["status"],
                "priority": row["priority"],
                "context": json.loads(row["context"]) if row["context"] else {},
            }
            for row in rows
        ]
