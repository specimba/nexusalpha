"""tests/vault/test_manager.py — 5-Track Memory Diagnostics"""
import pytest
from nexus_os.vault.manager import VaultManager

@pytest.fixture
def vault():
    # Use in-memory SQLite for fast testing
    return VaultManager()

def test_5_track_schema_creation(vault):
    # Verify the table exists and accepts valid track types
    vault.store_track("agent-1", "research", "trust", "alpha", 1.5)
    vault.store_track("agent-1", "research", "trust", "beta", 0.5)
    
    val = vault.retrieve_track("agent-1", "research", "trust", "alpha")
    assert val == 1.5

def test_track_type_constraint(vault):
    # Verify the CHECK constraint blocks invalid track types
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        vault.store_track("agent-1", "research", "invalid_track", "key", "value")

def test_get_full_agent_profile(vault):
    vault.store_track("agent-x", "code", "trust", "score", 0.92)
    vault.store_track("agent-x", "code", "capability", "python", "expert")
    vault.store_track("agent-x", "code", "failure_pattern", "syntax", 2)
    
    profile = vault.get_agent_profile("agent-x", "code")
    
    assert profile["trust"]["score"] == 0.92
    assert profile["capability"]["python"] == "expert"
    assert profile["failure_pattern"]["syntax"] == 2
    assert profile["governance"] == {}  # Empty but initialized
