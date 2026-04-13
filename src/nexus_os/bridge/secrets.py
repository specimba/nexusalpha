"""
bridge/secrets.py — Secret Management for Bridge Authentication

Replaces hardcoded AGENT_SECRETS dict with a proper secret store.
Supports:
  - Environment variable loading
  - JSON file-based secret store
  - Runtime secret rotation
  - Per-agent secret derivation from a master key

NO secrets are stored in source code.
"""

import os
import json
import hashlib
import hmac
import logging
from typing import Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class SecretNotFoundError(Exception):
    """Raised when a requested agent secret is not found."""
    pass


class SecretStore:
    """
    Multi-source secret store for Bridge authentication.

    Lookup order:
    1. In-memory overrides (runtime-registered secrets)
    2. Secret file (JSON)
    3. Environment variables (NEXUS_SECRET_{AGENT_ID})
    4. Master key derivation (if master key is set)
    """

    def __init__(
        self,
        secret_file: Optional[str] = None,
        master_key: Optional[str] = None,
        env_prefix: str = "NEXUS_SECRET_",
    ):
        self._overrides: Dict[str, str] = {}
        self._env_prefix = env_prefix
        self._master_key = master_key
        self._file_secrets: Dict[str, str] = {}

        if secret_file:
            self._load_file(secret_file)

    def _load_file(self, path: str):
        p = Path(path)
        if p.exists():
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._file_secrets = data
                    logger.info("Loaded %d secrets from %s", len(data), path)
                else:
                    logger.warning("Secret file %s is not a JSON object", path)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load secret file %s: %s", path, e)
        else:
            logger.info("Secret file %s not found, skipping", path)

    def register(self, agent_id: str, secret: str):
        """Register a secret at runtime (highest priority)."""
        self._overrides[agent_id] = secret

    def get_secret(self, agent_id: str) -> str:
        """Retrieve the secret for an agent."""
        if agent_id in self._overrides:
            return self._overrides[agent_id]

        if agent_id in self._file_secrets:
            return self._file_secrets[agent_id]

        env_key = f"{self._env_prefix}{agent_id.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val

        if self._master_key:
            derived = self._derive_secret(agent_id)
            self._overrides[agent_id] = derived
            return derived

        raise SecretNotFoundError(
            f"No secret found for agent '{agent_id}'. "
            f"Set {env_key} env var, add to secrets file, or register at runtime."
        )

    def _derive_secret(self, agent_id: str) -> str:
        """Derive a per-agent secret from the master key using HMAC-SHA256."""
        return hmac.new(
            self._master_key.encode(),
            agent_id.encode(),
            hashlib.sha256,
        ).hexdigest()

    def has_secret(self, agent_id: str) -> bool:
        try:
            self.get_secret(agent_id)
            return True
        except SecretNotFoundError:
            return False

    def remove(self, agent_id: str):
        self._overrides.pop(agent_id, None)

    def rotate(self, agent_id: str, new_secret: str):
        old = self._overrides.get(agent_id)
        self._overrides[agent_id] = new_secret
        logger.info("Rotated secret for agent %s (had previous: %s)", agent_id, old is not None)


def generate_signature(secret: str, trace_id: str, payload: str) -> str:
    """Generate HMAC-SHA256 signature for Bridge requests."""
    message = f"{secret}:{trace_id}:{payload}"
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(
    secret: str, trace_id: str, payload: str, provided_signature: str
) -> bool:
    """Verify a Bridge request signature using constant-time comparison."""
    expected = generate_signature(secret, trace_id, payload)
    return hmac.compare_digest(expected, provided_signature)
