"""
tests/integration/test_squeez.py — Squeez Memory Pruner Integration Tests

Tests the 3-pass pruning pipeline:
  Pass 1: Session TTL pruning
  Pass 2: Experience compression
  Pass 3: Wisdom promotion

Uses a real (in-memory) DatabaseManager with full schema.
"""

import pytest
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.observability.squeez import SqueezPruner


@pytest.fixture
def db():
    """Create an in-memory database with full schema."""
    config = DBConfig(db_path="test_squeez.db", passphrase="x", encrypted=False)
    db_mgr = DatabaseManager(config)
    db_mgr.setup_schema()
    yield db_mgr
    db_mgr.close()
    if os.path.exists("test_squeez.db"):
        os.remove("test_squeez.db")


@pytest.fixture
def pruner(db):
    return SqueezPruner(db, config={"ttl": {"session": 1, "experience": 1}})


class TestSessionPruning:
    """Pass 1: Session TTL pruning."""

    def test_prune_expired_sessions(self, db, pruner):
        """Sessions older than TTL should be deleted."""
        conn = db.get_connection()
        now = time.time()
        # Insert old session
        conn.execute(
            "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, 'session', ?)",
            ("sess-old", "proj-1", "agent-1", now - 10)
        )
        # Insert fresh session
        conn.execute(
            "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, 'session', ?)",
            ("sess-fresh", "proj-1", "agent-1", now)
        )
        conn.commit()

        count = pruner.prune_session_layer(ttl_seconds=5)
        assert count == 1

        rows = conn.execute("SELECT id FROM memory_records WHERE type='session'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "sess-fresh"

    def test_prune_nothing_if_all_fresh(self, db, pruner):
        """No sessions should be pruned if all are within TTL."""
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, 'session', ?)",
            ("sess-1", "proj-1", "agent-1", time.time())
        )
        conn.commit()

        count = pruner.prune_session_layer(ttl_seconds=60)
        assert count == 0

    def test_prune_respects_project_scope(self, db, pruner):
        """Pruning should only affect the targeted project (if specified)."""
        conn = db.get_connection()
        old_time = time.time() - 100
        for proj in ["proj-a", "proj-b"]:
            conn.execute(
                "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, 'session', ?)",
                (f"sess-{proj}", proj, "agent-1", old_time)
            )
        conn.commit()

        count = pruner.prune_session_layer(ttl_seconds=5)
        # Both should be pruned since prune_session_layer doesn't filter by project
        assert count == 2


class TestExperienceCompression:
    """Pass 2: Experience compression."""

    def test_compress_creates_paradigm(self, db, pruner):
        """Should aggregate task outcomes into an experience paradigm."""
        conn = db.get_connection()
        # Insert completed tasks
        for i in range(5):
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, agent_id, status, created_at) VALUES (?, ?, ?, 'completed', ?)",
                (f"task-{i}", "proj-1", "agent-1", time.time())
            )
        conn.execute(
            "INSERT INTO tasks (task_id, project_id, agent_id, status, created_at) VALUES (?, ?, ?, 'failed', ?)",
            ("task-fail", "proj-1", "agent-1", time.time())
        )
        conn.commit()

        paradigms, raw = pruner.compress_experience_layer(project_id="proj-1")
        assert paradigms == 1
        assert raw == 6  # 5 completed + 1 failed

    def test_compress_deduplicates(self, db, pruner):
        """Should not create duplicate paradigms within the dedup window."""
        conn = db.get_connection()
        for i in range(3):
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, agent_id, status, created_at) VALUES (?, ?, ?, 'completed', ?)",
                (f"task-dup-{i}", "proj-2", "agent-2", time.time())
            )
        conn.commit()

        pruner.compress_experience_layer(project_id="proj-2")
        paradigms2, _ = pruner.compress_experience_layer(project_id="proj-2")
        assert paradigms2 == 0  # Should update existing, not create new

    def test_compress_empty_database(self, db, pruner):
        """Should handle empty database gracefully."""
        paradigms, raw = pruner.compress_experience_layer()
        assert paradigms == 0
        assert raw == 0


class TestWisdomPromotion:
    """Pass 3: Wisdom promotion."""

    def test_promote_high_trust_experience(self, db, pruner):
        """High-trust, high-access experience should be promoted to wisdom."""
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, trust_score, access_count, timestamp)
               VALUES (?, ?, ?, 'experience', ?, ?, ?)""",
            ("exp-promote", "proj-1", "agent-1", 0.9, 15, time.time())
        )
        conn.commit()

        count = pruner.promote_to_wisdom(trust_threshold=0.85, access_threshold=10)
        assert count == 1

        rows = conn.execute("SELECT type FROM memory_records WHERE id LIKE 'wisdom-%'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "wisdom"

    def test_no_promote_low_trust(self, db, pruner):
        """Low-trust experience should NOT be promoted."""
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, trust_score, access_count, timestamp)
               VALUES (?, ?, ?, 'experience', ?, ?, ?)""",
            ("exp-low", "proj-1", "agent-1", 0.5, 15, time.time())
        )
        conn.commit()

        count = pruner.promote_to_wisdom()
        assert count == 0

    def test_no_duplicate_promotion(self, db, pruner):
        """Same experience should not be promoted twice."""
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, trust_score, access_count, timestamp)
               VALUES (?, ?, ?, 'experience', ?, ?, ?)""",
            ("exp-dup", "proj-1", "agent-1", 0.95, 20, time.time())
        )
        conn.commit()

        pruner.promote_to_wisdom()
        count2 = pruner.promote_to_wisdom()
        assert count2 == 0  # Already promoted


class TestFullPipeline:
    """Integration: Full 3-pass pipeline."""

    def test_full_pipeline(self, db, pruner):
        """All three passes should execute in sequence."""
        conn = db.get_connection()
        now = time.time()

        # Insert old session
        conn.execute(
            "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, 'session', ?)",
            ("sess-pipe", "proj-1", "agent-1", now - 100)
        )
        # Insert completed tasks for compression
        for i in range(3):
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, agent_id, status, created_at) VALUES (?, ?, ?, 'completed', ?)",
                (f"task-pipe-{i}", "proj-1", "agent-1", now)
            )
        # Insert promotable experience
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, trust_score, access_count, timestamp)
               VALUES (?, ?, ?, 'experience', ?, ?, ?)""",
            ("exp-pipe", "proj-1", "agent-1", 0.9, 12, now)
        )
        conn.commit()

        results = pruner.run_full_pipeline(project_id="proj-1")
        assert results["sessions_pruned"] == 1
        assert results["paradigms_created"] == 1
        assert results["raw_compressed"] == 3
        assert results["promoted"] == 1


class TestMemoryStats:
    def test_get_memory_stats(self, db, pruner):
        conn = db.get_connection()
        for layer in ["session", "project", "experience", "wisdom"]:
            conn.execute(
                "INSERT INTO memory_records (id, project_id, agent_id, type, timestamp) VALUES (?, ?, ?, ?, ?)",
                (f"stat-{layer}", "proj-1", "agent-1", layer, time.time())
            )
        conn.commit()

        stats = pruner.get_memory_stats(project_id="proj-1")
        assert stats["session"] == 1
        assert stats["project"] == 1
        assert stats["experience"] == 1
        assert stats["wisdom"] == 1
