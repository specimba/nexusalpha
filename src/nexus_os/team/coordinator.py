"""
team/coordinator.py — Agentic Team Coordinator

Central dispatch system for the GLM-5 full-stack long-term agentic team.

Wires together:
  - Hermes experience-based routing  (who handles this task?)
  - mem0 persistent memory           (what do we know about similar tasks?)
  - Skill registry                    (which platform skill can help?)
  - OpenClaw file-driven task dispatch (how do we assign work?)
  - Outcome recording                  (what did we learn?)

Architecture::

    User Request
        │
        ▼
    ┌─────────────────────────────────────────────────┐
    │  TeamCoordinator.dispatch(task_description)      │
    │                                                  │
    │  1. Query mem0 for relevant past experience      │
    │  2. Classify task via Hermes (domain+complexity) │
    │  3. Check skill registry for fast-path match     │
    │  4. Select worker based on availability+ability  │
    │  5. Create .task.md in worker's pending queue    │
    │  6. Monitor for completion                       │
    │  7. Record outcome to Hermes + mem0              │
    └─────────────────────────────────────────────────┘

Token Efficiency:
  - File-driven coordination (tasks in .task.md files, not in prompts)
  - Context injection only when relevant (mem0 search, not full history)
  - Workers receive minimal context (task description + relevant memories)
  - Results written to files, not returned through prompt chain
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Conditional imports for concurrent subsystems ──────────────────────

try:
    from nexus_os.vault.memory_adapter import Mem0Adapter
except ImportError:
    Mem0Adapter = None  # Graceful degradation

try:
    from nexus_os.engine.skill_adapter import SkillRegistry
except ImportError:
    SkillRegistry = None  # Graceful degradation

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.engine.hermes import (
    HermesRouter,
    ModelProfile,
    TaskDomain,
    TaskComplexity,
    RoutingDecision,
    SkillRecord,
)


# ── Constants ──────────────────────────────────────────────────────────

DEFAULT_OPENCLAW_BASE = Path.home() / ".openclaw" / "agents"

WORKER_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "worker_id": "glm5-worker-1",
        "agent_dir": "glm5-worker-1",
        "specializations": ["code", "analysis", "reasoning"],
        "model_profile": None,  # set dynamically
    },
    {
        "worker_id": "glm5-worker-2",
        "agent_dir": "glm5-worker-2",
        "specializations": ["code", "operations", "security"],
        "model_profile": None,
    },
]

# Domain → worker mapping for default routing when Hermes is unavailable
DOMAIN_WORKER_MAP: Dict[str, str] = {
    "code": "glm5-worker-1",
    "analysis": "glm5-worker-2",
    "reasoning": "glm5-worker-1",
    "creative": "glm5-worker-2",
    "operations": "glm5-worker-2",
    "security": "glm5-worker-2",
    "unknown": "glm5-worker-1",
}

STALL_THRESHOLD = timedelta(minutes=10)


# ── Data Classes ───────────────────────────────────────────────────────

@dataclass
class WorkerProfile:
    """Profile of a single OpenClaw worker agent.

    Attributes:
        worker_id:        Unique identifier (e.g. "glm5-worker-1").
        agent_dir:        Absolute path to the agent's OpenClaw directory.
        specializations:  List of domain keywords this worker is good at.
        stats:            Running counts of completed / failed / stalled tasks.
        trust_score:      Composite trust score from Hermes (0.0–1.0).
        available:        True when the worker has no in_progress task.
        pending_queue:    Path to the worker's ``tasks/pending/`` directory.
        done_queue:       Path to the worker's ``tasks/done/`` directory.
        failed_queue:     Path to the worker's ``tasks/failed/`` directory.
    """
    worker_id: str
    agent_dir: Path
    specializations: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "completed": 0, "failed": 0, "stalled": 0,
    })
    trust_score: float = 0.5
    available: bool = True

    @property
    def pending_queue(self) -> Path:
        return self.agent_dir / "tasks" / "pending"

    @property
    def done_queue(self) -> Path:
        return self.agent_dir / "tasks" / "done"

    @property
    def failed_queue(self) -> Path:
        return self.agent_dir / "tasks" / "failed"


# ── Coordinator ────────────────────────────────────────────────────────

class TeamCoordinator:
    """Central dispatch for the GLM-5 full-stack long-term agentic team.

    Orchestrates:
      - Hermes experience-based routing (who handles this task?)
      - mem0 persistent memory (what do we know about similar tasks?)
      - Skill registry (which platform skill can help?)
      - OpenClaw file-driven task dispatch (how do we assign work?)
      - Outcome recording (what did we learn?)

    The coordinator is designed for graceful degradation: if mem0 or
    skill_adapter are not installed, the system still routes and dispatches
    tasks using Hermes alone.

    Parameters:
        project_root:   Root directory of the Nexus OS project.
        db:             Optional pre-built DatabaseManager.  If *None*, an
                        in-memory database is created automatically.
        openclaw_base:  Base directory for OpenClaw agents.  Defaults to
                        ``~/.openclaw/agents/``.
    """

    def __init__(
        self,
        project_root: str,
        db: Optional[DatabaseManager] = None,
        openclaw_base: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.openclaw_base = Path(openclaw_base) if openclaw_base else DEFAULT_OPENCLAW_BASE

        # ── Database ──
        if db is not None:
            self.db = db
        else:
            config = DBConfig(
                db_path=":memory:",
                passphrase="coordinator-dev",
                encrypted=False,
            )
            self.db = DatabaseManager(config)
            self.db.setup_schema()

        # ── Hermes Router ──
        self._init_hermes()

        # ── mem0 Memory (optional) ──
        self.memory: Optional[Any] = None
        if Mem0Adapter is not None:
            try:
                self.memory = Mem0Adapter(project_root=str(self.project_root))
                logger.info("mem0 memory adapter initialised")
            except Exception as exc:
                logger.warning("mem0 adapter failed to initialise: %s", exc)

        # ── Skill Registry (optional) ──
        self.skill_registry: Optional[Any] = None
        if SkillRegistry is not None:
            try:
                self.skill_registry = SkillRegistry()
                logger.info("Skill registry initialised")
            except Exception as exc:
                logger.warning("Skill registry failed to initialise: %s", exc)

        # ── Worker Profiles ──
        self.workers: Dict[str, WorkerProfile] = {}
        self._load_worker_profiles()

        # ── Task tracking ──
        self._task_index: Dict[str, Dict[str, Any]] = {}

    # ────────────────────────────────────────────────────────────────────
    # Initialisation helpers
    # ────────────────────────────────────────────────────────────────────

    def _init_hermes(self) -> None:
        """Build a HermesRouter with model profiles matching each worker."""
        models: List[ModelProfile] = []
        for wdef in WORKER_DEFINITIONS:
            mid = wdef["worker_id"]
            models.append(ModelProfile(
                model_id=mid,
                provider="local",
                cost_per_token=0.0,
                max_context=8192,
                capabilities=wdef["specializations"],
                latency_estimate_ms=500.0,
                is_local=True,
                quality_score=0.5,
            ))
        self.hermes = HermesRouter(self.db, models=models, quality_threshold=0.4)

    def _load_worker_profiles(self) -> None:
        """Load WorkerProfile objects for each known worker."""
        for wdef in WORKER_DEFINITIONS:
            agent_dir = self.openclaw_base / wdef["agent_dir"]
            profile = WorkerProfile(
                worker_id=wdef["worker_id"],
                agent_dir=agent_dir,
                specializations=list(wdef["specializations"]),
            )
            # Ensure the agent directory structure exists
            for q in (profile.pending_queue, profile.done_queue, profile.failed_queue):
                q.mkdir(parents=True, exist_ok=True)
            self.workers[profile.worker_id] = profile

    # ────────────────────────────────────────────────────────────────────
    # Public API: Dispatch
    # ────────────────────────────────────────────────────────────────────

    def dispatch(
        self,
        description: str,
        priority: str = "medium",
        assigned_to: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Full dispatch pipeline for a new task.

        Steps:
          1. Query mem0 for relevant past experience
          2. Classify task via Hermes (domain + complexity)
          3. Check skill registry for fast-path match
          4. Select worker based on availability + ability
          5. Create ``.task.md`` in worker's pending queue
          6. Record routing decision

        Returns:
            ``dict`` with keys: ``task_id``, ``assigned_worker``,
            ``hermes_decision``, ``skill_match``, ``status``.
        """
        task_id = self._generate_task_id()

        # 1. Memory recall
        memories = self._query_memory(description)

        # 2. Hermes classification
        hermes_decision = self._route_via_hermes(task_id, description, context)

        # 3. Skill registry check
        skill_match = self._check_skill_registry(description, hermes_decision)

        # 4. Worker selection
        worker = self._select_worker(
            description=description,
            domain=hermes_decision.domain,
            assigned_to=assigned_to,
        )

        # 5. Create .task.md file
        task_file = self._create_task_file(
            task_id=task_id,
            description=description,
            priority=priority,
            assigned_to=worker.worker_id,
            hermes_decision=hermes_decision,
            skill_match=skill_match,
            memories=memories,
            context=context,
        )

        # 6. Track the task
        self._task_index[task_id] = {
            "task_id": task_id,
            "assigned_worker": worker.worker_id,
            "task_file": str(task_file),
            "hermes_decision": hermes_decision,
            "skill_match": skill_match,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "priority": priority,
        }

        logger.info(
            "Dispatched %s → %s [%s/%s] score=%.2f",
            task_id, worker.worker_id,
            hermes_decision.domain.value, hermes_decision.complexity.value,
            hermes_decision.score,
        )

        return {
            "task_id": task_id,
            "assigned_worker": worker.worker_id,
            "hermes_decision": {
                "domain": hermes_decision.domain.value,
                "complexity": hermes_decision.complexity.value,
                "selected_model": hermes_decision.selected_model,
                "score": hermes_decision.score,
                "reason": hermes_decision.reason,
                "matched_skill": hermes_decision.matched_skill,
            },
            "skill_match": skill_match,
            "status": "pending",
            "memories_found": len(memories),
            "task_file": str(task_file),
        }

    def dispatch_with_skill(
        self,
        skill_id: str,
        params: Dict[str, Any],
        description: str = "",
    ) -> Dict[str, Any]:
        """Dispatch a task that should use a specific platform skill.

        If the skill registry is available, the skill is invoked directly.
        Otherwise, the task is dispatched as a normal task with the skill
        ID noted in metadata.

        Parameters:
            skill_id:     Identifier of the platform skill to use.
            params:       Parameters to pass to the skill.
            description:  Optional human-readable description of the task.

        Returns:
            Same shape as :meth:`dispatch`.
        """
        description = description or f"Execute skill: {skill_id}"
        result = self.dispatch(
            description=description,
            priority="high",
            context={"skill_id": skill_id, "skill_params": params},
        )
        result["skill_match"] = skill_id
        result["dispatch_mode"] = "skill-driven"
        return result

    # ────────────────────────────────────────────────────────────────────
    # Public API: Status & Collection
    # ────────────────────────────────────────────────────────────────────

    def check_status(self, task_id: str) -> Dict[str, Any]:
        """Check the status of a dispatched task across all worker queues.

        Looks for the task file in pending, done, and failed directories
        of all workers.  Returns the current status or ``"unknown"``.

        Returns:
            ``dict`` with ``task_id``, ``status``, ``worker``, and
            optional ``task_file`` path.
        """
        # Check in-memory index first — but verify the file still exists
        # at the indexed path (it may have been moved to done/failed by a worker).
        if task_id in self._task_index:
            entry = self._task_index[task_id]
            indexed_path = entry.get("task_file", "")
            if indexed_path and Path(indexed_path).exists():
                file_status = self._scan_task_file_status(indexed_path)
                if file_status != "unknown":
                    entry["status"] = file_status
                    return entry

        # Scan all workers for the task file in any queue
        for worker in self.workers.values():
            status = self._find_task_in_worker(task_id, worker)
            if status != "unknown":
                # Update the index with the actual location
                if task_id in self._task_index:
                    self._task_index[task_id]["status"] = status
                return {
                    "task_id": task_id,
                    "status": status,
                    "worker": worker.worker_id,
                }

        return {"task_id": task_id, "status": "unknown"}

    def collect_results(self, since: Optional[str] = None) -> List[Dict[str, Any]]:
        """Collect all completed task results from worker done queues.

        Parameters:
            since:  ISO timestamp string.  Only results completed after
                    this time are returned.  If *None*, all results are
                    returned.

        Returns:
            List of result dicts, each containing ``task_id``, ``worker``,
            ``task_file``, and the parsed task content.
        """
        results: List[Dict[str, Any]] = []
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Invalid 'since' timestamp: %s", since)

        for worker in self.workers.values():
            for task_file in sorted(worker.done_queue.glob("*.task.md")):
                parsed = self._parse_task_file(task_file)
                if not parsed:
                    continue

                # Filter by timestamp if requested
                if since_dt:
                    created_str = parsed.get("created", "")
                    if created_str:
                        try:
                            created_dt = datetime.fromisoformat(
                                created_str.replace("Z", "+00:00")
                            )
                            if created_dt < since_dt:
                                continue
                        except ValueError:
                            pass

                results.append({
                    "task_id": parsed.get("id", task_file.stem),
                    "worker": worker.worker_id,
                    "task_file": str(task_file),
                    "title": parsed.get("title", ""),
                    "status": parsed.get("status", "completed"),
                    "priority": parsed.get("priority", "unknown"),
                })

        return results

    def get_team_status(self) -> Dict[str, Any]:
        """Return full team status: workers, queues, hermes stats, mem0 stats.

        Returns:
            Comprehensive status dict with nested worker info, Hermes
            statistics, and memory adapter status.
        """
        worker_status = {}
        for wid, profile in self.workers.items():
            pending = self._count_files(profile.pending_queue, "*.task.md")
            done = self._count_files(profile.done_queue, "*.task.md")
            failed = self._count_files(profile.failed_queue, "*.task.md")
            stalled = self._find_stalled_tasks(profile)
            profile.stats["stalled"] = len(stalled)

            worker_status[wid] = {
                "available": profile.available,
                "pending": pending,
                "done": done,
                "failed": failed,
                "stalled": len(stalled),
                "trust_score": profile.trust_score,
                "specializations": profile.specializations,
                "agent_dir": str(profile.agent_dir),
            }

        return {
            "workers": worker_status,
            "hermes": self.hermes.get_stats(),
            "memory_available": self.memory is not None,
            "skill_registry_available": self.skill_registry is not None,
            "total_tasks_dispatched": len(self._task_index),
            "openclaw_base": str(self.openclaw_base),
            "project_root": str(self.project_root),
        }

    # ────────────────────────────────────────────────────────────────────
    # Public API: Outcome Recording
    # ────────────────────────────────────────────────────────────────────

    def record_outcome(
        self,
        task_id: str,
        success: bool,
        duration_ms: float,
        result_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record task outcome to both Hermes and mem0.

        Parameters:
            task_id:        The task identifier.
            success:        Whether the task completed successfully.
            duration_ms:    Execution time in milliseconds.
            result_summary: Optional human-readable result description.

        Returns:
            Confirmation dict with ``task_id``, ``hermes_recorded``,
            ``mem0_recorded``.
        """
        hermes_recorded = False
        mem0_recorded = False

        # Record to Hermes
        try:
            self.hermes.record_outcome(task_id, success, duration_ms)
            hermes_recorded = True
        except Exception as exc:
            logger.warning("Hermes outcome recording failed: %s", exc)

        # Update worker trust score
        entry = self._task_index.get(task_id)
        if entry:
            worker_id = entry.get("assigned_worker")
            if worker_id and worker_id in self.workers:
                worker = self.workers[worker_id]
                if success:
                    worker.stats["completed"] += 1
                    # Incremental trust: move 10% toward 1.0
                    worker.trust_score = worker.trust_score * 0.9 + 0.1
                else:
                    worker.stats["failed"] += 1
                    # Decremental trust: move 20% toward 0.0
                    worker.trust_score = worker.trust_score * 0.8

        # Record to mem0
        if self.memory is not None and result_summary:
            try:
                outcome_text = (
                    f"Task {task_id}: {'SUCCESS' if success else 'FAILURE'}. "
                    f"Duration: {duration_ms:.0f}ms. {result_summary}"
                )
                # Use the add method; degrade gracefully if API differs
                if hasattr(self.memory, "add"):
                    self.memory.add(outcome_text, user_id="coordinator")
                elif hasattr(self.memory, "store"):
                    self.memory.store(outcome_text, metadata={"task_id": task_id})
                mem0_recorded = True
            except Exception as exc:
                logger.warning("mem0 outcome recording failed: %s", exc)

        # Update in-memory index
        if entry:
            entry["status"] = "completed" if success else "failed"
            entry["outcome"] = {
                "success": success,
                "duration_ms": duration_ms,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }

        logger.info(
            "Outcome recorded: %s → success=%s hermes=%s mem0=%s",
            task_id, success, hermes_recorded, mem0_recorded,
        )

        return {
            "task_id": task_id,
            "success": success,
            "duration_ms": duration_ms,
            "hermes_recorded": hermes_recorded,
            "mem0_recorded": mem0_recorded,
        }

    # ────────────────────────────────────────────────────────────────────
    # Public API: Foreman Patrol
    # ────────────────────────────────────────────────────────────────────

    def run_foreman_patrol(self) -> Dict[str, Any]:
        """Execute one foreman patrol cycle.

        Checks all workers for:
          - Stalled tasks (in_progress longer than STALL_THRESHOLD)
          - Load imbalance (difference > 2 pending tasks between workers)
          - Failed task accumulation

        Returns:
            Patrol report dict with ``timestamp``, ``stalled_tasks``,
            ``load_balanced``, ``recommendations``.
        """
        timestamp = datetime.now(timezone.utc)
        stalled_tasks: List[Dict[str, str]] = []
        pending_counts: Dict[str, int] = {}
        failed_counts: Dict[str, int] = {}

        for wid, worker in self.workers.items():
            pending = self._count_files(worker.pending_queue, "*.task.md")
            failed = self._count_files(worker.failed_queue, "*.task.md")
            pending_counts[wid] = pending
            failed_counts[wid] = failed

            # Check for stalled tasks
            stalled = self._find_stalled_tasks(worker)
            for task_name in stalled:
                stalled_tasks.append({
                    "worker": wid,
                    "task_file": task_name,
                    "action": "flagged_for_reassignment",
                })

        # Load balance check
        counts = sorted(pending_counts.values())
        load_balanced = True
        if len(counts) >= 2 and (counts[-1] - counts[0]) > 2:
            load_balanced = False

        # Recommendations
        recommendations: List[str] = []
        if stalled_tasks:
            recommendations.append(
                f"{len(stalled_tasks)} stalled task(s) detected — consider reassignment"
            )
        if not load_balanced:
            busiest = max(pending_counts, key=pending_counts.get)
            lightest = min(pending_counts, key=pending_counts.get)
            recommendations.append(
                f"Load imbalance: {busiest} ({pending_counts[busiest]} pending) vs "
                f"{lightest} ({pending_counts[lightest]} pending) — rebalance recommended"
            )
        for wid, fc in failed_counts.items():
            if fc > 3:
                recommendations.append(
                    f"Worker {wid} has {fc} failed tasks — investigate"
                )

        report = {
            "timestamp": timestamp.isoformat(),
            "stalled_tasks": stalled_tasks,
            "load_balanced": load_balanced,
            "pending_counts": pending_counts,
            "failed_counts": failed_counts,
            "recommendations": recommendations,
        }

        logger.info(
            "Patrol complete: stalled=%d balanced=%s",
            len(stalled_tasks), load_balanced,
        )
        return report

    # ────────────────────────────────────────────────────────────────────
    # Public API: Worker Cycle
    # ────────────────────────────────────────────────────────────────────

    def run_worker_cycle(self, worker_id: Optional[str] = None) -> Dict[str, Any]:
        """Poll and report on pending tasks for one or all workers.

        This is a simulation/monitoring method.  Real task execution is
        handled by the ``GLM5Worker`` cron process.  This method reports
        what *would* be processed.

        Parameters:
            worker_id:  If provided, only check this worker.  Otherwise
                        check all workers.

        Returns:
            Dict with ``tasks_found``, ``workers_checked``, and per-worker
            pending task details.
        """
        targets = (
            {worker_id: self.workers[worker_id]}
            if worker_id and worker_id in self.workers
            else self.workers
        )

        total_found = 0
        worker_details: Dict[str, List[Dict[str, str]]] = {}

        for wid, worker in targets.items():
            pending_tasks: List[Dict[str, str]] = []
            for task_file in sorted(worker.pending_queue.glob("*.task.md")):
                parsed = self._parse_task_file(task_file)
                if parsed:
                    pending_tasks.append({
                        "task_id": parsed.get("id", task_file.stem),
                        "title": parsed.get("title", ""),
                        "priority": parsed.get("priority", "medium"),
                        "status": parsed.get("status", "pending"),
                    })
            total_found += len(pending_tasks)
            worker_details[wid] = pending_tasks

        return {
            "tasks_found": total_found,
            "workers_checked": list(targets.keys()),
            "workers": worker_details,
        }

    # ────────────────────────────────────────────────────────────────────
    # Public API: Cron Setup
    # ────────────────────────────────────────────────────────────────────

    def setup_cron_jobs(self) -> str:
        """Generate crontab configuration for automated patrol and worker cycles.

        Creates a cron schedule with:
          - Foreman patrol every 30 minutes
          - Worker cycle every 5 minutes

        Returns:
            The generated crontab lines as a string.
        """
        python_path = "python3"
        coordinator_module = "nexus_os.team.coordinator"
        project_src = self.project_root / "src"

        cron_lines = [
            "# Nexus OS Team Coordinator — Automated Schedules",
            f"# Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "# Foreman patrol every 30 minutes",
            f"*/30 * * * * cd {self.project_root} && PYTHONPATH={project_src} "
            f"{python_path} -m {coordinator_module} --patrol",
            "",
            "# Worker poll cycle every 5 minutes",
            f"*/5 * * * * cd {self.project_root} && PYTHONPATH={project_src} "
            f"{python_path} -m {coordinator_module} --worker-cycle",
            "",
        ]

        cron_content = "\n".join(cron_lines)
        logger.info("Cron configuration generated (%d lines)", len(cron_lines))
        return cron_content

    # ────────────────────────────────────────────────────────────────────
    # Internal: Routing & Worker Selection
    # ────────────────────────────────────────────────────────────────────

    def _route_via_hermes(
        self,
        task_id: str,
        description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RoutingDecision:
        """Route a task through the Hermes 3-layer router.

        Falls back to a basic domain classification if Hermes routing
        fails (defensive programming).
        """
        try:
            decision = self.hermes.route(task_id, description, context)
            return decision
        except Exception as exc:
            logger.warning("Hermes routing failed, using fallback: %s", exc)
            # Fallback: basic classification
            from nexus_os.engine.hermes import TaskClassifier
            classifier = TaskClassifier()
            domain, complexity = classifier.classify(description, context)
            return RoutingDecision(
                task_id=task_id,
                selected_model=DOMAIN_WORKER_MAP.get(domain.value, "glm5-worker-1"),
                complexity=complexity,
                domain=domain,
                score=0.3,
                cost_estimate=0.0,
                reason="Fallback routing (Hermes unavailable)",
            )

    def _select_worker(
        self,
        description: str,
        domain: TaskDomain,
        assigned_to: Optional[str] = None,
    ) -> WorkerProfile:
        """Select the best available worker for a task.

        Selection priority:
          1. Explicit ``assigned_to`` override
          2. Hermes-selected model mapped to worker
          3. Domain-based default mapping
          4. Least-loaded worker (load balancing)
        """
        # 1. Explicit assignment
        if assigned_to and assigned_to in self.workers:
            return self.workers[assigned_to]

        # 2. Hermes model → worker mapping
        hermes_models = self.workers.keys()
        # (already handled by Hermes routing — selected_model IS the worker)

        # 3. Domain-based mapping
        domain_worker = DOMAIN_WORKER_MAP.get(domain.value)
        if domain_worker and domain_worker in self.workers:
            return self.workers[domain_worker]

        # 4. Least-loaded worker
        return self._select_least_loaded_worker()

    def _select_least_loaded_worker(self) -> WorkerProfile:
        """Select the worker with the fewest pending tasks."""
        best_worker = None
        best_count = float("inf")
        for worker in self.workers.values():
            count = self._count_files(worker.pending_queue, "*.task.md")
            if count < best_count:
                best_count = count
                best_worker = worker
        return best_worker or list(self.workers.values())[0]

    # ────────────────────────────────────────────────────────────────────
    # Internal: Memory & Skill Queries
    # ────────────────────────────────────────────────────────────────────

    def _query_memory(self, description: str) -> List[Dict[str, Any]]:
        """Query mem0 for relevant past experience related to the description.

        Returns:
            List of memory records.  Empty list if mem0 is unavailable.
        """
        if self.memory is None:
            return []

        try:
            if hasattr(self.memory, "search"):
                results = self.memory.search(description, limit=5)
                return results if isinstance(results, list) else []
            elif hasattr(self.memory, "query"):
                results = self.memory.query(description)
                return results if isinstance(results, list) else []
            return []
        except Exception as exc:
            logger.warning("mem0 query failed: %s", exc)
            return []

    def _check_skill_registry(
        self,
        description: str,
        hermes_decision: RoutingDecision,
    ) -> Optional[str]:
        """Check the skill registry for a fast-path match.

        Returns:
            Skill ID if a match is found, ``None`` otherwise.
        """
        if self.skill_registry is None:
            return None

        try:
            if hasattr(self.skill_registry, "find_skill"):
                match = self.skill_registry.find_skill(description)
                if match:
                    return getattr(match, "skill_id", str(match))
            elif hasattr(self.skill_registry, "search"):
                results = self.skill_registry.search(description)
                if results:
                    return results[0]
            return None
        except Exception as exc:
            logger.warning("Skill registry check failed: %s", exc)
            return None

    # ────────────────────────────────────────────────────────────────────
    # Internal: Task File Operations
    # ────────────────────────────────────────────────────────────────────

    def _generate_task_id(self) -> str:
        """Generate a unique task ID in the format ``task-YYYY-MM-DD-NNN``."""
        now = datetime.now(timezone.utc)
        date_part = now.strftime("%Y-%m-%d")
        # Use a short UUID suffix for uniqueness
        suffix = uuid.uuid4().hex[:6]
        return f"task-{date_part}-{suffix}"

    def _create_task_file(
        self,
        task_id: str,
        description: str,
        priority: str,
        assigned_to: str,
        hermes_decision: RoutingDecision,
        skill_match: Optional[str],
        memories: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Create a ``.task.md`` file in the worker's pending queue.

        The file uses YAML frontmatter for metadata and Markdown for the
        task body.

        Returns:
            Path to the created task file.
        """
        worker = self.workers[assigned_to]
        task_file = worker.pending_queue / f"{task_id}.task.md"

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build frontmatter
        frontmatter_lines = [
            "---",
            f"id: {task_id}",
            f"type: {hermes_decision.domain.value}-implementation",
            f"priority: {priority}",
            f"assigned_to: {assigned_to}",
            f"status: pending",
            f"created: {timestamp}",
            f"hermes_domain: {hermes_decision.domain.value}",
            f"hermes_complexity: {hermes_decision.complexity.value}",
            f"hermes_score: {hermes_decision.score:.2f}",
            f"skill_match: {skill_match or 'null'}",
            f"dependencies: {context.get('dependencies', '') if context else ''}",
            "---",
        ]

        # Build body
        body_lines = [
            "",
            f"# {description.split('.')[0] if description else task_id}",
            "",
            description,
        ]

        # Append relevant memories as context
        if memories:
            body_lines.append("")
            body_lines.append("## Relevant Past Experience")
            body_lines.append("")
            for i, mem in enumerate(memories[:5], 1):
                mem_text = str(mem.get("content", mem.get("text", mem)))[:300]
                body_lines.append(f"{i}. {mem_text}")
                body_lines.append("")

        content = "\n".join(frontmatter_lines) + "\n".join(body_lines) + "\n"
        task_file.write_text(content)

        return task_file

    def _parse_task_file(self, filepath: Path) -> Optional[Dict[str, str]]:
        """Parse a ``.task.md`` file's frontmatter and extract title.

        Returns:
            Dict with parsed frontmatter fields and ``title`` from the
            first H1 heading.  Returns *None* if the file cannot be read.
        """
        try:
            text = filepath.read_text()
        except Exception:
            return None

        frontmatter: Dict[str, str] = {}
        match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if match:
            inner = match.group(1).strip()
            for line in inner.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, val = line.split(":", 1)
                    frontmatter[key.strip()] = val.strip()
            body = text[match.end():].strip()
        else:
            body = text

        # Extract title from first H1 heading
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else frontmatter.get("id", filepath.stem)

        return {
            "id": frontmatter.get("id", filepath.stem),
            "title": title,
            "type": frontmatter.get("type", ""),
            "priority": frontmatter.get("priority", "medium"),
            "assigned_to": frontmatter.get("assigned_to", ""),
            "created": frontmatter.get("created", ""),
            "status": frontmatter.get("status", "pending"),
            "hermes_domain": frontmatter.get("hermes_domain", ""),
            "hermes_complexity": frontmatter.get("hermes_complexity", ""),
            "hermes_score": frontmatter.get("hermes_score", ""),
            "skill_match": frontmatter.get("skill_match", ""),
            "dependencies": frontmatter.get("dependencies", ""),
        }

    def _scan_task_file_status(self, task_file_path: str) -> str:
        """Determine status by checking which queue a task file resides in.

        Returns:
            One of ``"pending"``, ``"completed"``, ``"failed"``, or
            ``"unknown"``.
        """
        if not task_file_path:
            return "unknown"
        path = Path(task_file_path)
        if "pending" in path.parts:
            return "pending"
        if "done" in path.parts:
            return "completed"
        if "failed" in path.parts:
            return "failed"
        return "unknown"

    def _find_task_in_worker(self, task_id: str, worker: WorkerProfile) -> str:
        """Search for a task file in a worker's queues.

        Returns:
            ``"pending"``, ``"completed"``, ``"failed"``, or ``"unknown"``.
        """
        filename = f"{task_id}.task.md"

        if (worker.pending_queue / filename).exists():
            return "pending"
        if (worker.done_queue / filename).exists():
            return "completed"
        if (worker.failed_queue / filename).exists():
            return "failed"
        return "unknown"

    # ────────────────────────────────────────────────────────────────────
    # Internal: Stalled Task Detection
    # ────────────────────────────────────────────────────────────────────

    def _find_stalled_tasks(self, worker: WorkerProfile) -> List[str]:
        """Find tasks that have been in_progress longer than STALL_THRESHOLD.

        Returns:
            List of task filenames that appear stalled.
        """
        stalled: List[str] = []
        now = datetime.now(timezone.utc)

        for task_file in worker.pending_queue.glob("*.task.md"):
            parsed = self._parse_task_file(task_file)
            if not parsed or parsed.get("status") != "in_progress":
                continue

            created_str = parsed.get("created", "")
            if not created_str:
                continue

            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                if now - created_dt > STALL_THRESHOLD:
                    stalled.append(task_file.name)
            except ValueError:
                pass

        return stalled

    # ────────────────────────────────────────────────────────────────────
    # Internal: Utilities
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _count_files(directory: Path, pattern: str) -> int:
        """Count files matching a glob pattern in a directory."""
        if not directory.exists():
            return 0
        return len(list(directory.glob(pattern)))


# ── CLI entry point for cron ───────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Minimal CLI for cron invocation
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    mode = sys.argv[2] if len(sys.argv) > 2 else "--patrol"

    coordinator = TeamCoordinator(project_root=project)

    if mode == "--patrol":
        report = coordinator.run_foreman_patrol()
        print(f"[COORDINATOR] Patrol: {report['stalled_tasks'].__len__()} stalled")
    elif mode == "--worker-cycle":
        cycle = coordinator.run_worker_cycle()
        print(f"[COORDINATOR] Cycle: {cycle['tasks_found']} pending")
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
