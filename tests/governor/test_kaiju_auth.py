"""
tests/governor/test_kaiju_auth.py — KAIJU 4-Variable Authorization Tests

Validates the KaijuAuthorizer:
  - Scope x Clearance checks
  - Impact x Clearance checks
  - Intent x Action consistency checks
  - Full authorize() pipeline
  - Hold queue management
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.governor.kaiju_auth import (
    KaijuAuthorizer, AuthRequest, AuthResult,
    ScopeLevel, ImpactLevel, ClearanceLevel, Decision,
)


def _make_request(agent_id="agent-1", project_id="proj-1", action="read",
                  scope=ScopeLevel.PROJECT, intent="read the project memory records",
                  impact=ImpactLevel.LOW, clearance=ClearanceLevel.CONTRIBUTOR,
                  trace_id="test-trace"):
    return AuthRequest(
        agent_id=agent_id,
        project_id=project_id,
        action=action,
        scope=scope,
        intent=intent,
        impact=impact,
        clearance=clearance,
        trace_id=trace_id,
    )


class TestScopeCheck:
    """Test scope x clearance authorization."""

    def test_reader_can_access_project(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_scope(ScopeLevel.PROJECT, ClearanceLevel.READER)
        assert ok is True

    def test_reader_cannot_access_cross_project(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_scope(ScopeLevel.CROSS_PROJECT, ClearanceLevel.READER)
        assert ok is False
        assert "cross_project" in reason

    def test_reader_cannot_access_system(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_scope(ScopeLevel.SYSTEM, ClearanceLevel.READER)
        assert ok is False

    def test_admin_can_access_system(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_scope(ScopeLevel.SYSTEM, ClearanceLevel.ADMIN)
        assert ok is True

    def test_maintainer_can_access_cross_project(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_scope(ScopeLevel.CROSS_PROJECT, ClearanceLevel.MAINTAINER)
        assert ok is True

    def test_contributor_cannot_access_system(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_scope(ScopeLevel.SYSTEM, ClearanceLevel.CONTRIBUTOR)
        assert ok is False


class TestImpactCheck:
    """Test impact x clearance authorization."""

    def test_reader_can_low_impact(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_impact(ImpactLevel.LOW, ClearanceLevel.READER)
        assert ok is True

    def test_reader_cannot_medium_impact(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_impact(ImpactLevel.MEDIUM, ClearanceLevel.READER)
        assert ok is False
        assert "medium" in reason

    def test_contributor_can_medium_impact(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_impact(ImpactLevel.MEDIUM, ClearanceLevel.CONTRIBUTOR)
        assert ok is True

    def test_contributor_cannot_high_impact(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_impact(ImpactLevel.HIGH, ClearanceLevel.CONTRIBUTOR)
        assert ok is False

    def test_admin_can_critical_impact(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_impact(ImpactLevel.CRITICAL, ClearanceLevel.ADMIN)
        assert ok is True


class TestIntentCheck:
    """Test intent x action consistency checks."""

    def test_matching_intent_passes(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_intent("read the project files", "read")
        assert ok is True

    def test_empty_intent_fails(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_intent("", "read")
        assert ok is False
        assert "HOLD" in reason

    def test_short_intent_for_delete_holds(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_intent("remove", "delete")
        assert ok is False
        assert "HOLD" in reason
        assert "10+ chars" in reason

    def test_detailed_delete_intent_passes(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_intent("remove obsolete test records from the QA project", "delete")
        assert ok is True

    def test_mismatched_intent_warns(self):
        auth = KaijuAuthorizer()
        ok, reason = auth.check_intent("execute the code analysis pipeline", "read")
        # Should pass but warn (intent keywords don't match read)
        assert ok is True
        assert "WARN" in reason

    def test_write_intent_matches(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_intent("write new memory records to the vault", "write")
        assert ok is True

    def test_execute_intent_matches(self):
        auth = KaijuAuthorizer()
        ok, _ = auth.check_intent("run the data transformation pipeline", "execute")
        assert ok is True


class TestAuthorize:
    """Full authorization pipeline tests."""

    def test_full_allow(self):
        auth = KaijuAuthorizer()
        req = _make_request()
        result = auth.authorize(req)
        assert result.decision == Decision.ALLOW
        assert result.reason == "All checks passed"

    def test_scope_deny(self):
        auth = KaijuAuthorizer()
        req = _make_request(
            scope=ScopeLevel.SYSTEM,
            clearance=ClearanceLevel.READER,
        )
        result = auth.authorize(req)
        assert result.decision == Decision.DENY
        assert "scope" in result.reason.lower() or "Clearance" in result.reason

    def test_impact_deny(self):
        auth = KaijuAuthorizer()
        req = _make_request(
            impact=ImpactLevel.CRITICAL,
            clearance=ClearanceLevel.CONTRIBUTOR,
        )
        result = auth.authorize(req)
        assert result.decision == Decision.DENY
        assert "impact" in result.reason.lower() or "Clearance" in result.reason

    def test_intent_hold(self):
        auth = KaijuAuthorizer()
        req = _make_request(intent="")
        result = auth.authorize(req)
        assert result.decision == Decision.HOLD

    def test_admin_full_access(self):
        auth = KaijuAuthorizer()
        req = _make_request(
            action="delete",
            scope=ScopeLevel.SYSTEM,
            intent="purge all deprecated system configuration entries",
            impact=ImpactLevel.CRITICAL,
            clearance=ClearanceLevel.ADMIN,
        )
        result = auth.authorize(req)
        assert result.decision == Decision.ALLOW


class TestHoldQueue:
    """Test hold queue management."""

    def test_hold_is_queued(self):
        auth = KaijuAuthorizer()
        req = _make_request(intent="")
        auth.authorize(req)
        queue = auth.get_hold_queue()
        assert len(queue) == 1
        assert queue[0].trace_id == "test-trace"

    def test_resolve_hold(self):
        auth = KaijuAuthorizer()
        req = _make_request(intent="", action="delete")
        auth.authorize(req)
        resolved = auth.resolve_hold("test-trace", Decision.DENY)
        assert resolved is True
        assert len(auth.get_hold_queue()) == 0

    def test_resolve_nonexistent_hold(self):
        auth = KaijuAuthorizer()
        resolved = auth.resolve_hold("nonexistent", Decision.DENY)
        assert resolved is False

    def test_multiple_holds(self):
        auth = KaijuAuthorizer()
        for i in range(3):
            req = _make_request(intent="", trace_id=f"hold-{i}")
            auth.authorize(req)
        assert len(auth.get_hold_queue()) == 3
        auth.resolve_hold("hold-1", Decision.ALLOW)
        assert len(auth.get_hold_queue()) == 2
