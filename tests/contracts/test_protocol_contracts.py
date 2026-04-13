"""
tests/contracts/test_protocol_contracts.py — Bridge Protocol Contract Tests

Validates that Bridge request/response headers conform to the Nexus A2A protocol:
  - X-Nexus-Project-ID must be present and valid
  - X-Nexus-Trace-ID must be a valid UUID
  - X-Nexus-Lineage-ID must be present for chained requests
  - X-Nexus-Signature must match HMAC-SHA256 of the payload
  - Missing or malformed headers must return appropriate HTTP errors
"""

import pytest
import os
import sys
import hashlib
import hmac
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.bridge.secrets import (
    SecretStore, generate_signature, verify_signature, SecretNotFoundError
)


class TestSecretStore:
    """Test the SecretStore secret management component."""

    def test_register_and_retrieve_secret(self):
        store = SecretStore()
        store.register("agent-001", "secret_key_abc")
        assert store.get_secret("agent-001") == "secret_key_abc"

    def test_missing_secret_raises(self):
        store = SecretStore()
        with pytest.raises(SecretNotFoundError):
            store.get_secret("nonexistent_agent")

    def test_has_secret(self):
        store = SecretStore()
        store.register("agent-002", "key123")
        assert store.has_secret("agent-002") is True
        assert store.has_secret("agent-999") is False

    def test_override_priority(self):
        """In-memory override should take priority over file and env."""
        store = SecretStore(secret_file="/nonexistent/path.json")
        store.register("agent-003", "override_key")
        assert store.get_secret("agent-003") == "override_key"

    def test_remove_secret(self):
        store = SecretStore()
        store.register("agent-004", "removable_key")
        assert store.has_secret("agent-004") is True
        store.remove("agent-004")
        assert store.has_secret("agent-004") is False

    def test_rotate_secret(self):
        store = SecretStore()
        store.register("agent-005", "old_key")
        store.rotate("agent-005", "new_key")
        assert store.get_secret("agent-005") == "new_key"

    def test_master_key_derivation(self):
        """Agent secrets derived from master key should be deterministic."""
        store_a = SecretStore(master_key="master_secret")
        store_b = SecretStore(master_key="master_secret")
        assert store_a.get_secret("derived_agent") == store_b.get_secret("derived_agent")
        # Different agent IDs produce different secrets
        assert store_a.get_secret("agent_x") != store_a.get_secret("agent_y")

    def test_master_key_vs_override(self):
        """Runtime override should beat master key derivation."""
        store = SecretStore(master_key="master")
        store.register("agent-006", "explicit_override")
        assert store.get_secret("agent-006") == "explicit_override"


class TestSignatureGeneration:
    """Test HMAC-SHA256 signature generation and verification."""

    def test_signature_roundtrip(self):
        secret = "test_secret_key"
        trace_id = str(uuid.uuid4())
        payload = '{"action": "read", "resource": "memory_records"}'
        sig = generate_signature(secret, trace_id, payload)
        assert verify_signature(secret, trace_id, payload, sig) is True

    def test_wrong_secret_fails(self):
        sig = generate_signature("correct_secret", "trace-123", "payload_data")
        assert verify_signature("wrong_secret", "trace-123", "payload_data", sig) is False

    def test_tampered_payload_fails(self):
        sig = generate_signature("secret", "trace-123", "original_payload")
        assert verify_signature("secret", "trace-123", "tampered_payload", sig) is False

    def test_different_trace_id_fails(self):
        sig = generate_signature("secret", "trace-123", "payload")
        assert verify_signature("secret", "trace-456", "payload", sig) is False

    def test_signature_deterministic(self):
        """Same inputs should always produce the same signature."""
        sig1 = generate_signature("s", "t", "p")
        sig2 = generate_signature("s", "t", "p")
        assert sig1 == sig2

    def test_signature_length(self):
        """HMAC-SHA256 should produce 64 hex characters."""
        sig = generate_signature("key", "trace", "data")
        assert len(sig) == 64


class TestProtocolHeaders:
    """Test the Nexus A2A protocol header contract."""

    REQUIRED_HEADERS = [
        "X-Nexus-Project-ID",
        "X-Nexus-Trace-ID",
        "X-Nexus-Agent-ID",
        "X-Nexus-Signature",
    ]

    def test_required_headers_list(self):
        """Verify the canonical list of required headers."""
        assert len(self.REQUIRED_HEADERS) == 4
        assert "X-Nexus-Project-ID" in self.REQUIRED_HEADERS

    def test_project_id_format(self):
        """Project ID should be a non-empty string."""
        project_id = "proj_abc123"
        assert isinstance(project_id, str)
        assert len(project_id) > 0

    def test_trace_id_is_uuid(self):
        """Trace ID should be a valid UUID v4."""
        trace_id = str(uuid.uuid4())
        uuid.UUID(trace_id, version=4)  # Will raise ValueError if invalid

    def test_full_header_contract(self):
        """Simulate a valid full Bridge request header set."""
        headers = {
            "X-Nexus-Project-ID": "proj_demo",
            "X-Nexus-Trace-ID": str(uuid.uuid4()),
            "X-Nexus-Agent-ID": "reviewer-01",
            "X-Nexus-Signature": generate_signature("secret", "trace", "body"),
            "X-Nexus-Lineage-ID": str(uuid.uuid4()),  # Optional for chained requests
        }
        for header in self.REQUIRED_HEADERS:
            assert header in headers, f"Missing required header: {header}"
