"""
observability/tracing.py — Trace-ID Context Propagation (HPv2)

Provides thread-local trace ID management for distributed audit linking.
Each thread can have its own trace ID set, which propagates through the
system for correlation across governor/base.py audit_log entries and
bridge/server.py request headers.

Lightweight — no external dependencies. Uses stdlib threading.local()
and uuid4 for ID generation.

Usage:
    from nexus_os.observability.tracing import trace_context

    # Set a trace ID for the current thread
    trace_context.set_trace_id("trace-abc123def4567890")

    # Retrieve it later in the call stack
    tid = trace_context.get_trace_id()

    # Use as a context manager for automatic cleanup
    with trace_context.with_trace_id("trace-abc123def4567890"):
        # ... work ...
        pass  # trace ID automatically cleared
"""

import threading
import uuid
from typing import Optional
from contextlib import contextmanager

_logger_lock = threading.Lock()


class TraceContext:
    """
    Thread-local trace ID context manager.

    Stores trace IDs in threading.local() so each thread maintains
    its own independent trace context. This allows trace propagation
    through async/concurrent workloads without interference.
    """

    def __init__(self):
        self._local = threading.local()

    def set_trace_id(self, trace_id: str) -> None:
        """
        Set the trace ID for the current thread.

        Args:
            trace_id: Trace identifier string (typically "trace-{uuid4_hex[:16]}")
        """
        self._local.trace_id = trace_id

    def get_trace_id(self) -> Optional[str]:
        """
        Get the trace ID for the current thread.

        Returns:
            Current trace ID string, or None if not set.
        """
        return getattr(self._local, "trace_id", None)

    def clear_trace_id(self) -> None:
        """Clear the trace ID for the current thread."""
        self._local.trace_id = None

    @staticmethod
    def generate_trace_id() -> str:
        """
        Generate a new trace ID.

        Format: "trace-{uuid4_hex[:16]}" — 16 hex characters provide
        64 bits of entropy, sufficient for audit linking without being
        excessively long for headers and log lines.

        Returns:
            New trace ID string
        """
        return f"trace-{uuid.uuid4().hex[:16]}"

    @contextmanager
    def with_trace_id(self, trace_id: str):
        """
        Context manager that sets a trace ID and clears it on exit.

        Args:
            trace_id: Trace identifier to use within the context

        Yields:
            None

        Example:
            with trace_context.with_trace_id("trace-abc123"):
                do_work()  # trace_context.get_trace_id() returns "trace-abc123"
            # trace ID is now None
        """
        self.set_trace_id(trace_id)
        try:
            yield
        finally:
            self.clear_trace_id()


# Module-level singleton for convenience
trace_context = TraceContext()
