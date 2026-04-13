"""
tests/observability/test_tracing.py — Trace-ID Context Propagation Tests (HPv2)

5 tests across 2 classes:
  TestTraceGeneration: ID format validation, uniqueness
  TestTraceContext: Set/get, clear, context manager
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.observability.tracing import TraceContext


@pytest.fixture
def ctx():
    """Fresh TraceContext for each test."""
    return TraceContext()


class TestTraceGeneration:
    """Tests for trace ID generation."""

    def test_generate_trace_id_format(self):
        """Generated trace IDs should match the format 'trace-{16 hex chars}'."""
        for _ in range(20):
            tid = TraceContext.generate_trace_id()
            assert tid.startswith("trace-"), f"Trace ID should start with 'trace-', got: {tid}"
            hex_part = tid[6:]  # After "trace-"
            assert len(hex_part) == 16, f"Hex part should be 16 chars, got {len(hex_part)}: {tid}"
            assert all(c in "0123456789abcdef" for c in hex_part), f"Hex part should be lowercase hex: {tid}"

    def test_generate_unique_ids(self):
        """Each generated trace ID should be unique."""
        ids = {TraceContext.generate_trace_id() for _ in range(1000)}
        assert len(ids) == 1000, "All 1000 generated IDs should be unique"


class TestTraceContext:
    """Tests for thread-local trace context management."""

    def test_set_and_get(self, ctx):
        """set_trace_id and get_trace_id should round-trip correctly."""
        assert ctx.get_trace_id() is None, "Initial trace ID should be None"

        ctx.set_trace_id("trace-abc123def4567890")
        assert ctx.get_trace_id() == "trace-abc123def4567890"

        ctx.set_trace_id("trace-different0000000")
        assert ctx.get_trace_id() == "trace-different0000000"

    def test_clear(self, ctx):
        """clear_trace_id should remove the current trace ID."""
        ctx.set_trace_id("trace-tobecleared00")
        assert ctx.get_trace_id() == "trace-tobecleared00"

        ctx.clear_trace_id()
        assert ctx.get_trace_id() is None

    def test_context_manager(self, ctx):
        """with_trace_id should set the ID inside the block and clear it after."""
        assert ctx.get_trace_id() is None

        with ctx.with_trace_id("trace-contexttest000"):
            assert ctx.get_trace_id() == "trace-contexttest000"
            # Verify it's still set inside nested scope
            inner = ctx.get_trace_id()
            assert inner == "trace-contexttest000"

        # After exiting the context, trace ID should be cleared
        assert ctx.get_trace_id() is None
