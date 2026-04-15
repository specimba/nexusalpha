"""
tests/unit/test_secrets.py — SecretStore Unit Tests

Comprehensive tests for the SecretStore module:
  - Secret registration, retrieval, and removal
  - Environment variable loading
  - File-based secret loading
  - Master key derivation
  - Secret rotation
  - Signature generation and verification
"""

import pytest
import os
import sys
import json
import tempfile
import hashlib
import hmac
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.bridge.secrets import (
    SecretStore, SecretNotFoundError,
    generate_signature, verify_signature,
)


class TestSecretStoreBasic:
    """Basic SecretStore CRUD operations."""

    def test_register_and_get(self):
        store = SecretStore()
        store.register("agent-1", "key_abc")
        assert store.get_secret("agent-1") == "key_abc"

    def test_get_nonexistent_raises(self):
        store = SecretStore()
        with pytest.raises(SecretNotFoundError, match="agent-999"):
            store.get_secret("agent-999")

    def test_has_secret_true(self):
        store = SecretStore()
        store.register("agent-2", "exists")
        assert store.has_secret("agent-2") is True

    def test_has_secret_false(self):
        store = SecretStore()
        assert store.has_secret("ghost") is False

    def test_remove_existing(self):
        store = SecretStore()
        store.register("agent-3", "removable")
        store.remove("agent-3")
        assert store.has_secret("agent-3") is False

    def test_remove_nonexistent_silent(self):
        store = SecretStore()
        store.remove("nobody")  # Should not raise

    def test_rotate_updates_secret(self):
        store = SecretStore()
        store.register("agent-4", "old_key")
        store.rotate("agent-4", "new_key")
        assert store.get_secret("agent-4") == "new_key"

    def test_register_overwrites(self):
        store = SecretStore()
        store.register("agent-5", "first")
        store.register("agent-5", "second")
        assert store.get_secret("agent-5") == "second"


class TestSecretStoreFileLoading:
    """File-based secret loading tests."""

    def test_load_from_json_file(self):
        secrets = {"agent-a": "file_key_1", "agent-b": "file_key_2"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(secrets, f)
            f.flush()
            store = SecretStore(secret_file=f.name)
            assert store.get_secret("agent-a") == "file_key_1"
            assert store.get_secret("agent-b") == "file_key_2"
        os.unlink(f.name)

    def test_missing_file_no_error(self):
        store = SecretStore(secret_file="/tmp/nonexistent_secrets_xyz.json")
        with pytest.raises(SecretNotFoundError):
            store.get_secret("anyone")

    def test_override_beats_file(self):
        secrets = {"agent-c": "file_secret"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(secrets, f)
            f.flush()
            store = SecretStore(secret_file=f.name)
            store.register("agent-c", "override_secret")
            assert store.get_secret("agent-c") == "override_secret"
        os.unlink(f.name)

    def test_invalid_json_file_no_crash(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            store = SecretStore(secret_file=f.name)
            # Should not crash, just log a warning
            assert store.has_secret("any") is False
        os.unlink(f.name)

    def test_non_dict_json_no_crash(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(["array", "not", "dict"], f)
            f.flush()
            store = SecretStore(secret_file=f.name)
            assert store.has_secret("any") is False
        os.unlink(f.name)


class TestSecretStoreEnvLoading:
    """Environment variable secret loading tests."""

    def test_env_var_loading(self):
        os.environ["NEXUS_SECRET_ENVAGENT"] = "env_secret_value"
        store = SecretStore()
        assert store.get_secret("envagent") == "env_secret_value"
        del os.environ["NEXUS_SECRET_ENVAGENT"]

    def test_override_beats_env(self):
        os.environ["NEXUS_SECRET_PRIORITY"] = "env_value"
        store = SecretStore()
        store.register("priority", "override_value")
        assert store.get_secret("priority") == "override_value"
        del os.environ["NEXUS_SECRET_PRIORITY"]

    def test_file_beats_env(self):
        os.environ["NEXUS_SECRET_FILETEST"] = "env_lost"
        secrets = {"filetest": "file_wins"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(secrets, f)
            f.flush()
            store = SecretStore(secret_file=f.name)
            assert store.get_secret("filetest") == "file_wins"
        os.unlink(f.name)
        del os.environ["NEXUS_SECRET_FILETEST"]


class TestSecretStoreMasterKey:
    """Master key derivation tests."""

    def test_derivation_is_deterministic(self):
        store1 = SecretStore(master_key="master_pass_123")
        store2 = SecretStore(master_key="master_pass_123")
        assert store1.get_secret("derived_a") == store2.get_secret("derived_a")

    def test_different_agents_different_secrets(self):
        store = SecretStore(master_key="master")
        s1 = store.get_secret("agent_x")
        s2 = store.get_secret("agent_y")
        assert s1 != s2

    def test_different_master_keys_different_secrets(self):
        store_a = SecretStore(master_key="key_a")
        store_b = SecretStore(master_key="key_b")
        assert store_a.get_secret("agent_1") != store_b.get_secret("agent_1")

    def test_override_beats_master_key(self):
        store = SecretStore(master_key="master")
        store.register("agent_z", "explicit")
        assert store.get_secret("agent_z") == "explicit"


class TestSignatureFunctions:
    """Signature generation and verification tests."""

    def test_valid_signature(self):
        sig = generate_signature("secret", "trace-id", "payload")
        assert verify_signature("secret", "trace-id", "payload", sig) is True

    def test_wrong_secret(self):
        sig = generate_signature("correct", "trace", "data")
        assert verify_signature("wrong", "trace", "data", sig) is False

    def test_wrong_payload(self):
        sig = generate_signature("key", "trace", "original")
        assert verify_signature("key", "trace", "modified", sig) is False

    def test_empty_inputs(self):
        sig = generate_signature("", "", "")
        assert verify_signature("", "", "", sig) is True

    def test_signature_is_hex_64(self):
        sig = generate_signature("key", "trace", "payload")
        assert len(sig) == 64
        int(sig, 16)  # Should not raise if valid hex

    def test_unicode_handling(self):
        sig = generate_signature("key", "trace", "Unicode content: \u00e9\u00f1\u00fc")
        assert verify_signature("key", "trace", "Unicode content: \u00e9\u00f1\u00fc", sig) is True

    def test_long_payload(self):
        payload = "x" * 10000
        sig = generate_signature("key", "trace", payload)
        assert verify_signature("key", "trace", payload, sig) is True

    def test_timing_safe_comparison(self):
        """Verification should use constant-time comparison."""
        sig = generate_signature("key", "trace", "data")
        # Even a very close wrong signature should fail
        wrong_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        assert verify_signature("key", "trace", "data", wrong_sig) is False
