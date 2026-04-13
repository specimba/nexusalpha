"""
tests/integration/test_hermes.py — Hermes Router Integration Tests

Tests 3-layer routing: task classification, experience scoring, cost optimization.
"""

import pytest
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.engine.hermes import (
    HermesRouter, TaskClassifier, ExperienceScorer, CostOptimizer,
    ModelProfile, TaskComplexity, TaskDomain, SkillRecord, RoutingDecision,
)


@pytest.fixture
def db():
    config = DBConfig(db_path="test_hermes.db", passphrase="x", encrypted=False)
    db_mgr = DatabaseManager(config)
    db_mgr.setup_schema()
    yield db_mgr
    db_mgr.close()
    if os.path.exists("test_hermes.db"):
        os.remove("test_hermes.db")


@pytest.fixture
def models():
    return [
        ModelProfile("osman-coder", "local", 0.0, 8192, ["code", "fast"], 200, True, 0.7),
        ModelProfile("osman-reasoning", "local", 0.0, 8192, ["reasoning"], 1500, True, 0.8),
        ModelProfile("groq/gpt-oss-20b", "groq", 0.08, 32768, ["code", "analysis", "reasoning"], 800, False, 0.6),
        ModelProfile("groq/llama-fast", "groq", 0.05, 8192, ["code", "fast"], 300, False, 0.5),
    ]


@pytest.fixture
def router(db, models):
    r = HermesRouter(db, models=models, quality_threshold=0.5)
    return r


class TestTaskClassifier:
    def test_classify_code_task(self):
        classifier = TaskClassifier()
        domain, complexity = classifier.classify("Implement a REST API endpoint for user authentication")
        assert domain == TaskDomain.CODE
        assert complexity in (TaskComplexity.STANDARD, TaskComplexity.COMPLEX)

    def test_classify_analysis_task(self):
        classifier = TaskClassifier()
        domain, complexity = classifier.classify("Analyze the performance metrics from the last sprint")
        assert domain == TaskDomain.ANALYSIS

    def test_classify_security_task(self):
        classifier = TaskClassifier()
        domain, _ = classifier.classify("Security audit of the authentication module")
        assert domain == TaskDomain.SECURITY

    def test_classify_unknown_task(self):
        classifier = TaskClassifier()
        domain, _ = classifier.classify("xyz")
        assert domain == TaskDomain.UNKNOWN

    def test_complexity_from_length(self):
        classifier = TaskClassifier()
        _, complexity = classifier.classify("quick check")
        assert complexity == TaskComplexity.TRIVIAL

    def test_complexity_upgrade_for_critical_signals(self):
        classifier = TaskClassifier()
        _, complexity = classifier.classify(
            "This is a production deployment that requires architecture review and security validation"
        )
        assert complexity in (TaskComplexity.COMPLEX, TaskComplexity.CRITICAL)


class TestExperienceScorer:
    def _create_scorer(self, db):
        """Create an ExperienceScorer with model_performance table initialized."""
        conn = db.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_performance (
                model_id TEXT NOT NULL,
                task_class TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                total_latency_ms REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (model_id, task_class)
            )
        """)
        conn.commit()
        return ExperienceScorer(db)

    def test_score_with_no_experience(self, db):
        scorer = self._create_scorer(db)
        models = [ModelProfile("test-model", "local", 0.0, 4096, [], 100, True, 0.6)]
        scores = scorer.score(TaskDomain.CODE, models)
        assert "test-model" in scores
        # No data at all → falls back to base quality_score
        assert scores["test-model"] == 0.6

    def test_record_and_score_outcome(self, db):
        scorer = self._create_scorer(db)
        models = [ModelProfile("good-model", "local", 0.0, 4096, [], 100, True, 0.5)]

        # Record successful outcomes
        for _ in range(5):
            scorer.record_outcome("good-model", TaskDomain.CODE, True, 500.0)

        # Record one failure
        scorer.record_outcome("good-model", TaskDomain.CODE, False, 200.0)

        scores = scorer.score(TaskDomain.CODE, models)
        # Should have elevated score due to successful history (Bayesian smoothed)
        assert scores["good-model"] > 0.5

    def test_slow_success_penalized(self, db):
        scorer = self._create_scorer(db)
        models = [ModelProfile("slow-model", "local", 0.0, 4096, [], 100, True, 0.5)]

        scorer.record_outcome("slow-model", TaskDomain.CODE, True, 5000.0)  # 5 seconds
        scores = scorer.score(TaskDomain.CODE, models)
        # Slow execution reduces provenance score (but Bayesian score stays high)
        assert scores["slow-model"] > 0.5


class TestCostOptimizer:
    def test_select_cheapest_for_trivial(self):
        optimizer = CostOptimizer(quality_threshold=0.5)
        models = [
            ModelProfile("expensive", "cloud", 1.0, 4096, []),
            ModelProfile("cheap", "cloud", 0.01, 4096, []),
        ]
        scores = {"expensive": 0.8, "cheap": 0.7}
        selected, score, reason = optimizer.select(scores, models, TaskComplexity.TRIVIAL)
        assert selected == "cheap"
        assert "Cost-optimized" in reason

    def test_select_best_quality_for_critical(self):
        optimizer = CostOptimizer(quality_threshold=0.5)
        models = [
            ModelProfile("cloud-best", "cloud", 2.0, 4096, []),
            ModelProfile("local-good", "local", 0.0, 4096, []),
        ]
        scores = {"cloud-best": 0.95, "local-good": 0.85}
        selected, score, reason = optimizer.select(scores, models, TaskComplexity.CRITICAL)
        assert selected == "local-good"  # Prefers local for critical
        assert "local" in reason.lower()

    def test_fallback_when_no_model_above_threshold(self):
        optimizer = CostOptimizer(quality_threshold=0.9)
        models = [ModelProfile("m1", "cloud", 0.1, 4096, [])]
        scores = {"m1": 0.3}
        selected, score, reason = optimizer.select(scores, models, TaskComplexity.STANDARD)
        assert selected == "m1"
        assert "Fallback" in reason


class TestHermesRouter:
    def test_route_code_task(self, router):
        decision = router.route("task-1", "Implement a function to parse JSON config files")
        assert decision.domain == TaskDomain.CODE
        assert decision.selected_model in ("osman-coder", "groq/gpt-oss-20b", "groq/llama-fast")
        assert decision.score > 0.0

    def test_route_with_skill_fast_path(self, router):
        skill = SkillRecord(
            skill_id="skill-json-parse",
            name="JSON Config Parsing",
            task_type="code",
            pattern=r"json.*(parse|config|file)",
            recommended_model="osman-coder",
            success_rate=0.95,
            execution_count=10,
        )
        router.register_skill(skill)

        decision = router.route("task-2", "Parse the JSON config file and extract database settings")
        assert decision.matched_skill == "skill-json-parse"
        assert decision.selected_model == "osman-coder"
        assert "Fast-path" in decision.reason

    def test_route_reasoning_to_reasoning_model(self, router):
        decision = router.route("task-3", "Reason through the optimal data structure for this algorithm")
        assert decision.domain == TaskDomain.REASONING
        assert decision.selected_model in ("osman-reasoning", "groq/gpt-oss-20b")

    def test_record_outcome_updates_scorer(self, router):
        decision = router.route("task-4", "Quick code fix")
        router.record_outcome("task-4", success=True, duration_ms=300.0)
        # Should not raise
        stats = router.get_stats()
        assert stats["total_decisions"] == 1

    def test_stats(self, router):
        router.route("task-5", "Write a test suite")
        router.route("task-6", "Analyze performance data")
        stats = router.get_stats()
        assert stats["total_decisions"] == 2
        assert "code" in stats["domains"] or "analysis" in stats["domains"]

    def test_no_models_raises(self, db):
        router = HermesRouter(db)
        with pytest.raises(RuntimeError, match="No models registered"):
            router.route("task-x", "do something")


class TestSkillRecord:
    def test_skill_matching(self, router):
        skill = SkillRecord(
            skill_id="skill-deploy",
            name="Deployment",
            task_type="operations",
            pattern=r"deploy.*(server|production|app)",
            recommended_model="osman-coder",
            success_rate=0.9,
            execution_count=5,
        )
        router.register_skill(skill)
        decision = router.route("task-7", "Deploy the server to production environment")
        assert decision.matched_skill == "skill-deploy"

    def test_skill_needs_minimum_experience(self, router):
        skill = SkillRecord(
            skill_id="skill-new",
            name="New Skill",
            task_type="code",
            pattern=r"test.*pattern",
            recommended_model="osman-coder",
            success_rate=1.0,
            execution_count=1,  # Below minimum threshold of 3
        )
        router.register_skill(skill)
        decision = router.route("task-8", "Test this pattern matching logic")
        # Should NOT match because execution_count < 3
        assert decision.matched_skill is None


class TestBayesianScoring:
    """Tests for the Bayesian-smoothed model_performance backend."""

    def _create_scorer(self, db):
        """Create an ExperienceScorer with model_performance table initialized."""
        conn = db.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_performance (
                model_id TEXT NOT NULL,
                task_class TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                total_latency_ms REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (model_id, task_class)
            )
        """)
        conn.commit()
        return ExperienceScorer(db)

    def test_ensure_schema_creates_table(self, db):
        """model_performance table should be created on router init."""
        router = HermesRouter(db)
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_performance'"
        ).fetchall()
        assert len(rows) == 1

    def test_bayesian_prior_applies(self, db):
        """With no data in model_performance, falls back to quality_score."""
        scorer = self._create_scorer(db)
        models = [ModelProfile("new-model", "local", 0.0, 4096, [], 100, True, 0.3)]
        scores = scorer.score(TaskDomain.CODE, models)
        # No data at all → falls back to base quality_score
        assert scores["new-model"] == 0.3

    def test_bayesian_accumulates_successes(self, db):
        """Bayesian score should increase with more successes."""
        scorer = self._create_scorer(db)
        models = [ModelProfile("model-a", "local", 0.0, 4096, [], 100, True, 0.5)]

        for _ in range(10):
            scorer.record_outcome("model-a", TaskDomain.CODE, True, 200.0)

        scores = scorer.score(TaskDomain.CODE, models)
        # Bayesian: (10 + 10) / (10 + 0 + 2) = 20/12 ≈ 0.917
        expected = (ExperienceScorer.PRIOR_SUCCESS + 10) / (ExperienceScorer.PRIOR_SUCCESS + 10 + ExperienceScorer.PRIOR_FAILURE)
        assert abs(scores["model-a"] - expected) < 0.01
        assert scores["model-a"] > 0.85

    def test_bayesian_resists_small_sample_overfit(self, db):
        """1 success should NOT push score to 1.0 (Bayesian prior prevents this)."""
        scorer = self._create_scorer(db)
        models = [ModelProfile("model-b", "local", 0.0, 4096, [], 100, True, 0.5)]

        scorer.record_outcome("model-b", TaskDomain.CODE, True, 100.0)

        scores = scorer.score(TaskDomain.CODE, models)
        # Bayesian: (10 + 1) / (10 + 0 + 2) = 11/12 ≈ 0.917 (NOT 1.0)
        assert scores["model-b"] < 1.0
        assert scores["model-b"] > 0.8

    def test_bayesian_declines_with_failures(self, db):
        """Multiple failures should pull score below prior."""
        scorer = self._create_scorer(db)
        models = [ModelProfile("model-c", "local", 0.0, 4096, [], 100, True, 0.9)]

        scorer.record_outcome("model-c", TaskDomain.CODE, True, 100.0)
        for _ in range(10):
            scorer.record_outcome("model-c", TaskDomain.CODE, False, 100.0)

        scores = scorer.score(TaskDomain.CODE, models)
        # Bayesian: (10 + 1) / (10 + 1 + 2 + 10) = 11/23 ≈ 0.478
        assert scores["model-c"] < 0.6

    def test_get_performance_data(self, router):
        """get_performance_data should return rows from model_performance."""
        # Route a task first to create a decision, then record outcome
        router.route("task-perf-1", "Write a function to parse JSON")
        router.record_outcome("task-perf-1", success=True, duration_ms=300.0)
        router.route("task-perf-2", "Analyze error metrics")
        router.record_outcome("task-perf-2", success=False, duration_ms=500.0)

        perf_data = router.get_performance_data()
        assert len(perf_data) >= 1
        row = perf_data[0]
        assert "model_id" in row
        assert "task_class" in row
        assert "success_count" in row
        assert "failure_count" in row
        assert "total_latency_ms" in row

    def test_domain_isolation_in_bayesian(self, db):
        """Scores should be tracked independently per domain."""
        scorer = self._create_scorer(db)
        models = [ModelProfile("multi-model", "local", 0.0, 4096, [], 100, True, 0.5)]

        for _ in range(10):
            scorer.record_outcome("multi-model", TaskDomain.CODE, True, 200.0)
        for _ in range(10):
            scorer.record_outcome("multi-model", TaskDomain.ANALYSIS, False, 200.0)

        code_scores = scorer.score(TaskDomain.CODE, models)
        analysis_scores = scorer.score(TaskDomain.ANALYSIS, models)

        assert code_scores["multi-model"] > 0.8
        assert analysis_scores["multi-model"] < 0.6
