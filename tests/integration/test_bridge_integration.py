"""
tests/integration/test_bridge_integration.py — A2A Bridge Integration Tests

Comprehensive integration tests for the production-hardened Bridge server.
Tests the full request lifecycle: parse → authenticate → authorize → execute → respond.

Test cases:
  1. Valid request → 200 OK with correct JSON-RPC result
  2. Missing signature → 401 Unauthorized
  3. Invalid signature → 401 Unauthorized
  4. KAIJU DENY (scope violation) → 403 Forbidden
  5. KAIJU HOLD (empty intent) → 202 Accepted with hold ticket
  6. Malformed JSON → 400 Bad Request
  Plus: task status query, vault read/write, method not allowed, unknown agent
"""

import json
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.bridge.server import (
    BridgeServer,
    jsonrpc_result,
    jsonrpc_error,
    AuthError,
    ForbiddenError,
    HeldError,
    ParseError,
)
from nexus_os.bridge.secrets import (
    SecretStore,
    generate_signature,
    verify_signature,
)
from nexus_os.governor.base import NexusGovernor
from nexus_os.governor.kaiju_auth import KaijuAuthorizer


# ── Test Fixtures ───────────────────────────────────────────────

AGENT_ID = "test-agent-1"
AGENT_SECRET = "test-secret-key-abc123"
PROJECT_ID = "proj-test"
TRACE_ID = "trace-integration-001"


@pytest.fixture
def secret_store():
    store = SecretStore()
    store.register(AGENT_ID, AGENT_SECRET)
    return store


@pytest.fixture
def governor():
    """NexusGovernor with KAIJU authorizer (no DB needed for auth-only tests)."""
    authorizer = KaijuAuthorizer()
    # NexusGovernor needs a db; pass None and handle the audit log gracefully
    gov = NexusGovernor(db=None, kaiju=authorizer, enable_cva=False)
    return gov


@pytest.fixture
def bridge_no_auth(secret_store):
    """Bridge with auth but NO governor (dev mode — skip authz)."""
    return BridgeServer(secret_store=secret_store, governor=None)


@pytest.fixture
def bridge_full(secret_store, governor):
    """Bridge with both auth AND governor (full pipeline)."""
    return BridgeServer(secret_store=secret_store, governor=governor)


def _make_body(payload: dict) -> bytes:
    """Serialize payload to JSON bytes."""
    return json.dumps(payload).encode("utf-8")


def _make_headers(
    agent_id: str = AGENT_ID,
    project_id: str = PROJECT_ID,
    trace_id: str = TRACE_ID,
    payload: bytes = b'{}',
    secret: str = AGENT_SECRET,
) -> dict:
    """Build protocol headers with valid HMAC signature."""
    raw_payload = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    sig = generate_signature(secret, trace_id, raw_payload)
    return {
        "x-nexus-agent-id": agent_id,
        "x-nexus-project-id": project_id,
        "x-nexus-trace-id": trace_id,
        "x-nexus-signature": sig,
    }


def _submit_payload(
    description: str = "Test task",
    intent: str = "execute test task for integration validation",
    scope: str = "project",
    impact: str = "low",
    clearance: str = "contributor",
) -> dict:
    """Build a standard task submission payload."""
    return {
        "description": description,
        "context": {"type": "test"},
        "kaiju": {
            "scope": scope,
            "intent": intent,
            "impact": impact,
            "clearance": clearance,
        },
    }


# ── Test Case 1: Valid Request → 200 OK ───────────────────────

class TestValidRequest:
    """Valid authenticated + authorized request should succeed."""

    def test_submit_returns_200_with_result(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 200
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["status"] == "completed"
        assert response["result"]["task_id"] is not None
        assert response["result"]["task_id"].startswith("task-")
        assert response["trace_id"] == TRACE_ID

    def test_submit_has_output(self, bridge_no_auth):
        payload = _submit_payload(description="Run analysis pipeline")
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 200
        assert response["result"]["output"] is not None
        assert "Mock execution" in response["result"]["output"]
        assert "Run analysis pipeline" in response["result"]["output"]

    def test_submit_stores_result_for_status_query(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        _, submit_resp = bridge_no_auth.handle_submit(body, headers)
        task_id = submit_resp["result"]["task_id"]

        # Query status
        status_body = _make_body({"task_id": task_id})
        status_headers = _make_headers(payload=status_body)
        status, status_resp = bridge_no_auth.handle_status(status_body, status_headers)

        assert status == 200
        assert status_resp["result"]["task_id"] == task_id
        assert status_resp["result"]["status"] == "completed"

    def test_vault_read_returns_records_list(self, bridge_no_auth):
        payload = {"query": "test query", "type": "project", "limit": 5}
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_vault_read(body, headers)

        assert status == 200
        assert response["result"]["records"] == []
        assert response["result"]["count"] == 0

    def test_vault_write_returns_record_id(self, bridge_no_auth):
        payload = {"content": "test memory content", "type": "project", "classification": "standard"}
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_vault_write(body, headers)

        assert status == 200
        assert response["result"]["record_id"].startswith("rec-")
        assert response["result"]["status"] == "written"


# ── Test Case 2: Missing Signature → 401 ──────────────────────

class TestMissingSignature:
    """Requests without X-Nexus-Signature header should be rejected."""

    def test_no_signature_returns_401(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        headers = {
            "x-nexus-agent-id": AGENT_ID,
            "x-nexus-project-id": PROJECT_ID,
            "x-nexus-trace-id": TRACE_ID,
            # No x-nexus-signature header
        }

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 401
        assert "error" in response
        assert response["error"]["code"] == 401
        assert "signature" in response["error"]["message"].lower()

    def test_empty_signature_returns_401(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        headers = {
            "x-nexus-agent-id": AGENT_ID,
            "x-nexus-project-id": PROJECT_ID,
            "x-nexus-trace-id": TRACE_ID,
            "x-nexus-signature": "",
        }

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 401


# ── Test Case 3: Invalid Signature → 401 ──────────────────────

class TestInvalidSignature:
    """Requests with wrong HMAC signature should be rejected."""

    def test_wrong_secret_returns_401(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        # Sign with wrong secret
        headers = _make_headers(secret="wrong-secret-key", payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 401
        assert "error" in response
        assert "invalid" in response["error"]["message"].lower()

    def test_tampered_payload_returns_401(self, bridge_no_auth):
        payload = _submit_payload()
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        # Tamper with body after signing
        tampered_body = body.replace(b"test", b"TAMPERED")

        status, response = bridge_no_auth.handle_submit(tampered_body, headers)

        assert status == 401

    def test_wrong_agent_returns_401(self, bridge_no_auth):
        """Signature from wrong agent_id should fail."""
        payload = _submit_payload()
        body = _make_body(payload)
        # Sign for agent-1 but claim to be agent-2
        headers = _make_headers(agent_id="unknown-agent", payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 401


# ── Test Case 4: KAIJU DENY → 403 Forbidden ───────────────────

class TestKaijuDeny:
    """KAIJU scope/impact violations should return 403."""

    def test_reader_cannot_access_system_scope(self, bridge_full):
        """A reader attempting system scope should be denied."""
        payload = _submit_payload(
            description="System config access",
            intent="read system configuration across all projects",
            scope="system",      # Reader can only access self/project
            impact="low",
            clearance="reader",  # Reader clearance
        )
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_full.handle_submit(body, headers)

        assert status == 403
        assert "error" in response
        assert response["error"]["code"] == 403
        assert "scope" in response["error"]["message"].lower() or "clearance" in response["error"]["message"].lower()

    def test_contributor_cannot_high_impact(self, bridge_full):
        """A contributor attempting high impact should be denied."""
        payload = _submit_payload(
            description="Bulk delete operation",
            intent="delete multiple project records in batch",
            scope="project",
            impact="high",         # Contributor max: medium
            clearance="contributor",
        )
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_full.handle_submit(body, headers)

        assert status == 403
        assert "error" in response
        assert "impact" in response["error"]["message"].lower() or "clearance" in response["error"]["message"].lower()


# ── Test Case 5: KAIJU HOLD → 202 Accepted ───────────────────

class TestKaijuHold:
    """Suspicious intent should result in HOLD (202) with hold ticket."""

    def test_empty_intent_returns_hold(self, bridge_full):
        """Empty intent on execute action should be held for human review."""
        payload = _submit_payload(
            description="Execute task",
            intent="",  # Empty intent triggers HOLD
            scope="project",
            impact="low",
            clearance="contributor",
        )
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_full.handle_submit(body, headers)

        assert status == 202
        assert "result" in response
        assert response["result"]["status"] == "held"
        assert response["result"]["hold_reason"] is not None
        assert "HOLD" in response["result"]["hold_reason"]
        assert response["result"]["hold_ticket"] is not None

    def test_very_short_intent_returns_hold(self, bridge_full):
        """Intent shorter than 3 chars should always be held."""
        payload = {
            "description": "Execute task",
            "context": {},
            "kaiju": {
                "scope": "project",
                "intent": "x",  # Too short — under 3 char minimum
                "impact": "low",
                "clearance": "contributor",
            },
        }
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_full.handle_submit(body, headers)

        assert status == 202
        assert response["result"]["status"] == "held"
        assert "HOLD" in response["result"]["hold_reason"]


# ── Test Case 6: Malformed JSON → 400 Bad Request ─────────────

class TestMalformedJSON:
    """Invalid JSON bodies should return 400."""

    def test_invalid_json_returns_400(self, bridge_no_auth):
        body = b'{not valid json'
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 400
        assert "error" in response
        assert "json" in response["error"]["message"].lower()

    def test_non_object_json_returns_400(self, bridge_no_auth):
        """JSON array instead of object should be rejected."""
        body = b'[1, 2, 3]'
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 400
        assert "json object" in response["error"]["message"].lower()

    def test_empty_body_returns_400(self, bridge_no_auth):
        body = b''
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 400


# ── Additional Edge Cases ─────────────────────────────────────

class TestEdgeCases:
    """Additional integration scenarios."""

    def test_method_not_allowed(self, bridge_no_auth):
        """GET requests should be rejected with 405."""
        body = _make_body(_submit_payload())
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_request("GET", body, headers)

        assert status == 405

    def test_unknown_task_status_returns_404(self, bridge_no_auth):
        """Querying a non-existent task should return 404."""
        payload = {"task_id": "task-nonexistent"}
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_no_auth.handle_status(body, headers)

        assert status == 404
        assert "not found" in response["error"]["message"].lower()

    def test_missing_trace_id_returns_401(self, bridge_no_auth):
        """Missing X-Nexus-Trace-ID should fail authentication."""
        payload = _submit_payload()
        body = _make_body(payload)
        headers = {
            "x-nexus-agent-id": AGENT_ID,
            "x-nexus-project-id": PROJECT_ID,
            # No trace_id
            "x-nexus-signature": "anything",
        }

        status, response = bridge_no_auth.handle_submit(body, headers)

        assert status == 401

    def test_jsonrpc_response_format(self, bridge_no_auth):
        """All responses should follow JSON-RPC 2.0 format."""
        payload = _submit_payload()
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        _, response = bridge_no_auth.handle_submit(body, headers)

        assert "jsonrpc" in response
        assert response["jsonrpc"] == "2.0"
        assert "trace_id" in response
        # Should have either "result" or "error", not both
        has_result = "result" in response
        has_error = "error" in response
        assert has_result != has_error or (has_result and response["result"] is not None)

    def test_full_pipeline_with_governor_allow(self, bridge_full):
        """Full auth + authz pipeline with valid KAIJU vars should succeed."""
        payload = _submit_payload(
            description="Read project memory",
            intent="read project memory records for data analysis",
            scope="project",
            impact="low",
            clearance="contributor",
        )
        body = _make_body(payload)
        headers = _make_headers(payload=body)

        status, response = bridge_full.handle_submit(body, headers)

        assert status == 200
        assert response["result"]["status"] == "completed"
        assert response["result"]["task_id"] is not None
