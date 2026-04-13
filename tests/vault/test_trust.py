"""
tests/vault/test_trust.py — Persistent Bayesian Trust Scoring Tests (HPv2)

8 tests across 3 classes:
  TestBayesianScore: Base rate, success increases, failure decreases,
                     overfit resistance, decline after failures
  TestTrustPersistence: Score persists across instances, stats fields
  TestTrustEdgeCases: Unknown agent returns base rate
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.vault.trust import TrustScorer


@pytest.fixture
def db():
    """Create an in-memory-like test database with schema."""
    config = DBConfig(db_path="test_trust.db", passphrase="x", encrypted=False)
    db_mgr = DatabaseManager(config)
    db_mgr.setup_schema()
    yield db_mgr
    db_mgr.close()
    if os.path.exists("test_trust.db"):
        os.remove("test_trust.db")


@pytest.fixture
def scorer(db):
    s = TrustScorer(db)
    yield s
    s.close()


class TestBayesianScore:
    """Tests for Bayesian score computation."""

    def test_new_agent_base_rate(self, scorer):
        """Unknown agent should return ~0.833 (PRIOR_SUCCESS / (PRIOR_SUCCESS + PRIOR_FAILURE))."""
        score = scorer.get_score("agent-new-001")
        expected = TrustScorer.PRIOR_SUCCESS / (TrustScorer.PRIOR_SUCCESS + TrustScorer.PRIOR_FAILURE)
        assert abs(score - expected) < 0.001, f"Expected {expected}, got {score}"
        assert score > 0.83
        assert score < 0.84

    def test_success_increases_score(self, scorer):
        """Recording a success should increase the score above the base rate."""
        base_score = scorer.get_score("agent-good-001")
        scorer.record_success("agent-good-001")
        new_score = scorer.get_score("agent-good-001")
        assert new_score > base_score, "Score should increase after recording a success"

    def test_failure_decreases_score(self, scorer):
        """Recording a failure should decrease the score below the base rate."""
        base_score = scorer.get_score("agent-bad-001")
        scorer.record_failure("agent-bad-001")
        new_score = scorer.get_score("agent-bad-001")
        assert new_score < base_score, "Score should decrease after recording a failure"

    def test_overfit_resistance(self, scorer):
        """Many successes should NOT push the score to 1.0 (Bayesian prior prevents this)."""
        for _ in range(100):
            scorer.record_success("agent-reliable-001")

        score = scorer.get_score("agent-reliable-001")
        # Bayesian: (100 + 10) / (100 + 10 + 2) = 110/112 ≈ 0.982
        assert score < 1.0, "Score should never reach 1.0 due to Bayesian prior"
        assert score > 0.98, "Score should be very high after 100 successes"

    def test_decline_after_failures(self, scorer):
        """Multiple consecutive failures should pull score below the base rate."""
        # Start with some successes
        for _ in range(10):
            scorer.record_success("agent-declining-001")

        # Then record many failures
        for _ in range(20):
            scorer.record_failure("agent-declining-001")

        score = scorer.get_score("agent-declining-001")
        # Bayesian: (10 + 10) / (10 + 20 + 10 + 2) = 20/42 ≈ 0.476
        assert score < 0.6, "Score should decline significantly after many failures"


class TestTrustPersistence:
    """Tests for database persistence of trust scores."""

    def test_score_persists_across_instances(self, db):
        """Trust score should persist when creating a new TrustScorer with the same DB."""
        scorer1 = TrustScorer(db)
        scorer1.record_success("agent-persist-001")
        scorer1.record_success("agent-persist-001")
        scorer1.record_failure("agent-persist-001")
        scorer1.close()

        # Create a new scorer instance — should read the same data
        scorer2 = TrustScorer(db)
        stats = scorer2.get_stats("agent-persist-001")
        scorer2.close()

        assert stats["successes"] == 2
        assert stats["failures"] == 1
        assert stats["total"] == 3

    def test_stats_returns_correct_fields(self, scorer):
        """get_stats should return all required fields with correct types."""
        scorer.record_success("agent-stats-001")
        scorer.record_success("agent-stats-001")
        scorer.record_failure("agent-stats-001")

        stats = scorer.get_stats("agent-stats-001")

        assert "successes" in stats
        assert "failures" in stats
        assert "score" in stats
        assert "total" in stats

        assert isinstance(stats["successes"], int)
        assert isinstance(stats["failures"], int)
        assert isinstance(stats["score"], float)
        assert isinstance(stats["total"], int)
        assert 0.0 <= stats["score"] <= 1.0
        assert stats["total"] == stats["successes"] + stats["failures"]


class TestTrustEdgeCases:
    """Edge case tests for the trust scoring system."""

    def test_unknown_agent_returns_base_rate(self, scorer):
        """An agent with no recorded outcomes should return the prior base rate."""
        stats = scorer.get_stats("agent-never-seen-001")
        expected = TrustScorer.PRIOR_SUCCESS / (TrustScorer.PRIOR_SUCCESS + TrustScorer.PRIOR_FAILURE)

        assert stats["successes"] == 0
        assert stats["failures"] == 0
        assert stats["total"] == 0
        assert abs(stats["score"] - expected) < 0.001
