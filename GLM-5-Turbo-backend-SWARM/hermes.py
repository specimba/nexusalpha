"""
engine/hermes.py — Hermes Experience-Based Model Router

Inspired by Hermes Agent (NousResearch) — self-improving agents that extract
and refine skills from execution history. This router replaces naive round-robin
with a 3-layer routing strategy:

  Layer 1: TASK CLASSIFICATION — Classify the incoming task by type/domain
  Layer 2: EXPERIENCE SCORING — Score each available model based on historical
            performance for this task type (from experience paradigms)
  Layer 3: COST-OPTIMIZED SELECTION — Among top-scoring models, select the cheapest
            one that meets the quality threshold

This module also implements the SKILL.md pattern from Hermes Agent:
  - After each successful task execution, the router extracts a reusable skill
  - Skills are stored as structured records in the vault
  - Future tasks are matched against known skills for fast-path routing

Architecture:
  HermesRouter → TaskClassifier → ExperienceScorer → CostOptimizer → model_id
"""

import time
import logging
import re
import uuid
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from nexus_os.db.manager import DatabaseManager

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Task complexity levels for routing decisions."""
    TRIVIAL = "trivial"         # Simple lookup, formatting
    STANDARD = "standard"       # Normal code, analysis, generation
    COMPLEX = "complex"         # Multi-step reasoning, large context
    CRITICAL = "critical"       # Architecture decisions, security operations


class TaskDomain(Enum):
    """Task domain categories."""
    CODE = "code"               # Code generation, review, debugging
    ANALYSIS = "analysis"       # Data analysis, research synthesis
    REASONING = "reasoning"     # Logical reasoning, math, planning
    CREATIVE = "creative"       # Writing, brainstorming, design
    OPERATIONS = "operations"   # System tasks, configuration, deployment
    SECURITY = "security"       # Security audits, policy checks
    UNKNOWN = "unknown"


@dataclass
class ModelProfile:
    """Profile of a single model available for routing."""
    model_id: str
    provider: str              # "local", "groq", "openrouter", etc.
    cost_per_token: float      # USD per 1M tokens
    max_context: int           # Maximum context window (tokens)
    capabilities: List[str]    # ["code", "reasoning", "fast", "vision", ...]
    latency_estimate_ms: float = 500.0
    is_local: bool = False
    quality_score: float = 0.5  # Updated by ExperienceScorer


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    task_id: str
    selected_model: str
    complexity: TaskComplexity
    domain: TaskDomain
    score: float               # 0.0 to 1.0 confidence in selection
    cost_estimate: float       # Estimated cost in USD
    reason: str                # Human-readable explanation
    matched_skill: Optional[str] = None  # Skill ID if fast-path matched
    timestamp: float = field(default_factory=time.time)


@dataclass
class SkillRecord:
    """A reusable skill extracted from successful task execution."""
    skill_id: str
    name: str
    task_type: str             # The task domain/type this skill covers
    pattern: str               # Regex or keyword pattern for matching
    recommended_model: str     # Model that performed best for this skill
    success_rate: float
    execution_count: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


# ── Domain keywords for task classification ─────────────────────

DOMAIN_KEYWORDS = {
    TaskDomain.CODE: [
        "code", "implement", "function", "class", "debug", "fix", "bug",
        "refactor", "test", "compile", "syntax", "variable", "import",
        "module", "api", "endpoint", "sql", "query", "schema", "deploy",
    ],
    TaskDomain.ANALYSIS: [
        "analyze", "compare", "evaluate", "assess", "measure", "metric",
        "report", "statistics", "data", "trend", "correlation", "summary",
        "aggregate", "benchmark", "performance",
    ],
    TaskDomain.REASONING: [
        "reason", "logic", "prove", "derive", "calculate", "solve",
        "optimize", "algorithm", "strategy", "plan", "design", "architect",
        "tradeoff", "decision",
    ],
    TaskDomain.CREATIVE: [
        "write", "draft", "create", "design", "brainstorm", "idea",
        "narrative", "story", "content", "copy", "email", "message",
        "template", "document",
    ],
    TaskDomain.OPERATIONS: [
        "configure", "setup", "install", "deploy", "restart", "monitor",
        "health", "status", "log", "backup", "migrate", "scale",
    ],
    TaskDomain.SECURITY: [
        "security", "audit", "vulnerability", "auth", "encrypt", "permission",
        "compliance", "policy", "risk", "threat", "incident", "firewall",
    ],
}

COMPLEXITY_SIGNALS = {
    TaskComplexity.TRIVIAL: {"quick", "simple", "format", "check", "list", "get", "fetch"},
    TaskComplexity.STANDARD: {"implement", "create", "update", "modify", "generate"},
    TaskComplexity.COMPLEX: {"redesign", "optimize", "refactor", "integrate", "migrate"},
    TaskComplexity.CRITICAL: {"architecture", "security", "production", "deploy", "migration"},
}


class TaskClassifier:
    """Classifies tasks by domain and complexity for routing."""

    def classify(self, description: str, context: Optional[Dict] = None) -> Tuple[TaskDomain, TaskComplexity]:
        """Classify a task description into domain and complexity."""
        desc_lower = description.lower()
        words = set(re.findall(r'[a-z]+', desc_lower))

        # Domain classification: count keyword matches
        domain_scores = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in words)
            domain_scores[domain] = score

        best_domain = max(domain_scores, key=domain_scores.get)
        if domain_scores[best_domain] == 0:
            best_domain = TaskDomain.UNKNOWN

        # Complexity classification
        desc_len = len(description)
        context_size = len(str(context or {}))

        if desc_len < 50 and context_size < 200:
            complexity = TaskComplexity.TRIVIAL
        elif desc_len < 200 and context_size < 1000:
            complexity = TaskComplexity.STANDARD
        elif desc_len < 500 or "multi-step" in desc_lower:
            complexity = TaskComplexity.COMPLEX
        else:
            complexity = TaskComplexity.COMPLEX

        # Override based on explicit complexity signals
        for comp, signals in COMPLEXITY_SIGNALS.items():
            if any(s in desc_lower for s in signals):
                # Only upgrade, never downgrade
                if comp.value in ("complex", "critical") and complexity.value in ("trivial", "standard"):
                    complexity = comp
                elif comp.value == "critical" and complexity.value != "critical":
                    complexity = comp

        return best_domain, complexity


class ExperienceScorer:
    """
    Scores models based on historical performance for a given task domain.

    Uses a dual-backend approach:
      1. model_performance table — Bayesian-smoothed success rates (primary)
      2. memory_records experience layer — Fallback provenance trail

    Bayesian smoothing prevents overfitting to small sample sizes by
    applying a weak prior (default: 83% base success rate).
    """

    # Weak Bayesian prior: assume 83% success until proven otherwise
    PRIOR_SUCCESS = 10
    PRIOR_FAILURE = 2

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._cache: Dict[str, Dict[str, float]] = {}
        self._cache_ttl = 300  # 5 minutes

    def score(
        self,
        domain: TaskDomain,
        models: List[ModelProfile],
    ) -> Dict[str, float]:
        """
        Score each model for the given domain based on experience history.

        Scoring strategy:
          1. Query model_performance table for Bayesian-smoothed rates
          2. Fall back to memory_records experience paradigms
          3. Use ModelProfile.quality_score as base for unknown models

        Returns: {model_id: score (0.0 to 1.0)}
        """
        cache_key = domain.value
        if cache_key in self._cache:
            return self._cache[cache_key]

        conn = self.db.get_connection()
        model_scores: Dict[str, float] = {}

        # ── Backend 1: model_performance table (Bayesian) ──
        perf_rows = conn.execute(
            """SELECT model_id, success_count, failure_count
               FROM model_performance
               WHERE task_class = ?""",
            (domain.value,)
        ).fetchall()

        bayesian_scores: Dict[str, float] = {}
        for row in perf_rows:
            mid = row[0]
            s = row[1] + self.PRIOR_SUCCESS
            f = row[2] + self.PRIOR_FAILURE
            bayesian_scores[mid] = s / (s + f)

        # ── Backend 2: memory_records fallback ──
        experience_scores: Dict[str, List[float]] = defaultdict(list)
        mem_rows = conn.execute(
            """SELECT agent_id, trust_score
               FROM memory_records
               WHERE type = 'experience'
               AND project_id = ?
               ORDER BY timestamp DESC
               LIMIT 50""",
            (f"routing-{domain.value}",)
        ).fetchall()

        for row in mem_rows:
            experience_scores[row[0]].append(row[1])

        # ── Merge: Bayesian first, memory_records as supplement ──
        for model in models:
            model_id = model.model_id

            if model_id in bayesian_scores:
                # Primary: Bayesian-smoothed score
                model_scores[model_id] = bayesian_scores[model_id]
            else:
                # Try partial match in Bayesian scores
                matched_bayesian = False
                for bayes_mid, bayes_score in bayesian_scores.items():
                    if model_id in bayes_mid or bayes_mid in model_id:
                        model_scores[model_id] = bayes_score
                        matched_bayesian = True
                        break

                if not matched_bayesian:
                    # Fallback: memory_records experience
                    mem_list = experience_scores.get(model_id, [])
                    if not mem_list:
                        for agent_id, agent_scores in experience_scores.items():
                            if model_id in agent_id or agent_id in model_id:
                                mem_list = agent_scores
                                break

                    if mem_list:
                        weighted = []
                        for i, s in enumerate(reversed(mem_list)):
                            weight = 0.9 ** i
                            weighted.append(s * weight)
                        total_weight = sum(0.9 ** i for i in range(len(mem_list)))
                        model_scores[model_id] = sum(weighted) / total_weight
                    else:
                        # No data at all — use base quality score
                        model_scores[model_id] = model.quality_score

        # Domain-affinity boost: prefer models whose capabilities match domain
        for model in models:
            if domain.value in model.capabilities:
                model_scores[model.model_id] = min(
                    1.0, model_scores[model.model_id] + 0.2
                )

        self._cache[cache_key] = model_scores
        return model_scores

    def record_outcome(
        self,
        model_id: str,
        domain: TaskDomain,
        success: bool,
        duration_ms: float,
    ):
        """
        Record a task execution outcome for future scoring.

        Writes to BOTH backends:
          1. model_performance — UPSERT for Bayesian accumulation
          2. memory_records — Provenance trail for S-P-E-W hierarchy
        """
        conn = self.db.get_connection()

        # ── Backend 1: model_performance UPSERT ──
        if success:
            conn.execute(
                """INSERT INTO model_performance (model_id, task_class, success_count, failure_count, total_latency_ms)
                   VALUES (?, ?, 1, 0, ?)
                   ON CONFLICT(model_id, task_class) DO UPDATE SET
                       success_count = success_count + 1,
                       total_latency_ms = total_latency_ms + ?,
                       last_updated = CURRENT_TIMESTAMP""",
                (model_id, domain.value, duration_ms, duration_ms)
            )
        else:
            conn.execute(
                """INSERT INTO model_performance (model_id, task_class, success_count, failure_count, total_latency_ms)
                   VALUES (?, ?, 0, 1, ?)
                   ON CONFLICT(model_id, task_class) DO UPDATE SET
                       failure_count = failure_count + 1,
                       total_latency_ms = total_latency_ms + ?,
                       last_updated = CURRENT_TIMESTAMP""",
                (model_id, domain.value, duration_ms, duration_ms)
            )

        # ── Backend 2: memory_records provenance trail ──
        score = 1.0 if success else 0.0
        if success and duration_ms > 0:
            speed_score = max(0.0, min(1.0, 1000.0 / duration_ms))
            score = score * 0.7 + speed_score * 0.3

        paradigm_id = f"paradigm-{model_id}-{domain.value}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO memory_records
               (id, project_id, agent_id, type, trust_score, provenance, timestamp, consent)
               VALUES (?, ?, ?, 'experience', ?, ?, ?, 'granted')""",
            (
                paradigm_id,
                f"routing-{domain.value}",
                model_id,
                score,
                f"hermes-outcome:success={success},duration={duration_ms:.0f}ms",
                time.time(),
            )
        )
        conn.commit()

        # Invalidate cache for this domain
        self._cache.pop(domain.value, None)


class CostOptimizer:
    """Selects the cheapest model that meets the quality threshold."""

    def __init__(self, quality_threshold: float = 0.6):
        self.quality_threshold = quality_threshold

    def select(
        self,
        model_scores: Dict[str, float],
        models: List[ModelProfile],
        complexity: TaskComplexity,
    ) -> Tuple[str, float, str]:
        """
        Select the best model from scored candidates.

        Strategy:
          - TRIVIAL tasks: always pick cheapest model above threshold
          - STANDARD tasks: pick cheapest above threshold
          - COMPLEX tasks: pick best quality, ignore cost
          - CRITICAL tasks: pick best quality local model first, then best cloud

        Returns:
          (model_id, score, reason)
        """
        # Filter models above threshold
        candidates = [
            (mid, score)
            for mid, score in model_scores.items()
            if score >= self.quality_threshold
        ]

        if not candidates:
            # Fallback: pick the model with the highest score regardless
            best = max(model_scores.items(), key=lambda x: x[1])
            return best[0], best[1], f"Fallback: no model above threshold {self.quality_threshold}"

        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.CRITICAL):
            # Quality-first selection
            candidates.sort(key=lambda x: x[1], reverse=True)

            if complexity == TaskComplexity.CRITICAL:
                # Prefer local models for critical tasks
                local_models = {m.model_id: m for m in models if m.is_local or m.provider == "local"}
                for mid, score in candidates:
                    if mid in local_models:
                        return mid, score, f"Critical: best local model (score={score:.2f})"

            best_mid, best_score = candidates[0]
            return best_mid, best_score, f"Quality-first: score={best_score:.2f}"

        # Cost-optimized for TRIVIAL and STANDARD
        model_costs = {m.model_id: m.cost_per_token for m in models}
        candidates_with_cost = [
            (mid, score, model_costs.get(mid, float("inf")))
            for mid, score in candidates
        ]
        candidates_with_cost.sort(key=lambda x: (x[2], -x[1]))  # Cost ascending, score descending for ties

        cheapest_mid, cheapest_score, cheapest_cost = candidates_with_cost[0]
        return (
            cheapest_mid,
            cheapest_score,
            f"Cost-optimized: ${cheapest_cost:.6f}/1M tokens (score={cheapest_score:.2f})",
        )


class HermesRouter:
    """
    3-layer experience-based model router.

    Replaces naive round-robin with intelligent routing:
      1. Classify task (domain + complexity)
      2. Check for matching skills (fast path)
      3. Score models by experience
      4. Select cheapest model above quality threshold
    """

    def __init__(
        self,
        db: DatabaseManager,
        models: Optional[List[ModelProfile]] = None,
        quality_threshold: float = 0.6,
    ):
        self.db = db
        self.classifier = TaskClassifier()
        self.scorer = ExperienceScorer(db)
        self.optimizer = CostOptimizer(quality_threshold)
        self._models: Dict[str, ModelProfile] = {}
        self._skills: List[SkillRecord] = []
        self._decision_history: List[RoutingDecision] = []

        self._ensure_schema()

        if models:
            for m in models:
                self.register_model(m)

    def _ensure_schema(self):
        """Create model_performance table if missing (Bayesian scoring backend)."""
        conn = self.db.get_connection()
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

    def register_model(self, profile: ModelProfile):
        """Register a model available for routing."""
        self._models[profile.model_id] = profile

    def register_skill(self, skill: SkillRecord):
        """Register a reusable skill for fast-path routing."""
        self._skills.append(skill)

    def route(
        self,
        task_id: str,
        description: str,
        context: Optional[Dict] = None,
    ) -> RoutingDecision:
        """
        Route a task to the best available model.

        Returns:
            RoutingDecision with selected model, scores, and reasoning.
        """
        # Layer 1: Classify
        domain, complexity = self.classifier.classify(description, context)

        # Check for matching skill (fast path)
        matched_skill = self._match_skill(description, domain)
        if matched_skill:
            decision = RoutingDecision(
                task_id=task_id,
                selected_model=matched_skill.recommended_model,
                complexity=complexity,
                domain=domain,
                score=matched_skill.success_rate,
                cost_estimate=0,  # Calculated below
                reason=f"Fast-path skill match: {matched_skill.name} (rate={matched_skill.success_rate:.2f})",
                matched_skill=matched_skill.skill_id,
            )
            model = self._models.get(matched_skill.recommended_model)
            if model:
                decision.cost_estimate = model.cost_per_token / 1_000_000
            self._decision_history.append(decision)
            return decision

        # Layer 2: Score models by experience
        models = list(self._models.values())
        if not models:
            raise RuntimeError("No models registered in HermesRouter")

        scores = self.scorer.score(domain, models)

        # Layer 3: Cost-optimized selection
        selected_model, score, reason = self.optimizer.select(
            scores, models, complexity
        )

        model = self._models.get(selected_model)
        cost = model.cost_per_token / 1_000_000 if model else 0

        full_reason = f"{reason} | domain={domain.value}, complexity={complexity.value}"

        decision = RoutingDecision(
            task_id=task_id,
            selected_model=selected_model,
            complexity=complexity,
            domain=domain,
            score=score,
            cost_estimate=cost,
            reason=full_reason,
        )

        self._decision_history.append(decision)
        logger.info(
            "Hermes: %s → %s (%.2f) [%s/%s]",
            task_id, selected_model, score, domain.value, complexity.value
        )
        return decision

    def record_outcome(
        self,
        task_id: str,
        success: bool,
        duration_ms: float,
    ):
        """Record the outcome of a routed task for learning."""
        decision = self._find_decision(task_id)
        if decision:
            self.scorer.record_outcome(
                decision.selected_model, decision.domain, success, duration_ms
            )
            # Update matched skill if applicable
            if decision.matched_skill:
                self._update_skill_usage(decision.matched_skill, success)

    def _find_decision(self, task_id: str) -> Optional[RoutingDecision]:
        for d in reversed(self._decision_history):
            if d.task_id == task_id:
                return d
        return None

    def _match_skill(
        self, description: str, domain: TaskDomain
    ) -> Optional[SkillRecord]:
        """Check if any known skill matches this task.

        Skills are matched by pattern regex against the task description.
        Domain is not used as a strict filter because the classifier may
        disagree with the skill's task_type (e.g., 'deploy' classified as
        CODE but skill registered under OPERATIONS).
        """
        desc_lower = description.lower()
        for skill in self._skills:
            if skill.execution_count < 3:  # Need minimum experience
                continue
            if re.search(skill.pattern, desc_lower):
                return skill
        return None

    def _update_skill_usage(self, skill_id: str, success: bool):
        """Update a skill's stats after usage."""
        for skill in self._skills:
            if skill.skill_id == skill_id:
                total = skill.execution_count
                skill.success_rate = (
                    (skill.success_rate * total + (1.0 if success else 0.0))
                    / (total + 1)
                )
                skill.execution_count += 1
                skill.last_used = time.time()
                break

    def get_stats(self) -> Dict[str, Any]:
        """Return router statistics."""
        if not self._decision_history:
            return {"total_decisions": 0}

        domains = defaultdict(int)
        complexities = defaultdict(int)
        fast_paths = 0
        for d in self._decision_history:
            domains[d.domain.value] += 1
            complexities[d.complexity.value] += 1
            if d.matched_skill:
                fast_paths += 1

        return {
            "total_decisions": len(self._decision_history),
            "domains": dict(domains),
            "complexities": dict(complexities),
            "fast_path_matches": fast_paths,
            "fast_path_rate": fast_paths / len(self._decision_history),
            "models_registered": list(self._models.keys()),
            "skills_registered": len(self._skills),
        }

    def get_performance_data(self) -> List[Dict[str, Any]]:
        """Return raw model_performance table rows for introspection."""
        conn = self.db.get_connection()
        rows = conn.execute(
            """SELECT model_id, task_class, success_count, failure_count,
                      total_latency_ms, last_updated
               FROM model_performance
               ORDER BY last_updated DESC"""
        ).fetchall()
        return [
            {
                "model_id": r[0], "task_class": r[1],
                "success_count": r[2], "failure_count": r[3],
                "total_latency_ms": r[4], "last_updated": r[5],
            }
            for r in rows
        ]
