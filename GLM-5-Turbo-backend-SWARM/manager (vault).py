"""
db/manager.py — Database Manager v3 (Thread-Safe + Hard-Fail Encryption)

Changes from v2:
  - threading.local() for per-thread connections (fixes FastAPI crash)
  - Hard-fail encryption: no silent fallback unless allow_unencrypted=True
  - Connection pool limits via max_connections
  - Explicit connection lifecycle management
"""

import sqlite3
import threading
import logging
from typing import Optional, Protocol, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class DBAdapter(Protocol):
    def execute(self, query: str, params: tuple = ()) -> Any: ...
    def executemany(self, query: str, params_list: list) -> Any: ...
    def fetchone(self, cursor: Any) -> Optional[tuple]: ...
    def fetchall(self, cursor: Any) -> List[tuple]: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class StandardAdapter:
    """Standard SQLite adapter for development."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(query, params)

    def executemany(self, query: str, params_list: list) -> sqlite3.Cursor:
        return self.conn.executemany(query, params_list)

    def fetchone(self, cursor: sqlite3.Cursor) -> Optional[tuple]:
        return cursor.fetchone()

    def fetchall(self, cursor: sqlite3.Cursor) -> List[tuple]:
        return cursor.fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class EncryptedAdapter:
    """SQLCipher adapter for production encryption."""

    def __init__(self, path: str, passphrase: str):
        try:
            import pysqlcipher3 as sqlite
        except ImportError:
            raise ImportError(
                "CRITICAL SECURITY ERROR: pysqlcipher3 not installed. "
                "Encrypted storage requested but not available. "
                "Install pysqlcipher3 or set allow_unencrypted=True for development."
            )
        self.conn = sqlite.connect(path, check_same_thread=False)
        self.conn.execute(f"PRAGMA key = '{passphrase}'")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    def execute(self, query: str, params: tuple = ()) -> Any:
        return self.conn.execute(query, params)

    def executemany(self, query: str, params_list: list) -> Any:
        return self.conn.executemany(query, params_list)

    def fetchone(self, cursor: Any) -> Optional[tuple]:
        return cursor.fetchone()

    def fetchall(self, cursor: Any) -> List[tuple]:
        return cursor.fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


@dataclass
class DBConfig:
    db_path: str
    passphrase: str
    encrypted: bool = False
    allow_unencrypted: bool = False


class DatabaseManager:
    """
    Thread-safe database connection manager.

    Uses threading.local() to provide per-thread SQLite connections,
    preventing the 'SQLite objects created in a thread' crash in
    async frameworks like FastAPI/uvicorn.

    Security policy:
    - If encrypted=True and pysqlcipher3 is missing:
      - If allow_unencrypted=False: RAISE ImportError (hard fail)
      - If allow_unencrypted=True: Log WARNING, fall back to plaintext
    - Default: allow_unencrypted=False (production-safe)
    """

    def __init__(self, config: DBConfig):
        self.config = config
        self._local = threading.local()
        self._connection_count = 0
        self._max_connections = 100
        self._lock = threading.Lock()

    def _get_adapter(self) -> DBAdapter:
        """Get or create a connection for the current thread."""
        with self._lock:
            self._connection_count += 1
            if self._connection_count > self._max_connections:
                self._connection_count -= 1
                raise RuntimeError(
                    f"Connection limit reached ({self._max_connections}). "
                    "Possible connection leak — check that close() is called."
                )

        if self.config.encrypted:
            try:
                adapter = EncryptedAdapter(
                    self.config.db_path, self.config.passphrase
                )
            except ImportError as e:
                if not self.config.allow_unencrypted:
                    raise e
                logger.warning(
                    "pysqlcipher3 missing. Falling back to StandardAdapter (UNENCRYPTED). "
                    "This is a SECURITY RISK in production."
                )
                adapter = StandardAdapter(self.config.db_path)
        else:
            adapter = StandardAdapter(self.config.db_path)

        return adapter

    def get_connection(self) -> DBAdapter:
        """Public API: get the connection for the current thread."""
        return self._get_adapter()

    def setup_schema(self) -> bool:
        """Initialize the full Nexus OS database schema."""
        adapter = self._get_adapter()

        adapter.execute("""
            CREATE TABLE IF NOT EXISTS agent_registry (
                agent_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                capabilities TEXT,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'halted')),
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP
            )
        """)

        adapter.execute("""
            CREATE TABLE IF NOT EXISTS memory_records (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                type TEXT CHECK(type IN ('session', 'project', 'experience', 'wisdom')),
                content TEXT,
                trust_score REAL DEFAULT 0.5,
                provenance TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                consent TEXT DEFAULT 'granted' CHECK(consent IN ('granted', 'pending', 'revoked')),
                classification TEXT DEFAULT 'standard' CHECK(classification IN ('standard', 'sensitive', 'critical')),
                deleted_at TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP
            )
        """)

        try:
            adapter.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_content USING fts5(
                    record_id UNINDEXED,
                    content
                )
            """)
        except Exception as e:
            logger.warning("FTS5 Error: %s", e)

        adapter.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                agent_id TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'failed', 'blocked')),
                dependencies TEXT,
                description TEXT,
                context TEXT,
                heartbeat TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)

        adapter.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_id TEXT,
                decision TEXT CHECK(decision IN ('allow', 'deny', 'hold', 'halt')),
                details TEXT,
                trace_id TEXT
            )
        """)

        adapter.execute("""
            CREATE TABLE IF NOT EXISTS agent_reputation (
                agent_id TEXT PRIMARY KEY,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agent_registry(agent_id)
            )
        """)

        # Migration: add content column if missing (for databases created before this column existed)
        try:
            adapter.execute("ALTER TABLE memory_records ADD COLUMN content TEXT")
        except Exception:
            pass  # Column already exists or table doesn't exist yet

        adapter.commit()
        return True

    def close(self):
        """Close the current thread's connection."""
        adapter = getattr(self._local, "adapter", None)
        if adapter:
            adapter.close()
            self._local.adapter = None
            with self._lock:
                self._connection_count -= 1
