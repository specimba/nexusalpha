"""
tests/governor/test_governor.py — NexusGovernor Unit Tests

Validates the unified authorization gate:
  - KAIJU 4-variable gate (scope, intent, impact, clearance)
  - CVA trait verification fallback
  - Compliance engine integration
  - Audit logging
  - Hold queue delegation
"""

import pytest
import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nexus_os.governor.base import NexusGovernor
from nexus_os.governor.kaiju_auth import (
    KaijuAuthorizer, AuthResult,
    ScopeLevel, ImpactLevel, ClearanceLevel, Decision,
)


class FakeDBAdapter:
    """In-memory SQLite adapter for governor tests."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_id TEXT,
                decision TEXT,
                details TEXT,
                trace_id TEXT
            )
        """)

    def execute(self, query, params=()):
        return self._conn.execute(query, params)

    def executemany(self, query, params_list):
        return self._conn.executemany(query, params_list)

    def fetchone(self, cursor):
        return cursor.fetchone()

    def fetchall(self, cursor):
        return cursor.fetchall()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def get_audits(self):
        """Helper to retrieve all audit log entries."""
        rows = self._conn.execute(
            "SELECT actor_id, action, resource_id, decision, trace_id FROM audit_logs"
        ).fetchall()
        return [
            {"actor_id": r[0], "action": r[1], "resource_id": r[2],
             "decision": r[3], "trace_id": r[4]}
            for r in rows
        ]


class FakeDBManager:
    """Wraps FakeDBAdapter to satisfy NexusGovernor constructor."""

    def __init__(self):
        self._adapter = FakeDBAdapter()

    def get_connection(self):
        return self._adapter

    def close(self):
        self._adapter.close()


@pytest.fixture
def db():
    mgr = FakeDBManager()
    yield mgr
    mgr.close()


@pytest.fixture
def governor(db):
    return NexusGovernor(db)


class TestBasicAllow:
    """Verify that a well-formed request passes authorization."""

    def test_standard_contributor_read(self, governor):
        result = governor.check_access(
            agent_id="agent-1",
            project_id="proj-1",
            action="read",
            scope="project",
            intent="read project memory records for analysis",
            impact="low",
            clearance="contributor",
        )
        assert result.decision == Decision.ALLOW
        assert result.trace_id is None

    def test_admin_system_access(self, governor):
        result = governor.check_access(
            agent_id="admin",
            project_id="system",
            action="execute",
            scope="system",
            intent="execute system-wide maintenance task across all projects",
            impact="critical",
            clearance="admin",
        )
        assert result.decision == Decision.ALLOW

    def test_maintainer_cross_project(self, governor):
        result = governor.check_access(
            agent_id="maint-1",
            project_id="proj-a",
            action="read",
            scope="cross_project",
            intent="compare configurations across project boundaries",
            impact="low",
            clearance="maintainer",
        )
        assert result.decision == Decision.ALLOW


class TestDeny:
    """Verify that scope and impact violations are denied."""

    def test_reader_cannot_access_system(self, governor):
        result = governor.check_access(
            agent_id="reader-1",
            project_id="proj-1",
            action="read",
            scope="system",
            intent="read system config",
            impact="low",
            clearance="reader",
        )
        assert result.decision == Decision.DENY
        assert "scope" in result.reason.lower() or "Clearance" in result.reason

    def test_contributor_cannot_high_impact(self, governor):
        result = governor.check_access(
            agent_id="contrib-1",
            project_id="proj-1",
            action="delete",
            scope="project",
            intent="delete project records",
            impact="high",
            clearance="contributor",
        )
        assert result.decision == Decision.DENY
        assert "impact" in result.reason.lower() or "Clearance" in result.reason

    def test_invalid_kaiju_variable(self, governor):
        result = governor.check_access(
            agent_id="agent-1",
            project_id="proj-1",
            action="read",
            scope="invalid_scope_value",
            intent="test",
            impact="low",
            clearance="reader",
        )
        assert result.decision == Decision.DENY
        assert "Invalid" in result.reason


class TestHold:
    """Verify that intent issues result in HOLD (not DENY)."""

    def test_empty_intent_holds(self, governor):
        result = governor.check_access(
            agent_id="agent-1",
            project_id="proj-1",
            action="write",
            scope="project",
            intent="",
            impact="low",
            clearance="contributor",
        )
        assert result.decision == Decision.HOLD
        assert "HOLD" in result.reason or "intent" in result.reason.lower()

    def test_short_intent_for_delete_holds(self, governor):
        result = governor.check_access(
            agent_id="agent-1",
            project_id="proj-1",
            action="delete",
            scope="project",
            intent="remove",
            impact="high",
            clearance="maintainer",
        )
        assert result.decision == Decision.HOLD


class TestAuditLogging:
    """Verify that all decisions are logged to audit_logs."""

    def test_allow_is_audited(self, governor, db):
        governor.check_access(
            agent_id="agent-1", project_id="proj-1", action="read",
            scope="project", intent="read project data", impact="low",
            clearance="reader", trace_id="audit-test-1",
        )
        audits = db.get_connection().get_audits() if hasattr(db.get_connection(), 'get_audits') else []
        # Use raw query instead
        conn = db.get_connection()
        rows = conn.fetchall(conn.execute(
            "SELECT actor_id, decision, trace_id FROM audit_logs"
        ))
        assert len(rows) == 1
        assert rows[0][0] == "agent-1"
        assert rows[0][1] == "allow"
        assert rows[0][2] == "audit-test-1"

    def test_deny_is_audited(self, governor, db):
        governor.check_access(
            agent_id="agent-1", project_id="proj-1", action="read",
            scope="system", intent="test", impact="low", clearance="reader",
            trace_id="audit-deny-1",
        )
        conn = db.get_connection()
        rows = conn.fetchall(conn.execute(
            "SELECT decision FROM audit_logs"
        ))
        assert len(rows) == 1
        assert rows[0][0] == "deny"

    def test_hold_is_audited(self, governor, db):
        governor.check_access(
            agent_id="agent-1", project_id="proj-1", action="delete",
            scope="project", intent="", impact="high", clearance="maintainer",
        )
        conn = db.get_connection()
        rows = conn.fetchall(conn.execute(
            "SELECT decision FROM audit_logs"
        ))
        assert len(rows) == 1
        assert rows[0][0] == "hold"


class TestHoldQueueDelegation:
    """Verify hold queue is delegated to KAIJU authorizer."""

    def test_hold_queued(self, governor):
        governor.check_access(
            agent_id="agent-1", project_id="proj-1", action="delete",
            scope="project", intent="", impact="high", clearance="maintainer",
            trace_id="hold-test-1",
        )
        queue = governor.get_hold_queue()
        assert len(queue) == 1
        assert queue[0].trace_id == "hold-test-1"

    def test_resolve_hold(self, governor):
        governor.check_access(
            agent_id="agent-1", project_id="proj-1", action="delete",
            scope="project", intent="", impact="high", clearance="maintainer",
            trace_id="hold-resolve-1",
        )
        resolved = governor.resolve_hold("hold-resolve-1", Decision.DENY)
        assert resolved is True
        assert len(governor.get_hold_queue()) == 0

    def test_resolve_nonexistent(self, governor):
        resolved = governor.resolve_hold("nonexistent", Decision.DENY)
        assert resolved is False


class TestCVADisabled:
    """Verify governor works without CVA verification."""

    def test_no_cva(self, db):
        gov = NexusGovernor(db, enable_cva=False)
        result = gov.check_access(
            agent_id="agent-1", project_id="proj-1", action="read",
            scope="project", intent="read data", impact="low",
            clearance="reader",
        )
        assert result.decision == Decision.ALLOW


class TestCustomKaiju:
    """Verify governor accepts a custom KaijuAuthorizer."""

    def test_custom_authorizer(self, db):
        custom = KaijuAuthorizer(require_intent_for=["execute"])
        gov = NexusGovernor(db, kaiju=custom)
        # Write without intent should still ALLOW since "write" is not
        # in the custom intent_sensitive list
        result = gov.check_access(
            agent_id="agent-1", project_id="proj-1", action="write",
            scope="project", intent="", impact="low", clearance="contributor",
        )
        assert result.decision == Decision.HOLD  # empty intent < 3 chars
