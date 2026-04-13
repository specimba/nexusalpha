"""
vault/trust.py — Persistent Bayesian Trust Scoring (HPv2)

Tracks per-agent success/failure counts using Bayesian smoothing to produce
robust trust scores that resist overfitting to small sample sizes.

Prior: PRIOR_SUCCESS=10, PRIOR_FAILURE=2 → 83% base success rate.
This matches the prior used in engine/hermes.py for consistent behavior
across the trust and routing subsystems.

Uses the agent_reputation table (agent_id, successes, failures, last_updated)
with UPSERT pattern for recording outcomes. Thread safety is delegated to
DatabaseManager which uses threading.local() for per-thread connections.
"""

import logging
from typing import Dict, Optional

from nexus_os.db.manager import DatabaseManager

logger = logging.getLogger(__name__)


class TrustScorer:
    """
    Bayesian trust scorer for tracking agent reliability.

    Produces a smoothed trust score in [0.0, 1.0] for each agent based on
    observed successes and failures. The Bayesian prior prevents the score
    from jumping to extremes with small sample sizes.

    Formula:
        score = (successes + PRIOR_SUCCESS) / (total + PRIOR_SUCCESS + PRIOR_FAILURE)

    With defaults (PRIOR_SUCCESS=10, PRIOR_FAILURE=2):
        - New agent (0 observations): score = 10/12 ≈ 0.833
        - After 1 success: score = 11/13 ≈ 0.846
        - After 100 successes, 0 failures: score = 110/112 ≈ 0.982 (never reaches 1.0)
    """

    # Bayesian prior — same as hermes.py ExperienceScorer
    PRIOR_SUCCESS = 10
    PRIOR_FAILURE = 2

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._conn = db.get_connection()
        logger.info(
            "TrustScorer initialized (prior: %d successes, %d failures, base_rate=%.3f)",
            self.PRIOR_SUCCESS, self.PRIOR_FAILURE,
            self.PRIOR_SUCCESS / (self.PRIOR_SUCCESS + self.PRIOR_FAILURE),
        )

    def close(self):
        """Release the database connection held by this scorer."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_score(self, agent_id: str) -> float:
        """
        Get the Bayesian trust score for an agent.

        Args:
            agent_id: Unique agent identifier

        Returns:
            float: Trust score in [0.0, 1.0]. Unknown agents receive the prior rate (~0.833).
        """
        row = self._conn.execute(
            "SELECT successes, failures FROM agent_reputation WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()

        if row is None:
            # No data — return prior-only estimate
            score = self.PRIOR_SUCCESS / (self.PRIOR_SUCCESS + self.PRIOR_FAILURE)
            logger.debug("Trust score for unknown agent %s: %.4f (prior only)", agent_id, score)
            return score

        successes, failures = row[0], row[1]
        total = successes + failures
        score = (successes + self.PRIOR_SUCCESS) / (total + self.PRIOR_SUCCESS + self.PRIOR_FAILURE)

        logger.debug(
            "Trust score for %s: %.4f (%d successes, %d failures, %d total)",
            agent_id, score, successes, failures, total,
        )
        return score

    def _ensure_agent_registered(self, agent_id: str) -> None:
        """Ensure the agent exists in agent_registry (FK prerequisite for agent_reputation)."""
        self._conn.execute(
            """INSERT OR IGNORE INTO agent_registry (agent_id, model_id, status)
               VALUES (?, 'unknown', 'active')""",
            (agent_id,),
        )

    def record_success(self, agent_id: str) -> None:
        """
        Record a successful outcome for an agent.

        Uses UPSERT to atomically create or update the agent's reputation row.
        Auto-registers the agent in agent_registry if not already present.

        Args:
            agent_id: Unique agent identifier
        """
        self._ensure_agent_registered(agent_id)
        self._conn.execute(
            """INSERT INTO agent_reputation (agent_id, successes, failures, last_updated)
               VALUES (?, 1, 0, CURRENT_TIMESTAMP)
               ON CONFLICT(agent_id) DO UPDATE SET
                   successes = successes + 1,
                   last_updated = CURRENT_TIMESTAMP""",
            (agent_id,),
        )
        self._conn.commit()
        logger.info("Recorded success for agent %s", agent_id)

    def record_failure(self, agent_id: str) -> None:
        """
        Record a failed outcome for an agent.

        Uses UPSERT to atomically create or update the agent's reputation row.
        Auto-registers the agent in agent_registry if not already present.

        Args:
            agent_id: Unique agent identifier
        """
        self._ensure_agent_registered(agent_id)
        self._conn.execute(
            """INSERT INTO agent_reputation (agent_id, successes, failures, last_updated)
               VALUES (?, 0, 1, CURRENT_TIMESTAMP)
               ON CONFLICT(agent_id) DO UPDATE SET
                   failures = failures + 1,
                   last_updated = CURRENT_TIMESTAMP""",
            (agent_id,),
        )
        self._conn.commit()
        logger.info("Recorded failure for agent %s", agent_id)

    def get_stats(self, agent_id: str) -> Dict:
        """
        Get full trust statistics for an agent.

        Args:
            agent_id: Unique agent identifier

        Returns:
            dict: {successes, failures, score, total}
                  Unknown agents return {successes: 0, failures: 0, score: prior_rate, total: 0}
        """
        row = self._conn.execute(
            "SELECT successes, failures FROM agent_reputation WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()

        if row is None:
            score = self.PRIOR_SUCCESS / (self.PRIOR_SUCCESS + self.PRIOR_FAILURE)
            logger.debug("Stats for unknown agent %s: prior only", agent_id)
            return {
                "successes": 0,
                "failures": 0,
                "score": score,
                "total": 0,
            }

        successes, failures = row[0], row[1]
        total = successes + failures
        score = (successes + self.PRIOR_SUCCESS) / (total + self.PRIOR_SUCCESS + self.PRIOR_FAILURE)

        return {
            "successes": successes,
            "failures": failures,
            "score": score,
            "total": total,
        }
