"""
tests/bridge/test_sdk.py — Nexus Bridge Client SDK Tests

Tests circuit breaker, retry policy, signature generation, and client API.
"""

import pytest
import os
import sys
import json
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.bridge.sdk import (
    NexusClient, CircuitBreaker, CircuitState,
    RetryPolicy, generate_signature, verify_signature,
    BridgeResponse,
)


class TestSignatureGeneration:
    def test_roundtrip(self):
        sig = generate_signature("secret", "trace-123", "payload")
        assert verify_signature("secret", "trace-123", "payload", sig) is True

    def test_wrong_secret(self):
        sig = generate_signature("correct", "trace", "data")
        assert verify_signature("wrong", "trace", "data", sig) is False

    def test_deterministic(self):
        s1 = generate_signature("key", "trace", "body")
        s2 = generate_signature("key", "trace", "body")
        assert s1 == s2

    def test_hex_length(self):
        sig = generate_signature("k", "t", "p")
        assert len(sig) == 64


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_transitions_to_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.record_failure()  # Fail in half-open
        assert cb.state == CircuitState.OPEN

    def test_stats(self):
        cb = CircuitBreaker()
        stats = cb.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0


class TestRetryPolicy:
    def test_delay_calculation(self):
        policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
        assert policy.get_delay(0) == 1.0
        assert policy.get_delay(1) == 2.0
        assert policy.get_delay(2) == 4.0
        assert policy.get_delay(10) == 30.0  # Capped at max_delay

    def test_should_retry_http_error(self):
        from urllib.error import HTTPError
        policy = RetryPolicy()
        err = HTTPError(None, 503, "Service Unavailable", {}, None)
        assert policy.should_retry(err) is True

    def test_should_not_retry_4xx(self):
        from urllib.error import HTTPError
        policy = RetryPolicy()
        err = HTTPError(None, 404, "Not Found", {}, None)
        assert policy.should_retry(err) is False

    def test_should_retry_connection_error(self):
        policy = RetryPolicy()
        assert policy.should_retry(ConnectionError("timeout")) is True

    def test_should_not_retry_generic(self):
        policy = RetryPolicy()
        assert policy.should_retry(ValueError("bad input")) is False


class TestNexusClient:
    def test_build_headers(self):
        client = NexusClient(
            bridge_url="http://localhost:8000",
            agent_id="test-agent",
            secret="test-secret",
        )
        headers = client._build_headers("proj-1", "trace-abc", '{"test": true}')
        assert headers["X-Nexus-Project-ID"] == "proj-1"
        assert headers["X-Nexus-Agent-ID"] == "test-agent"
        assert headers["X-Nexus-Trace-ID"] == "trace-abc"
        assert headers["X-Nexus-Signature"] is not None
        assert len(headers["X-Nexus-Signature"]) == 64

    def test_lineage_header_optional(self):
        client = NexusClient("http://localhost:8000", "a1", "s1")
        headers = client._build_headers("p1", "t1", "{}", lineage_id="parent-trace")
        assert headers["X-Nexus-Lineage-ID"] == "parent-trace"

    def test_no_lineage_by_default(self):
        client = NexusClient("http://localhost:8000", "a1", "s1")
        headers = client._build_headers("p1", "t1", "{}")
        assert "X-Nexus-Lineage-ID" not in headers

    def test_circuit_breaker_integration():
        breaker = CircuitBreaker(failure_threshold=1)
        assert breaker.state == CircuitState.CLOSED
        breaker.record_failure()
        import time
        for _ in range(10):
            if breaker.state == CircuitState.OPEN:
                break
            time.sleep(0.01)
        assert breaker.state == CircuitState.OPEN
    def test_stats(self):
        client = NexusClient("http://localhost:8000", "a1", "s1")
        breaker = CircuitBreaker()
        client.set_circuit_breaker(breaker)
        stats = client.get_stats()
        assert stats["agent_id"] == "a1"
        assert stats["bridge_url"] == "http://localhost:8000"
        assert stats["total_requests"] == 0
        assert "circuit_breaker" in stats

    def test_trace_id_unique(self):
        client = NexusClient("http://localhost:8000", "a1", "s1")
        ids = set()
        for _ in range(10):
            tid = client._generate_trace_id()
            ids.add(tid)
        assert len(ids) == 10  # All unique

    def test_bridge_url_trailing_slash(self):
        client = NexusClient("http://localhost:8000/", "a1", "s1")
        assert client.bridge_url == "http://localhost:8000"


