"""
engine/heartbeat.py — Heartbeat Monitor and Task Reclamation

Detects stalled agents and reclaims their tasks for re-assignment.
Integrates with EngineRouter and DatabaseManager for lifecycle management.

Design:
  - Background daemon thread (configurable interval, default 30s)
  - Heartbeat timeout = 2x check interval (configurable)
  - Reclaimed tasks reset to 'pending' with agent_id cleared
  - Agent registry updated: stalled agents set to 'suspended'
  - Audit log entry for every reclamation event
  - Graceful shutdown support
"""

import time
import threading
import logging
import uuid
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass

from nexus_os.db.manager import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class ReclamationEvent:
    """Record of a single task reclamation."""
    task_id: str
    project_id: str
    previous_agent_id: Optional[str]
    reason: str
    timestamp: float
    trace_id: str


class HeartbeatMonitor:
    """
    Background thread that monitors agent heartbeats and reclaims stalled tasks.

    Lifecycle:
      start() → spawns daemon thread → _monitor_loop()
      stop()  → sets stop event → joins thread (5s timeout)

    Reclamation logic:
      1. Find tasks with status='in_progress' AND heartbeat < (now - timeout)
      2. Reset task to 'pending', clear agent_id
      3. Mark the previous agent as 'suspended' in agent_registry
      4. Write audit log entry
      5. Collect ReclamationEvent for callers to inspect
    """

    def __init__(
        self,
        db: DatabaseManager,
        check_interval: int = 30,
        heartbeat_timeout_multiplier: float = 2.0,
        max_reclamations_per_cycle: int = 50,
    ):
        self.db = db
        self.check_interval = check_interval
        self.timeout = check_interval * heartbeat_timeout_multiplier
        self.max_reclamations = max_reclamations_per_cycle
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._events: List[ReclamationEvent] = []
        self._lock = threading.Lock()
        self._suspended_agents: Set[str] = set()
        self._cycle_count = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def events(self) -> List[ReclamationEvent]:
        with self._lock:
            return list(self._events)

    @property
    def suspended_agents(self) -> Set[str]:
        with self._lock:
            return set(self._suspended_agents)

    def start(self):
        """Start the heartbeat monitoring daemon thread."""
        if self.is_running:
            logger.warning("HeartbeatMonitor already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="heartbeat-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "HeartbeatMonitor started (interval=%ds, timeout=%.1fs)",
            self.check_interval, self.timeout
        )

    def stop(self):
        """Stop the heartbeat monitoring daemon thread."""
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("HeartbeatMonitor stopped after %d cycles.", self._cycle_count)

    def check_now(self) -> List[ReclamationEvent]:
        """
        Perform a single reclamation check (synchronous, no threading).
        Useful for testing or manual triggering.
        """
        return self._reclaim_stalled_tasks()

    def _monitor_loop(self):
        """Main daemon loop — runs until stop() is called."""
        logger.info("HeartbeatMonitor loop started.")
        while not self._stop_event.is_set():
            try:
                self._reclaim_stalled_tasks()
                self._cycle_count += 1
            except Exception as e:
                logger.error("Heartbeat monitor cycle %d error: %s", self._cycle_count, e)
            self._stop_event.wait(self.check_interval)
        logger.info("HeartbeatMonitor loop exiting.")

    def _reclaim_stalled_tasks(self) -> List[ReclamationEvent]:
        """
        Find tasks in 'in_progress' with stale heartbeats and reclaim them.

        Returns:
            List of ReclamationEvent objects for this cycle.
        """
        conn = self.db.get_connection()
        cutoff = time.time() - self.timeout

        rows = conn.execute(
            """SELECT task_id, project_id, agent_id, heartbeat
               FROM tasks
               WHERE status = 'in_progress' AND heartbeat < ?
               ORDER BY heartbeat ASC
               LIMIT ?""",
            (cutoff, self.max_reclamations)
        ).fetchall()

        cycle_events: List[ReclamationEvent] = []

        for row in rows:
            task_id = row[0]
            project_id = row[1]
            agent_id = row[2]
            last_heartbeat = row[3]
            stale_seconds = time.time() - last_heartbeat

            trace_id = str(uuid.uuid4())

            # 1. Reset task to pending
            conn.execute(
                """UPDATE tasks
                   SET status = 'pending', agent_id = NULL, heartbeat = NULL
                   WHERE task_id = ?""",
                (task_id,)
            )

            # 2. Suspend the agent (if not already suspended)
            if agent_id:
                conn.execute(
                    """UPDATE agent_registry
                       SET status = 'suspended', last_seen = ?
                       WHERE agent_id = ? AND status != 'halted'""",
                    (time.time(), agent_id)
                )
                with self._lock:
                    self._suspended_agents.add(agent_id)

            # 3. Write audit log
            conn.execute(
                """INSERT INTO audit_logs (actor_id, action, resource_id, decision, details, trace_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent_id or "system",
                    "heartbeat_reclamation",
                    task_id,
                    "deny",
                    f"Task reclaimed: heartbeat stale by {stale_seconds:.0f}s (timeout={self.timeout:.0f}s)",
                    trace_id,
                )
            )

            event = ReclamationEvent(
                task_id=task_id,
                project_id=project_id,
                previous_agent_id=agent_id,
                reason=f"Heartbeat stale by {stale_seconds:.0f}s",
                timestamp=time.time(),
                trace_id=trace_id,
            )
            cycle_events.append(event)

            logger.warning(
                "Reclaimed task %s from agent %s (stale %.0fs)",
                task_id, agent_id, stale_seconds
            )

        conn.commit()

        if cycle_events:
            with self._lock:
                self._events.extend(cycle_events)
            logger.info(
                "HeartbeatMonitor cycle %d: reclaimed %d tasks",
                self._cycle_count, len(cycle_events)
            )

        return cycle_events

    def unsuspend_agent(self, agent_id: str) -> bool:
        """
        Manually re-activate a suspended agent.
        Returns True if the agent was found and re-activated.
        """
        conn = self.db.get_connection()
        cursor = conn.execute(
            """UPDATE agent_registry
               SET status = 'active', last_seen = ?
               WHERE agent_id = ? AND status = 'suspended'""",
            (time.time(), agent_id)
        )
        conn.commit()
        if cursor.rowcount > 0:
            with self._lock:
                self._suspended_agents.discard(agent_id)
            logger.info("Agent %s re-activated.", agent_id)
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Return monitor statistics."""
        with self._lock:
            return {
                "is_running": self.is_running,
                "cycle_count": self._cycle_count,
                "total_reclamations": len(self._events),
                "suspended_agents": list(self._suspended_agents),
                "check_interval": self.check_interval,
                "timeout": self.timeout,
            }
