"""
observability/squeez.py — Squeez Memory Pruner

Implements MIA-inspired trajectory compression and memory pruning.
Reduces raw logs to contrastive success/failure patterns.

Layer 1: Session TTL pruning (hard-delete old session memories)
Layer 2: Experience compression (aggregate task outcomes into paradigms)
Layer 3: Wisdom extraction (promote high-trust, high-access experience to wisdom)

Aligned with the S-P-E-W memory hierarchy:
  S (Session)   → prune after TTL
  P (Project)   → compress duplicates, keep latest
  E (Experience)→ aggregate into paradigms (success/failure ratios)
  W (Wisdom)    → promote from E when trust > threshold AND access_count > threshold
"""

import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from nexus_os.db.manager import DatabaseManager

logger = logging.getLogger(__name__)


class SqueezPruner:
    """
    Periodically prunes and compresses memory records based on age, access patterns,
    and trust scores. Implements a simplified version of the MIA trajectory compression
    approach described in arXiv:2507.xxxxx.

    The pruner operates in three passes:
      Pass 1: Hard-delete expired session memories (default TTL: 24h)
      Pass 2: Compress raw experience logs into aggregated paradigms
      Pass 3: Promote high-value experience records to the wisdom layer
    """

    # Default TTLs per memory layer (seconds)
    DEFAULT_TTL = {
        "session": 86400,       # 24 hours
        "project": 604800,      # 7 days (only prunes unaccessed)
        "experience": 2592000,  # 30 days
        "wisdom": None,         # Never auto-prune
    }

    # Promotion thresholds
    WISDOM_TRUST_THRESHOLD = 0.85
    WISDOM_ACCESS_THRESHOLD = 10

    def __init__(self, db: DatabaseManager, config: Optional[Dict] = None):
        self.db = db
        self._ttl = {**self.DEFAULT_TTL}
        if config and "ttl" in config:
            self._ttl.update(config["ttl"])
        if config and "wisdom_trust" in config:
            self.WISDOM_TRUST_THRESHOLD = config["wisdom_trust"]
        if config and "wisdom_access" in config:
            self.WISDOM_ACCESS_THRESHOLD = config["wisdom_access"]

    # ── Pass 1: Session TTL Pruning ──────────────────────────────

    def prune_session_layer(self, ttl_seconds: Optional[int] = None) -> int:
        """
        Hard-delete session memories older than TTL.

        Args:
            ttl_seconds: Override TTL (default from config, 24h)

        Returns:
            Number of records deleted
        """
        ttl = ttl_seconds or self._ttl["session"]
        if ttl is None:
            return 0

        cutoff = time.time() - ttl
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM memory_records WHERE type = 'session' AND timestamp < ?",
            (cutoff,)
        )
        conn.commit()
        count = cursor.rowcount
        logger.info("Squeez [Pass 1]: Pruned %d expired session memories (TTL=%ds)", count, ttl)
        return count

    # ── Pass 2: Experience Compression ────────────────────────────

    def compress_experience_layer(
        self,
        project_id: Optional[str] = None,
        batch_size: int = 100,
    ) -> Tuple[int, int]:
        """
        Compress raw experience logs into structured paradigms.
        Aggregates task outcomes per agent into success-rate paradigms.

        For each agent with completed tasks:
          - Calculate success rate = successes / total
          - Store as a single compressed experience record
          - Mark source tasks as 'compressed' (via provenance field)

        Args:
            project_id: Scope to a specific project (None = all)
            batch_size: Maximum records to compress in one pass

        Returns:
            Tuple of (paradigms_created, raw_records_compressed)
        """
        conn = self.db.get_connection()

        query = """
            SELECT agent_id, project_id, COUNT(*) as total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successes
            FROM tasks
            WHERE status IN ('completed', 'failed')
        """
        params: tuple = ()
        if project_id:
            query += " AND project_id = ?"
            params = (project_id,)
        query += " GROUP BY agent_id, project_id ORDER BY total DESC LIMIT ?"

        rows = conn.execute(query, params + (batch_size,)).fetchall()

        paradigms_created = 0
        raw_compressed = 0

        for row in rows:
            agent_id = row[0]
            proj_id = row[1]
            total = row[2]
            successes = row[3]
            success_rate = successes / max(total, 1)
            paradigm_id = f"paradigm-{agent_id}-{proj_id}-{int(time.time())}"

            # Check if a recent paradigm already exists for this agent+project
            existing = conn.execute(
                """SELECT id FROM memory_records
                   WHERE type = 'experience'
                   AND agent_id = ?
                   AND project_id = ?
                   AND provenance LIKE 'squeez-compression%'
                   AND timestamp > ?
                   LIMIT 1""",
                (agent_id, proj_id, time.time() - 3600)  # 1-hour dedup window
            ).fetchone()

            if existing:
                # Update existing paradigm instead of creating duplicate
                conn.execute(
                    """UPDATE memory_records
                       SET trust_score = ?, timestamp = ?
                       WHERE id = ?""",
                    (success_rate, time.time(), existing[0])
                )
                logger.debug(
                    "Squeez [Pass 2]: Updated paradigm %s (rate=%.2f, n=%d)",
                    existing[0], success_rate, total
                )
            else:
                conn.execute(
                    """INSERT INTO memory_records
                       (id, project_id, agent_id, type, trust_score, provenance, timestamp, consent)
                       VALUES (?, ?, ?, 'experience', ?, ?, ?, 'granted')""",
                    (paradigm_id, proj_id, agent_id, success_rate,
                     f"squeez-compression:{total}tasks", time.time())
                )
                logger.debug(
                    "Squeez [Pass 2]: Created paradigm %s (rate=%.2f, n=%d)",
                    paradigm_id, success_rate, total
                )
                paradigms_created += 1

            raw_compressed += total

        conn.commit()
        logger.info(
            "Squeez [Pass 2]: %d paradigms created/updated from %d raw tasks",
            paradigms_created, raw_compressed
        )
        return paradigms_created, raw_compressed

    # ── Pass 3: Wisdom Promotion ──────────────────────────────────

    def promote_to_wisdom(
        self,
        trust_threshold: Optional[float] = None,
        access_threshold: Optional[int] = None,
    ) -> int:
        """
        Promote high-value experience records to the wisdom layer.
        Criteria: trust_score >= threshold AND access_count >= threshold.

        Args:
            trust_threshold: Override trust threshold (default 0.85)
            access_threshold: Override access count threshold (default 10)

        Returns:
            Number of records promoted
        """
        trust_t = trust_threshold or self.WISDOM_TRUST_THRESHOLD
        access_t = access_threshold or self.WISDOM_ACCESS_THRESHOLD

        conn = self.db.get_connection()

        rows = conn.execute(
            """SELECT id, project_id, agent_id, content, trust_score, access_count
               FROM memory_records
               WHERE type = 'experience'
               AND trust_score >= ?
               AND access_count >= ?
               AND id NOT IN (
                   SELECT REPLACE(provenance, 'promoted-from:', '')
                   FROM memory_records
                   WHERE type = 'wisdom' AND provenance LIKE 'promoted-from:%'
               )""",
            (trust_t, access_t)
        ).fetchall()

        promoted = 0
        for row in rows:
            wisdom_id = f"wisdom-{row[0]}"
            conn.execute(
                """INSERT INTO memory_records
                   (id, project_id, agent_id, type, trust_score, provenance, timestamp, consent, classification)
                   VALUES (?, ?, ?, 'wisdom', ?, ?, ?, 'granted', 'critical')""",
                (wisdom_id, row[1], row[2], row[4],
                 f"promoted-from:{row[0]}", time.time())
            )
            promoted += 1
            logger.info(
                "Squeez [Pass 3]: Promoted %s to wisdom (trust=%.2f, accesses=%d)",
                row[0], row[4], row[5]
            )

        conn.commit()
        logger.info("Squeez [Pass 3]: %d experience records promoted to wisdom", promoted)
        return promoted

    # ── Full Pipeline ────────────────────────────────────────────

    def run_full_pipeline(
        self,
        project_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Execute all three pruning passes in sequence.

        Args:
            project_id: Scope to a specific project (None = all)

        Returns:
            Dict with keys: sessions_pruned, paradigms_created, raw_compressed, promoted
        """
        logger.info("Squeez: Starting full pipeline for project=%s", project_id or "ALL")

        results = {}
        results["sessions_pruned"] = self.prune_session_layer()
        paradigms, raw = self.compress_experience_layer(project_id)
        results["paradigms_created"] = paradigms
        results["raw_compressed"] = raw
        results["promoted"] = self.promote_to_wisdom()

        total = sum(results.values())
        logger.info("Squeez: Pipeline complete. Total operations: %d", total)
        return results

    # ── Statistics ───────────────────────────────────────────────

    def get_memory_stats(self, project_id: Optional[str] = None) -> Dict[str, int]:
        """Get current record counts by memory layer."""
        conn = self.db.get_connection()
        query = "SELECT type, COUNT(*) as count FROM memory_records WHERE deleted_at IS NULL"
        params: tuple = ()
        if project_id:
            query += " AND project_id = ?"
            params = (project_id,)
        query += " GROUP BY type"

        rows = conn.execute(query, params).fetchall()
        return {row[0]: row[1] for row in rows}
