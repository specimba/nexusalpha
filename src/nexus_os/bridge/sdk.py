"""
bridge/sdk.py — Nexus OS Bridge Client SDK

Client library for communicating with the Nexus Bridge server.
Implements:
  - Retry logic with exponential backoff
  - Circuit breaker for fault tolerance
  - Request signing via HMAC-SHA256
  - Protocol header management (X-Nexus-* headers)
  - Async support via aiohttp (optional)

Usage:
    from nexus_os.bridge.sdk import NexusClient, CircuitBreaker

    client = NexusClient(
        bridge_url="http://127.0.0.1:8000",
        agent_id="reviewer-01",
        secret="your_agent_secret",
    )

    # Simple request
    response = client.submit_task(
        project_id="proj-001",
        description="Review the authentication module",
        context={"type": "code_review"},
    )

    # With retry and circuit breaker
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
    client.set_circuit_breaker(breaker)
"""

import time
import json
import hashlib
import hmac
import logging
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)


# ── Signature Helpers ───────────────────────────────────────────

def generate_signature(secret: str, trace_id: str, payload: str) -> str:
    """Generate HMAC-SHA256 signature for Bridge requests."""
    message = f"{secret}:{trace_id}:{payload}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(secret: str, trace_id: str, payload: str, provided: str) -> bool:
    """Verify a Bridge request signature using constant-time comparison."""
    expected = generate_signature(secret, trace_id, payload)
    return hmac.compare_digest(expected, provided)


# ── Circuit Breaker ─────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing — reject all requests
    HALF_OPEN = "half_open" # Testing — allow one request through


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.

    States:
      CLOSED:   Normal operation. Track failures. Open if threshold exceeded.
      OPEN:     All requests rejected immediately. Wait for recovery_timeout.
      HALF_OPEN: Allow one request. If it succeeds → CLOSED. If it fails → OPEN.
    """
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_count: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_count = 0
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state  # Triggers state transition check
        with self._lock:
            if state == CircuitState.CLOSED:
                return True
            if state == CircuitState.HALF_OPEN:
                if self._half_open_count < self.half_open_max:
                    self._half_open_count += 1
                    return True
                return False
            return False  # OPEN

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN

    def get_stats(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ── Retry Policy ────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """Exponential backoff retry policy."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retryable_status_codes: List[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for the given retry attempt (0-indexed)."""
        delay = self.base_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)

    def should_retry(self, error: Exception) -> bool:
        """Determine if an error is retryable."""
        if isinstance(error, HTTPError):
            return error.code in self.retryable_status_codes
        if isinstance(error, URLError):
            return True  # Network errors are always retryable
        if isinstance(error, (ConnectionError, TimeoutError)):
            return True
        return False


# ── Nexus Client ────────────────────────────────────────────────

@dataclass
class BridgeResponse:
    """Response from a Bridge request."""
    status_code: int
    body: Dict[str, Any]
    headers: Dict[str, str]
    trace_id: Optional[str] = None
    duration_ms: float = 0.0
    retries_used: int = 0


class NexusClient:
    """
    Client SDK for the Nexus OS Bridge.

    Features:
      - Automatic HMAC-SHA256 request signing
      - Protocol header injection (X-Nexus-* headers)
      - Exponential backoff retry
      - Circuit breaker integration
      - Structured response parsing
    """

    def __init__(
        self,
        bridge_url: str,
        agent_id: str,
        secret: str,
        timeout: float = 30.0,
        retry_policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.bridge_url = bridge_url.rstrip("/")
        self.agent_id = agent_id
        self.secret = secret
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self._circuit_breaker = circuit_breaker
        self._request_count = 0
        self._trace_counter = 0

    def set_circuit_breaker(self, breaker: CircuitBreaker):
        self._circuit_breaker = breaker

    def _generate_trace_id(self) -> str:
        """Generate a unique trace ID for this request."""
        self._trace_counter += 1
        raw = f"{self.agent_id}-{self._trace_counter}-{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _build_headers(
        self,
        project_id: str,
        trace_id: str,
        payload: str,
        lineage_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build the full Nexus protocol headers."""
        signature = generate_signature(self.secret, trace_id, payload)
        headers = {
            "Content-Type": "application/json",
            "X-Nexus-Project-ID": project_id,
            "X-Nexus-Agent-ID": self.agent_id,
            "X-Nexus-Trace-ID": trace_id,
            "X-Nexus-Signature": signature,
        }
        if lineage_id:
            headers["X-Nexus-Lineage-ID"] = lineage_id
        return headers

    def _execute_request(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> BridgeResponse:
        """Execute a single HTTP request to the Bridge."""
        url = f"{self.bridge_url}{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        trace_id = headers.get("X-Nexus-Trace-ID", "unknown")

        start = time.perf_counter()
        try:
            req = Request(url, data=body, headers=headers, method="POST")
            with urlopen(req, timeout=self.timeout) as resp:
                duration = (time.perf_counter() - start) * 1000
                resp_body = json.loads(resp.read().decode("utf-8"))
                return BridgeResponse(
                    status_code=resp.status,
                    body=resp_body,
                    headers=dict(resp.headers),
                    trace_id=trace_id,
                    duration_ms=duration,
                )
        except HTTPError as e:
            duration = (time.perf_counter() - start) * 1000
            resp_body = {}
            try:
                resp_body = json.loads(e.read().decode("utf-8"))
            except Exception:
                resp_body = {"error": str(e)}
            return BridgeResponse(
                status_code=e.code,
                body=resp_body,
                headers={},
                trace_id=trace_id,
                duration_ms=duration,
            )

    def _request_with_retry(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> BridgeResponse:
        """Execute request with retry and circuit breaker logic."""
        # Check circuit breaker
        if self._circuit_breaker and not self._circuit_breaker.allow_request():
            return BridgeResponse(
                status_code=503,
                body={"error": "Circuit breaker is OPEN", "circuit": self._circuit_breaker.get_stats()},
                headers={},
                trace_id=headers.get("X-Nexus-Trace-ID"),
            )

        last_error = None
        retries = 0

        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                response = self._execute_request(endpoint, payload, headers)

                # Check if response is retryable
                if response.status_code in self.retry_policy.retryable_status_codes:
                    last_error = HTTPError(
                        None, response.status_code,
                        response.body.get("error", "Server error"),
                        {}, None
                    )
                else:
                    # Success or non-retryable error
                    if self._circuit_breaker:
                        if response.status_code < 500:
                            self._circuit_breaker.record_success()
                        elif response.status_code >= 500:
                            self._circuit_breaker.record_failure()
                    response.retries_used = retries
                    return response

            except (URLError, ConnectionError, TimeoutError) as e:
                last_error = e
                response = BridgeResponse(
                    status_code=0,
                    body={"error": str(e)},
                    headers={},
                    trace_id=headers.get("X-Nexus-Trace-ID"),
                    duration_ms=0,
                )
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()

            # Retry logic
            if attempt < self.retry_policy.max_retries and self.retry_policy.should_retry(last_error):
                delay = self.retry_policy.get_delay(attempt)
                logger.warning(
                    "NexusClient: Request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self.retry_policy.max_retries, delay, str(last_error)
                )
                time.sleep(delay)
                retries += 1
            else:
                break

        # All retries exhausted
        if self._circuit_breaker:
            self._circuit_breaker.record_failure()

        if not response:
            response = BridgeResponse(
                status_code=0,
                body={"error": f"All retries exhausted: {last_error}"},
                headers={},
                trace_id=headers.get("X-Nexus-Trace-ID"),
            )
        response.retries_used = retries
        return response

    # ── Public API ──────────────────────────────────────────────

    def submit_task(
        self,
        project_id: str,
        description: str,
        context: Optional[Dict] = None,
        lineage_id: Optional[str] = None,
        scope: str = "project",
        intent: str = "",
        impact: str = "low",
        clearance: str = "contributor",
    ) -> BridgeResponse:
        """
        Submit a task to the Bridge for execution.

        Args:
            project_id: Target project scope
            description: Task description
            context: Additional task context
            lineage_id: Optional lineage ID for chained requests
            scope: KAIJU scope variable
            intent: KAIJU intent variable
            impact: KAIJU impact variable
            clearance: KAIJU clearance variable

        Returns:
            BridgeResponse with task_id and status
        """
        payload = {
            "description": description,
            "context": context or {},
            "kaiju": {
                "scope": scope,
                "intent": intent,
                "impact": impact,
                "clearance": clearance,
            },
        }

        trace_id = self._generate_trace_id()
        headers = self._build_headers(project_id, trace_id, json.dumps(payload), lineage_id)

        response = self._request_with_retry("/tasks/submit", payload, headers)
        self._request_count += 1

        logger.info(
            "NexusClient: submit_task → %d (retries=%d, %.0fms) [%s]",
            response.status_code, response.retries_used, response.duration_ms, trace_id
        )
        return response

    def query_status(
        self,
        project_id: str,
        task_id: str,
    ) -> BridgeResponse:
        """Query the status of a submitted task."""
        payload = {"task_id": task_id}
        trace_id = self._generate_trace_id()
        headers = self._build_headers(project_id, trace_id, json.dumps(payload))

        return self._request_with_retry("/tasks/status", payload, headers)

    def read_memory(
        self,
        project_id: str,
        query: str,
        memory_type: str = "project",
        limit: int = 10,
    ) -> BridgeResponse:
        """Query the Vault for memory records."""
        payload = {
            "query": query,
            "type": memory_type,
            "limit": limit,
        }
        trace_id = self._generate_trace_id()
        headers = self._build_headers(project_id, trace_id, json.dumps(payload))

        return self._request_with_retry("/vault/read", payload, headers)

    def write_memory(
        self,
        project_id: str,
        content: str,
        memory_type: str = "project",
        classification: str = "standard",
    ) -> BridgeResponse:
        """Write a memory record to the Vault."""
        payload = {
            "content": content,
            "type": memory_type,
            "classification": classification,
        }
        trace_id = self._generate_trace_id()
        headers = self._build_headers(project_id, trace_id, json.dumps(payload))

        return self._request_with_retry("/vault/write", payload, headers)

    def get_stats(self) -> Dict[str, Any]:
        """Return client statistics."""
        stats = {
            "agent_id": self.agent_id,
            "bridge_url": self.bridge_url,
            "total_requests": self._request_count,
            "retry_policy": {
                "max_retries": self.retry_policy.max_retries,
                "base_delay": self.retry_policy.base_delay,
            },
        }
        if self._circuit_breaker:
            stats["circuit_breaker"] = self._circuit_breaker.get_stats()
        return stats
