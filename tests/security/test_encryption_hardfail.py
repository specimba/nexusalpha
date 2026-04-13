"""
tests/security/test_encryption_hardfail.py — DB Encryption Hard-Fail Tests

Validates that DatabaseManager v3 properly enforces encryption policy:
  - Hard fails when encrypted=True but pysqlcipher3 is missing
  - Falls back gracefully when allow_unencrypted=True
  - Works normally in unencrypted mode
  - Is thread-safe under concurrent access
"""

import pytest
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig


class TestEncryptionHardFail:
    """Test encryption enforcement policy."""

    def test_encrypted_without_pysqlcipher_hard_fails(self):
        """When encrypted=True and pysqlcipher3 missing, must raise ImportError."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'pysqlcipher3':
                raise ImportError("No module named 'pysqlcipher3'")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            config = DBConfig(
                db_path="test.db",
                passphrase="x",
                encrypted=True,
                allow_unencrypted=False,
            )
            db = DatabaseManager(config)
            with pytest.raises(ImportError, match="CRITICAL SECURITY ERROR"):
                db.get_connection()
        finally:
            builtins.__import__ = real_import

    def test_unencrypted_mode_works(self):
        """Standard unencrypted mode should work without any special deps."""
        config = DBConfig(db_path="test_unencrypted.db", passphrase="x", encrypted=False)
        db = DatabaseManager(config)
        conn = db.get_connection()
        conn.execute("SELECT 1")
        db.close()
        if os.path.exists("test_unencrypted.db"):
            os.remove("test_unencrypted.db")

    def test_encrypted_with_allow_unencrypted_falls_back(self):
        """When allow_unencrypted=True, should fall back with a warning, not crash."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'pysqlcipher3':
                raise ImportError("No module named 'pysqlcipher3'")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            config = DBConfig(
                db_path="test_fallback.db",
                passphrase="x",
                encrypted=True,
                allow_unencrypted=True,
            )
            db = DatabaseManager(config)
            conn = db.get_connection()
            conn.execute("SELECT 1")
            db.close()
        finally:
            builtins.__import__ = real_import
        if os.path.exists("test_fallback.db"):
            os.remove("test_fallback.db")

    def test_thread_safety(self):
        """Concurrent threads should each get their own connection without errors."""
        config = DBConfig(db_path="test_threadsafe.db", passphrase="x", encrypted=False)
        db = DatabaseManager(config)
        db.setup_schema()
        errors = []

        def worker(thread_id):
            try:
                conn = db.get_connection()
                for i in range(10):
                    conn.execute(
                        "INSERT INTO audit_logs (actor_id, action, decision) VALUES (?, ?, ?)",
                        (f"thread_{thread_id}", f"action_{i}", "allow"),
                    )
                    conn.commit()
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0, f"Thread safety errors: {errors}"
        db.close()
        if os.path.exists("test_threadsafe.db"):
            os.remove("test_threadsafe.db")

    def test_connection_limit(self):
        """Should raise RuntimeError when max_connections is exceeded."""
        config = DBConfig(db_path="test_limits.db", passphrase="x", encrypted=False)
        db = DatabaseManager(config)
        db._max_connections = 3

        connections = []
        for _ in range(3):
            conn = db.get_connection()
            connections.append(conn)

        with pytest.raises(RuntimeError, match="Connection limit reached"):
            db.get_connection()

        for conn in connections:
            conn.close()
        if os.path.exists("test_limits.db"):
            os.remove("test_limits.db")

    def test_setup_schema_creates_tables(self):
        """setup_schema should create all core tables without errors."""
        config = DBConfig(db_path="test_schema.db", passphrase="x", encrypted=False)
        db = DatabaseManager(config)
        result = db.setup_schema()
        assert result is True

        conn = db.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "agent_registry" in table_names
        assert "memory_records" in table_names
        assert "tasks" in table_names
        assert "audit_logs" in table_names
        assert "agent_reputation" in table_names
        db.close()
        if os.path.exists("test_schema.db"):
            os.remove("test_schema.db")
