"""
engine/executor.py — Real Task Executor v2

Replaces the time.sleep(0.1) simulation with a pluggable execution
backend. Supports:
  - SyncCallbackExecutor: Calls a Python callable (for in-process agents)
  - AsyncBridgeExecutor: Sends execution request through the Bridge (A2A)
  - MockExecutor: Original simulation (for testing only)

The executor integrates with TrustScorer to record success/failure
after each task execution.
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, Future

from nexus_os.db.manager import DatabaseManager
from nexus_os.engine.router import EngineRouter, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a single task execution."""
    task_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    agent_id: Optional[str] = None


class ExecutorBackend(ABC):
    """
    Pluggable execution backend.
    Implement this to route task execution to different agent types.
    """

    @abstractmethod
    def execute(self, task_id: str, description: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a task and return the result."""
        ...


class SyncCallbackExecutor(ExecutorBackend):
    """
    Executes tasks by calling a registered Python callable.
    Useful for in-process agent simulation or local tool execution.

    Usage:
        executor = SyncCallbackExecutor()
        executor.register_handler("code_review", my_review_function)
    """

    def __init__(self, default_timeout: float = 30.0):
        self._handlers: Dict[str, Callable[[str, Dict], Any]] = {}
        self.default_timeout = default_timeout

    def register_handler(self, task_type: str, handler: Callable[[str, Dict], Any]):
        """Register a callable for a specific task type."""
        self._handlers[task_type] = handler

    def execute(self, task_id: str, description: str, context: Dict[str, Any]) -> ExecutionResult:
        task_type = context.get("type", "default")
        handler = self._handlers.get(task_type)
        if handler is None:
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error=f"No handler registered for task type: {task_type}",
            )
        start = time.perf_counter()
        try:
            output = handler(description, context)
            duration = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                task_id=task_id,
                success=True,
                output=str(output) if output else None,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error=str(e),
                duration_ms=duration,
            )


class AsyncBridgeExecutor(ExecutorBackend):
    """
    Sends task execution requests through the Nexus Bridge to remote agents.
    This is the production executor for Milestone 4+.
    """

    def __init__(self, bridge_url: str = "http://127.0.0.1:8000", timeout: float = 30.0):
        self.bridge_url = bridge_url
        self.timeout = timeout

    def execute(self, task_id: str, description: str, context: Dict[str, Any]) -> ExecutionResult:
        agent_id = context.get("agent_id")
        if not agent_id:
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error="No agent_id in task context for bridge execution",
            )
        # TODO: Implement actual Bridge RPC call
        # For now, return a structured not-implemented result
        return ExecutionResult(
            task_id=task_id,
            success=False,
            error=f"BridgeExecutor not yet wired to Bridge at {self.bridge_url}",
            agent_id=agent_id,
        )


class MockExecutor(ExecutorBackend):
    """
    Simulation executor for testing.
    Every task completes after a configurable delay with configurable outcomes.
    """

    def __init__(self, delay: float = 0.01, failure_rate: float = 0.0):
        self.delay = delay
        self.failure_rate = failure_rate
        self._call_count = 0

    def execute(self, task_id: str, description: str, context: Dict[str, Any]) -> ExecutionResult:
        import random
        self._call_count += 1
        if self.delay > 0:
            time.sleep(self.delay)
        if random.random() < self.failure_rate:
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error="Mock failure (simulated)",
                duration_ms=self.delay * 1000,
            )
        return ExecutionResult(
            task_id=task_id,
            success=True,
            output=f"Mock execution #{self._call_count}: {description}",
            duration_ms=self.delay * 1000,
        )


class TaskExecutor:
    """
    Orchestrates task execution using a pluggable backend.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        backend: Optional[ExecutorBackend] = None,
        trust_scorer=None,
        max_workers: int = 4,
    ):
        self.db = db_manager
        self.backend = backend or MockExecutor()
        self.trust_scorer = trust_scorer
        self.router = EngineRouter(db_manager)
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._active_futures: Dict[str, Future] = {}

    def set_backend(self, backend: ExecutorBackend):
        """Swap the execution backend at runtime."""
        self.backend = backend

    def execute_next_batch(self, project_id: str) -> List[ExecutionResult]:
        """Execute all ready tasks for a project."""
        ready = self.router.get_ready_tasks(project_id)
        results = []
        for task in ready:
            task_id = task["task_id"]
            description = task.get("description", "")
            context = task.get("context", {})
            self._update_status(task_id, TaskStatus.IN_PROGRESS)
            result = self._execute_single(task_id, description, context)
            results.append(result)
        return results

    def execute_async(self, project_id: str) -> Dict[str, Future]:
        """Submit all ready tasks to the thread pool for parallel execution."""
        ready = self.router.get_ready_tasks(project_id)
        futures = {}
        for task in ready:
            task_id = task["task_id"]
            description = task.get("description", "")
            context = task.get("context", {})
            self._update_status(task_id, TaskStatus.IN_PROGRESS)
            future = self._thread_pool.submit(
                self._execute_single, task_id, description, context
            )
            self._active_futures[task_id] = future
            futures[task_id] = future
        return futures

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Optional[ExecutionResult]:
        future = self._active_futures.get(task_id)
        if future is None:
            return None
        try:
            result = future.result(timeout=timeout)
            del self._active_futures[task_id]
            return result
        except Exception as e:
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error=f"Execution failed: {e}",
            )

    def _execute_single(
        self, task_id: str, description: str, context: Dict[str, Any]
    ) -> ExecutionResult:
        try:
            result = self.backend.execute(task_id, description, context)
            if result.success:
                self._update_status(task_id, TaskStatus.COMPLETED)
                if self.trust_scorer and result.agent_id:
                    self.trust_scorer.record_success(result.agent_id)
            else:
                self._update_status(task_id, TaskStatus.FAILED)
                if self.trust_scorer and result.agent_id:
                    self.trust_scorer.record_failure(result.agent_id)
            logger.info(
                "Task %s: %s (%.1fms)",
                task_id, "OK" if result.success else f"FAIL: {result.error}",
                result.duration_ms,
            )
            return result
        except Exception as e:
            self._update_status(task_id, TaskStatus.FAILED)
            logger.error("Task %s crashed: %s", task_id, e)
            return ExecutionResult(
                task_id=task_id,
                success=False,
                error=f"Executor crash: {e}",
            )

    def _update_status(self, task_id: str, status: TaskStatus):
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE tasks SET status = ?, heartbeat = ? WHERE task_id = ?",
            (status.value, time.time(), task_id),
        )
        conn.commit()

    def shutdown(self, wait: bool = True):
        self._thread_pool.shutdown(wait=wait)
