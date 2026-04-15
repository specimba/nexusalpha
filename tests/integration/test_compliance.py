"""
tests/integration/test_compliance.py — Compliance Engine Integration Tests

Tests OWASP ASI, CSA, IMDA, IETF VAP, KAIJU, and internal rule evaluation.
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.db.manager import DatabaseManager, DBConfig
from nexus_os.governor.compliance import (
    ComplianceEngine, ComplianceStatus, ComplianceLevel, RuleSource,
)


@pytest.fixture
def db():
    db_path = "test_compliance.db"
    db = DatabaseManager(db_path)
    yield db
    db.close_all()
    import time
    time.sleep(0.1)
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def engine(db):
    e = ComplianceEngine(db)
    e.load_default_rules()
    return e


class TestCompliantScenario:
    """A fully compliant action should pass all checks."""

    def test_full_compliance(self, engine):
        result = engine.evaluate(
            agent_id="agent-1",
            action="read",
            context={
                "signature_verified": True,
                "has_secret": True,
                "trace_id": "trace-123",
                "lineage_id": "lineage-456",
                "response_validated": True,
                "kaiju_authorized": True,
                "is_registered": True,
                "project_id": "proj-1",
                "target_project_id": "proj-1",
                "human_hold_required": False,
                "trust_score": 0.8,
                "encryption_enabled": True,
                "classification": "standard",
            },
            trace_id="trace-123",
        )
        assert result.is_compliant
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0
        assert len(result.warnings) == 0


class TestOWASPASI:
    def test_missing_authentication(self, engine):
        result = engine.evaluate("agent-x", "write", {"signature_verified": False, "has_secret": False})
        assert not result.is_compliant
        assert any(v.rule_id == "OWASP-ASI-01" for v in result.violations)

    def test_missing_poisoning_check(self, engine):
        result = engine.evaluate("agent-x", "write", {"poison_check_passed": False})
        assert any(v.rule_id == "OWASP-ASI-02" for v in result.violations)

    def test_missing_provenance(self, engine):
        result = engine.evaluate("agent-x", "read", {"trace_id": "", "lineage_id": ""})
        assert any(v.rule_id == "OWASP-ASI-03" for v in result.violations)

    def test_no_bypass_for_reads(self, engine):
        """Poisoning check should NOT apply to read actions."""
        result = engine.evaluate("agent-x", "read", {"poison_check_passed": False})
        # OWASP-ASI-02 should not fire for reads
        assert not any(v.rule_id == "OWASP-ASI-02" for v in result.violations)


class TestCSATrust:
    def test_unregistered_agent(self, engine):
        result = engine.evaluate("ghost", "read", {"is_registered": False})
        assert any(v.rule_id == "CSA-TRUST-01" for v in result.violations)

    def test_cross_project_blocked(self, engine):
        result = engine.evaluate(
            "agent-1", "read",
            {"project_id": "proj-a", "target_project_id": "proj-b", "clearance": "contributor"}
        )
        assert any(v.rule_id == "CSA-TRUST-02" for v in result.violations)

    def test_cross_project_allowed_for_admin(self, engine):
        result = engine.evaluate(
            "admin", "read",
            {
                "project_id": "proj-a", "target_project_id": "proj-b", "clearance": "admin",
                "signature_verified": True, "has_secret": True, "trace_id": "t", "lineage_id": "l",
                "kaiju_authorized": True, "is_registered": True,
                "response_validated": True, "encryption_enabled": True, "classification": "standard",
            }
        )
        # CSA-TRUST-02 should NOT fire for admin clearance
        assert not any(v.rule_id == "CSA-TRUST-02" for v in result.violations)


class TestIMDA:
    def test_critical_without_human_hold(self, engine):
        result = engine.evaluate(
            "agent-1", "delete",
            {"impact": "critical", "human_hold_required": False}
        )
        assert any(v.rule_id == "IMDA-01" for v in result.violations)

    def test_critical_with_human_hold_passes(self, engine):
        result = engine.evaluate(
            "agent-1", "delete",
            {
                "impact": "critical", "human_hold_required": True,
                "signature_verified": True, "has_secret": True, "trace_id": "t", "lineage_id": "l",
                "kaiju_authorized": True, "is_registered": True, "project_id": "p1",
                "response_validated": True, "encryption_enabled": True, "classification": "standard",
            }
        )
        assert not any(v.rule_id == "IMDA-01" for v in result.violations)


class TestIETEVAP:
    def test_missing_trace_in_audit(self, engine):
        result = engine.evaluate("agent-1", "read", {"trace_id": ""})
        assert any(v.rule_id == "IETF-VAP-01" for v in result.warnings)


class TestKAIJU:
    def test_missing_intent_for_write(self, engine):
        result = engine.evaluate("agent-1", "write", {"intent": ""})
        assert any(v.rule_id == "KAIJU-01" for v in result.violations)

    def test_short_intent_for_delete(self, engine):
        result = engine.evaluate("agent-1", "delete", {"intent": "remove"})
        assert any(v.rule_id == "KAIJU-01" for v in result.violations)

    def test_sufficient_intent_passes(self, engine):
        result = engine.evaluate(
            "agent-1", "delete",
            {
                "intent": "remove obsolete test records from the QA project as part of cleanup sprint",
                "signature_verified": True, "has_secret": True, "trace_id": "t", "lineage_id": "l",
                "kaiju_authorized": True, "is_registered": True, "project_id": "p1",
                "response_validated": True, "encryption_enabled": True, "classification": "standard",
            }
        )
        assert not any(v.rule_id == "KAIJU-01" for v in result.violations)


class TestInternalRules:
    def test_low_trust_warning(self, engine):
        result = engine.evaluate(
            "agent-1", "write",
            {
                "trust_score": 0.2,
                "signature_verified": True, "has_secret": True, "trace_id": "t", "lineage_id": "l",
                "poison_check_passed": True, "kaiju_authorized": True, "is_registered": True,
                "project_id": "p1", "response_validated": True, "encryption_enabled": True,
                "classification": "standard",
            }
        )
        assert any(v.rule_id == "NEXUS-01" for v in result.warnings)

    def test_critical_unencrypted(self, engine):
        result = engine.evaluate(
            "agent-1", "write",
            {
                "classification": "critical", "encryption_enabled": False,
                "signature_verified": True, "has_secret": True, "trace_id": "t", "lineage_id": "l",
                "poison_check_passed": True, "kaiju_authorized": True, "is_registered": True,
                "project_id": "p1", "response_validated": True,
            }
        )
        assert any(v.rule_id == "NEXUS-02" for v in result.violations)


class TestStatusDetermination:
    def test_critical_violation_blocks(self, engine):
        result = engine.evaluate(
            "ghost", "write",
            {"is_registered": False, "signature_verified": False}
        )
        # Multiple CRITICAL violations should result in BLOCKED status
        assert result.status in (ComplianceStatus.BLOCKED, ComplianceStatus.NON_COMPLIANT)

    def test_warnings_only_yield_warning_status(self, engine):
        result = engine.evaluate(
            "agent-1", "read",
            {
                "trace_id": "",
                "trust_score": 0.2,
                "signature_verified": True, "has_secret": True, "lineage_id": "l",
                "kaiju_authorized": True, "is_registered": True, "project_id": "p1",
                "response_validated": True, "encryption_enabled": True, "classification": "standard",
            }
        )
        assert result.status == ComplianceStatus.WARNING


class TestComplianceBadge:
    def test_badge_generation(self, engine):
        # Run a few evaluations
        engine.evaluate("a1", "read", {
            "signature_verified": True, "has_secret": True, "trace_id": "t",
            "lineage_id": "l", "kaiju_authorized": True, "is_registered": True,
            "project_id": "p1", "response_validated": True, "encryption_enabled": True,
            "classification": "standard",
        })
        badge = engine.generate_badge()
        assert badge["nexus_os_compliance"]["rules_loaded"] > 0
        assert badge["nexus_os_compliance"]["status"] in ("compliant", "attention_required")
        assert "OWASP ASI 2026" in badge["nexus_os_compliance"]["frameworks"]

    def test_custom_rule(self, engine):
        from nexus_os.governor.compliance import ComplianceRule
        engine.add_rule(ComplianceRule(
            rule_id="CUSTOM-01",
            name="Custom Test Rule",
            description="A custom rule for testing.",
            source=RuleSource.INTERNAL,
            level=ComplianceLevel.WARNING,
            check_fn="check_trust_threshold",
        ))
        badge = engine.generate_badge()
        assert badge["nexus_os_compliance"]["rules_loaded"] > 12


