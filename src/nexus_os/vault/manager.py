"""
vault/manager.py — VaultManager: S-P-E-W Memory Vault with MINJA v2 Protection

Central memory management for Nexus OS. Integrates:
  - MINJA v2 multi-layer poisoning detection (vault/poisoning.py)
  - Bayesian trust scoring (vault/trust.py)
  - S-P-E-W memory layer hierarchy (Session → Project → Experience → Wisdom)
  - Access tracking and soft deletion
  - Trace-ID context propagation

Memory Layers:
  S (Session)   → Short-lived, auto-pruned by SqueezPruner
  P (Project)   → Medium-term project knowledge
  E (Experience) → Compressed task outcome patterns
  W (Wisdom)    → High-trust, high-access promoted knowledge

Security:
  Every write_memory() call goes through MINJA validate_write().
  Low-trust agents negating high-trust memories are blocked.
  Velocity limits prevent flood attacks.
  Pattern anomaly detection catches duplicate injection.
"""

import uuid
import time
import logging
from typing import Dict, List, Optional, Any

from nexus_os.db.manager import DatabaseManager
from nexus_os.vault.poisoning import MinjaDetector, PoisoningError
from nexus_os.vault.trust import TrustScorer

logger = logging.getLogger(__name__)


class VaultManager:
    """
    S-P-E-W Memory Vault with MINJA v2 poisoning protection.

    All write operations are validated through the MINJA detector
    before being persisted to the database. Reads and searches
    update access counters for SqueezPruner wisdom promotion.
    """

    VALID_TYPES = {"session", "project", "experience", "wisdom"}
    VALID_CLASSIFICATIONS = {"standard", "sensitive", "critical"}
    VALID_CONSENT = {"granted", "pending", "revoked"}

    def __init__(self, db_manager: DatabaseManager, config: Optional[Dict] = None):
        cfg = config or {}
        self.db = db_manager
        self.trust_scorer = TrustScorer(db_manager)
        self.poison_detector = MinjaDetector(
            velocity_threshold=cfg.get("velocity_threshold", 10),
            window_seconds=cfg.get("window_seconds", 60),
            similarity_threshold=cfg.get("similarity_threshold", 0.3),
            contradiction_negation_boost=cfg.get("contradiction_negation_boost", 0.15),
            pattern_window=cfg.get("pattern_window", 50),
            pattern_anomaly_ratio=cfg.get("pattern_anomaly_ratio", 0.6),
        )

    # ── Write ───────────────────────────────────────────────────

    def write_memory(
        self,
        project_id: str,
        agent_id: str,
        content: str,
        memory_type: str = "session",
        classification: str = "standard",
        consent: str = "granted",
        trust_score: Optional[float] = None,
        provenance: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        """
        Write a memory record with MINJA validation.

        Returns:
            The record_id of the created memory.

        Raises:
            PoisoningError: If MINJA detects a poisoning attempt.
            ValueError: If memory_type or classification is invalid.
        """
        if memory_type not in self.VALID_TYPES:
            raise ValueError(f"Invalid memory type: {memory_type}. Must be one of {self.VALID_TYPES}")
        if classification not in self.VALID_CLASSIFICATIONS:
            raise ValueError(f"Invalid classification: {classification}")
        if consent not in self.VALID_CONSENT:
            raise ValueError(f"Invalid consent: {consent}")

        agent_trust = trust_score if trust_score is not None else self.trust_scorer.get_score(agent_id)

        # MINJA v2 validation
        is_safe, reason = self.poison_detector.validate_write(
            project_id, agent_id, content, agent_trust
        )
        if not is_safe:
            logger.warning(
                "MINJA blocked write from agent=%s trust=%.2f in project=%s: %s",
                agent_id, agent_trust, project_id, reason,
            )
            raise PoisoningError(reason)

        record_id = f"{memory_type}-{uuid.uuid4().hex[:12]}"
        conn = self.db.get_connection()
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, content, trust_score,
                provenance, classification, consent, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id, project_id, agent_id, memory_type, content,
                agent_trust, provenance or "", classification, consent,
                time.time(),
            ),
        )
        conn.commit()

        # Register successful write with MINJA for future pattern analysis
        self.poison_detector.register_write(project_id, agent_id, content, agent_trust)

        logger.info(
            "Vault write: record=%s type=%s agent=%s project=%s trace=%s",
            record_id, memory_type, agent_id, project_id, trace_id or "-",
        )
        return record_id

    # ── Read ────────────────────────────────────────────────────

    def read_memory(
        self,
        project_id: str,
        memory_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read memory records from the vault.

        Args:
            project_id: Project scope.
            memory_type: Optional type filter (session/project/experience/wisdom).
            limit: Maximum records to return.
            offset: Pagination offset.
            agent_id: Optional agent filter.

        Returns:
            List of memory record dicts.
        """
        query = """
            SELECT id, project_id, agent_id, type, content, trust_score,
                   provenance, timestamp, consent, classification,
                   access_count, last_accessed
            FROM memory_records
            WHERE deleted_at IS NULL AND project_id = ?
        """
        params: list = [project_id]

        if memory_type:
            if memory_type not in self.VALID_TYPES:
                raise ValueError(f"Invalid memory type: {memory_type}")
            query += " AND type = ?"
            params.append(memory_type)

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self.db.get_connection()
        rows = conn.execute(query, params).fetchall()

        # Update access_count and last_accessed
        now = time.time()
        for row in rows:
            record_id = row[0]
            conn.execute(
                "UPDATE memory_records SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (now, record_id),
            )
        conn.commit()

        return [
            {
                "id": r[0], "project_id": r[1], "agent_id": r[2],
                "type": r[3], "content": r[4], "trust_score": r[5],
                "provenance": r[6], "timestamp": r[7], "consent": r[8],
                "classification": r[9], "access_count": r[10],
                "last_accessed": r[11],
            }
            for r in rows
        ]

    # ── Search ──────────────────────────────────────────────────

    def search(
        self,
        project_id: str,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search across memory content.

        Uses LIKE %%query%% for broad matching. Returns actual records
        sorted by timestamp descending. Updates access_count for hits.

        Returns:
            List of matching memory record dicts. NEVER a placeholder string.
        """
        if not query or not query.strip():
            return []

        search_pattern = f"%{query}%"
        conn = self.db.get_connection()
        rows = conn.execute(
            """SELECT id, project_id, agent_id, type, content, trust_score,
                      provenance, timestamp, consent, classification,
                      access_count, last_accessed
               FROM memory_records
               WHERE deleted_at IS NULL
                 AND project_id = ?
                 AND content LIKE ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (project_id, search_pattern, limit),
        ).fetchall()

        # Update access counts
        now = time.time()
        for row in rows:
            conn.execute(
                "UPDATE memory_records SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (now, row[0]),
            )
        conn.commit()

        return [
            {
                "id": r[0], "project_id": r[1], "agent_id": r[2],
                "type": r[3], "content": r[4], "trust_score": r[5],
                "provenance": r[6], "timestamp": r[7], "consent": r[8],
                "classification": r[9], "access_count": r[10],
                "last_accessed": r[11],
            }
            for r in rows
        ]

    # ── Get Single ──────────────────────────────────────────────

    def get_memory(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Get a single memory record by ID."""
        conn = self.db.get_connection()
        row = conn.execute(
            """SELECT id, project_id, agent_id, type, content, trust_score,
                      provenance, timestamp, consent, classification,
                      access_count, last_accessed
               FROM memory_records
               WHERE id = ? AND deleted_at IS NULL""",
            (record_id,),
        ).fetchone()

        if row is None:
            return None

        # Update access
        conn.execute(
            "UPDATE memory_records SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            (time.time(), record_id),
        )
        conn.commit()

        return {
            "id": row[0], "project_id": row[1], "agent_id": row[2],
            "type": row[3], "content": row[4], "trust_score": row[5],
            "provenance": row[6], "timestamp": row[7], "consent": row[8],
            "classification": row[9], "access_count": row[10],
            "last_accessed": row[11],
        }

    # ── Delete ──────────────────────────────────────────────────

    def delete_memory(self, record_id: str, soft: bool = True) -> bool:
        """
        Delete a memory record.

        Args:
            record_id: The record to delete.
            soft: If True, sets deleted_at timestamp. If False, hard-deletes.

        Returns:
            True if the record was found and deleted, False otherwise.
        """
        conn = self.db.get_connection()
        if soft:
            conn.execute(
                "UPDATE memory_records SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (time.time(), record_id),
            )
        else:
            conn.execute(
                "DELETE FROM memory_records WHERE id = ?",
                (record_id,),
            )
        conn.commit()
        return conn.execute(
            "SELECT changes()"
        ).fetchone()[0] > 0

    # ── Stats ───────────────────────────────────────────────────

    def get_stats(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Get memory statistics by layer."""
        conn = self.db.get_connection()
        query = "SELECT type, COUNT(*) as count FROM memory_records WHERE deleted_at IS NULL"
        params: list = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " GROUP BY type"

        rows = conn.execute(query, params).fetchall()
        layer_counts = {row[0]: row[1] for row in rows}

        total = sum(layer_counts.values())
        return {
            "total": total,
            "session": layer_counts.get("session", 0),
            "project": layer_counts.get("project", 0),
            "experience": layer_counts.get("experience", 0),
            "wisdom": layer_counts.get("wisdom", 0),
        }
