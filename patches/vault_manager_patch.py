"""
PATCH: vault/manager.py — Wire MINJA v2 Poisoning Detector

Apply this diff to your existing vault/manager.py file.
The MinjaDetector replaces the old negation-word heuristic.

BEFORE:
-------
def write_memory(self, project_id, agent_id, content, ...):
    # ... existing validation ...
    # Old poisoning check (v1 - negation words only):
    negation_words = ['not', 'no', 'never', ...]
    has_negation = any(w in content.lower() for w in negation_words)
    if has_negation and agent_trust < 0.5:
        raise PoisoningError("Negation detected from low-trust agent")
    # ... write to DB ...

AFTER:
------
from nexus_os.vault.poisoning import MinjaDetector, PoisoningError

class VaultManager:
    def __init__(self, db_manager, ...):
        # ... existing init ...
        self.poison_detector = MinjaDetector(
            velocity_threshold=10,       # max writes per agent per 60s
            window_seconds=60,           # velocity window
            similarity_threshold=0.4,    # TF-IDF cosine threshold
            contradiction_negation_boost=0.15,
            pattern_window=50,           # pattern analysis window
            pattern_anomaly_ratio=0.6,   # duplicate ratio threshold
        )

    def write_memory(self, project_id, agent_id, content, ...):
        # ... existing validation ...
        agent_trust = self.scorer.get_score(agent_id)
        is_safe, reason = self.poison_detector.validate_write(
            project_id, agent_id, content, agent_trust
        )
        if not is_safe:
            raise PoisoningError(reason)

        # ... write to DB ...
        # After successful insert:
        self.poison_detector.register_write(
            project_id, agent_id, content, trust_score
        )
        return record_id

NOTES:
------
- MinjaDetector is stateful; it builds a per-project TF-IDF index over time.
- The first few writes to any project will always pass (empty index).
- Velocity tracking resets after window_seconds.
- Pattern anomaly requires at least 5 writes before it starts checking.
- Trust score comes from the existing TrustScorer (0.0 to 1.0).
"""
