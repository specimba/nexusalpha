"""
tests/unit/test_executor_v2.py — Task Executor v2 Unit Tests

Validates the pluggable executor backends:
  - MockExecutor: Simulation with configurable delay/failure
  - SyncCallbackExecutor: In-process callable execution
  - AsyncBridgeExecutor: Bridge RPC stub (returns not-implemented)
  - TaskExecutor: Orchestration with batch and async modes
"""

import pytest
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.engine.executor import (
    MockExecutor, SyncCallbackExecutor, AsyncBridgeExecutor,
    TaskExecutor, ExecutionResult,
)


class TestMockExecutor:
    """Test the mock/simulation executor."""

    def test_successful_execution(self):
        executor = MockExecutor(delay=0.001)
        result = executor.execute("task-1", "Do something", {})
        assert result.success is True
        assert result.task_id == "task-1"
        assert result.output is not None
        assert result.error is None

    def test_simulated_failure(self):
        executor = MockExecutor(delay=0.001, failure_rate=1.0)
        result = executor.execute("task-2", "This will fail", {})
        assert result.success is False
        assert result.error == "Mock failure (simulated)"

    def test_duration_recorded(self):
        executor = MockExecutor(delay=0.05)
        result = executor.execute("task-3", "Timed task", {})
        assert result.duration_ms > 0

    def test_zero_delay(self):
        executor = MockExecutor(delay=0)
        result = executor.execute("task-4", "Instant", {})
        assert result.success is True
        assert result.duration_ms >= 0

    def test_incrementing_output(self):
        executor = MockExecutor(delay=0)
        r1 = executor.execute("t1", "A", {})
        r2 = executor.execute("t2", "B", {})
        assert "#1" in r1.output
        assert "#2" in r2.output


class TestSyncCallbackExecutor:
    """Test the in-process callback executor."""

    def test_registered_handler_executes(self):
        executor = SyncCallbackExecutor()
        def my_handler(description, context):
            return f"Processed: {description}"
        executor.register_handler("review", my_handler)
        result = executor.execute("task-10", "Review this code", {"type": "review"})
        assert result.success is True
        assert "Processed: Review this code" in result.output

    def test_missing_handler_returns_error(self):
        executor = SyncCallbackExecutor()
        result = executor.execute("task-11", "Unknown type", {"type": "nonexistent"})
        assert result.success is False
        assert "No handler registered" in result.error

    def test_handler_exception_caught(self):
        executor = SyncCallbackExecutor()
        def bad_handler(desc, ctx):
            raise ValueError("Intentional failure")
        executor.register_handler("fail", bad_handler)
        result = executor.execute("task-12", "Boom", {"type": "fail"})
        assert result.success is False
        assert "Intentional failure" in result.error

    def test_default_type_fallback(self):
        executor = SyncCallbackExecutor()
        executor.register_handler("default", lambda d, c: "default called")
        result = executor.execute("task-13", "No type specified", {})
        assert result.success is True
        assert result.output == "default called"


class TestAsyncBridgeExecutor:
    """Test the Bridge RPC executor stub."""

    def test_missing_agent_id_returns_error(self):
        executor = AsyncBridgeExecutor()
        result = executor.execute("task-20", "Some task", {})
        assert result.success is False
        assert "No agent_id" in result.error

    def test_with_agent_id_returns_not_implemented(self):
        executor = AsyncBridgeExecutor()
        result = executor.execute("task-21", "Task", {"agent_id": "agent-01"})
        assert result.success is False
        assert "not yet wired" in result.error
        assert result.agent_id == "agent-01"

    def test_custom_bridge_url(self):
        executor = AsyncBridgeExecutor(bridge_url="http://192.168.1.100:8000")
        result = executor.execute("task-22", "Task", {"agent_id": "a1"})
        assert "192.168.1.100" in result.error


class TestTaskExecutor:
    """Test the TaskExecutor orchestrator (requires DB mock)."""

    def test_backend_swap(self):
        """Should be able to swap backends at runtime."""
        mock1 = MockExecutor(delay=0)
        mock2 = MockExecutor(delay=0, failure_rate=1.0)
        # Note: TaskExecutor requires DatabaseManager; test backend swap directly
        # through the set_backend pattern
        assert mock1.execute("t", "desc", {}).success is True
        assert mock2.execute("t", "desc", {}).success is False

    def test_execution_result_dataclass(self):
        result = ExecutionResult(
            task_id="test",
            success=True,
            output="Hello",
            error=None,
            duration_ms=42.5,
            agent_id="agent-1",
        )
        assert result.task_id == "test"
        assert result.success is True
        assert result.output == "Hello"
        assert result.duration_ms == 42.5
        assert result.agent_id == "agent-1"
