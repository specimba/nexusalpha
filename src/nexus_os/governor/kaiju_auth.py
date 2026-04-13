"""
governor/kaiju_auth.py — KAIJU 4-Variable Authorization Extension

Source: arXiv:2604.02375 — KAIJU IGX (Intent-Gated Execution)
Priority: Phase 1 (URGENT — before any Phase 2 work)

This module extends the Nexus OS Governor with four authorization variables
inspired by KAIJU's Intent-Gated Execution kernel:

  1. SCOPE    — Which resources/entities are affected by the action
  2. INTENT   — Why the agent is performing the action (purpose)
  3. IMPACT   — Potential blast radius (low/medium/high/critical)
  4. CLEARANCE — Agent's authorization level (reader/contributor/admin)

The current Governor only checks project_id isolation + CVA trait matching.
This extension adds a mandatory 4-variable gate BEFORE any action is executed.

Integration: Import into governor/base.py and call check_access() instead of
the existing _is_authorized().
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class Decision(Enum):
    """Governor authorization decision."""
    ALLOW = "allow"
    DENY = "deny"
    HOLD = "hold"   # Requires human review
    HALT = "halt"   # Emergency stop


class ScopeLevel(Enum):
    """Resource scope granularity."""
    SELF = "self"               # Agent's own records only
    PROJECT = "project"         # All records in the project
    CROSS_PROJECT = "cross_project"  # Multiple projects
    SYSTEM = "system"           # System-wide (all projects, config, registry)


class ImpactLevel(Enum):
    """Potential blast radius of an action."""
    LOW = "low"                 # Read-only, no side effects
    MEDIUM = "medium"           # Modify one or few records
    HIGH = "high"               # Delete records, modify many entries
    CRITICAL = "critical"       # Delete project, system config, agent registry


class ClearanceLevel(Enum):
    """Agent authorization level (ascending)."""
    READER = "reader"           # Can read only
    CONTRIBUTOR = "contributor" # Can read + write own records
    MAINTAINER = "maintainer"   # Can read + write project records
    ADMIN = "admin"             # Full access including system-level


# Clearance hierarchy: higher level includes all permissions of lower levels
CLEARANCE_HIERARCHY = {
    ClearanceLevel.READER: 1,
    ClearanceLevel.CONTRIBUTOR: 2,
    ClearanceLevel.MAINTAINER: 3,
    ClearanceLevel.ADMIN: 4,
}

# Scope requirements per clearance level
SCOPE_LIMITS: Dict[ClearanceLevel, List[ScopeLevel]] = {
    ClearanceLevel.READER: [ScopeLevel.SELF, ScopeLevel.PROJECT],
    ClearanceLevel.CONTRIBUTOR: [ScopeLevel.SELF, ScopeLevel.PROJECT],
    ClearanceLevel.MAINTAINER: [ScopeLevel.SELF, ScopeLevel.PROJECT, ScopeLevel.CROSS_PROJECT],
    ClearanceLevel.ADMIN: [ScopeLevel.SELF, ScopeLevel.PROJECT, ScopeLevel.CROSS_PROJECT, ScopeLevel.SYSTEM],
}

# Impact requirements per clearance level
IMPACT_LIMITS: Dict[ClearanceLevel, List[ImpactLevel]] = {
    ClearanceLevel.READER: [ImpactLevel.LOW],
    ClearanceLevel.CONTRIBUTOR: [ImpactLevel.LOW, ImpactLevel.MEDIUM],
    ClearanceLevel.MAINTAINER: [ImpactLevel.LOW, ImpactLevel.MEDIUM, ImpactLevel.HIGH],
    ClearanceLevel.ADMIN: [ImpactLevel.LOW, ImpactLevel.MEDIUM, ImpactLevel.HIGH, ImpactLevel.CRITICAL],
}


@dataclass
class AuthRequest:
    """Authorization request with all 4 KAIJU variables."""
    agent_id: str
    project_id: str
    action: str              # e.g., "read", "write", "delete", "execute"
    scope: ScopeLevel
    intent: str              # Free-text description of why
    impact: ImpactLevel
    clearance: ClearanceLevel
    trace_id: Optional[str] = None


@dataclass
class AuthResult:
    """Authorization result."""
    decision: Decision
    reason: str
    trace_id: Optional[str] = None


class KaijuAuthorizer:
    """
    KAIJU-inspired 4-variable authorization engine.

    Evaluates every action against four dimensions:
      scope    x clearance  -> "Is this agent allowed to touch these resources?"
      intent   x action     -> "Does the stated purpose match the action type?"
      impact   x clearance  -> "Is this agent cleared for this blast radius?"

    Returns ALLOW, DENY, or HOLD (human review required).
    """

    # Actions that require explicit intent justification
    INTENT_SENSITIVE_ACTIONS = {"delete", "drop", "remove", "purge", "truncate", "halt", "suspend"}
    # Actions where intent should match the action type
    INTENT_ACTION_KEYWORDS = {
        "read": ["read", "fetch", "query", "search", "retrieve", "get", "view", "inspect", "check", "analyze"],
        "write": ["write", "create", "add", "insert", "update", "modify", "set", "save", "store"],
        "delete": ["delete", "remove", "clean", "purge", "clear", "drop"],
        "execute": ["execute", "run", "process", "compute", "transform", "generate"],
    }

    def __init__(self, require_intent_for: Optional[List[str]] = None):
        self._intent_sensitive = set(require_intent_for or self.INTENT_SENSITIVE_ACTIONS)
        self._hold_queue: List[AuthResult] = []

    def check_scope(self, scope: ScopeLevel, clearance: ClearanceLevel) -> tuple:
        """Check if clearance level permits the requested scope."""
        allowed = SCOPE_LIMITS.get(clearance, [])
        if scope in allowed:
            return True, "OK"
        return False, f"Clearance '{clearance.value}' does not permit scope '{scope.value}'. Allowed: {[s.value for s in allowed]}"

    def check_intent(self, intent: str, action: str) -> tuple:
        """
        Check if the stated intent is consistent with the action.
        HOLD (not DENY) when intent is suspicious — human review needed.
        """
        if not intent or len(intent.strip()) < 3:
            return False, "HOLD: Intent is empty or too short — requires human review"

        intent_lower = intent.lower()
        action_lower = action.lower()

        # For sensitive actions, intent must be more detailed
        if action_lower in self._intent_sensitive:
            if len(intent.strip()) < 10:
                return False, f"HOLD: Action '{action}' requires detailed intent justification (10+ chars)"

        # Check if intent keywords match action type
        keywords = self.INTENT_ACTION_KEYWORDS.get(action_lower, [])
        if keywords and not any(kw in intent_lower for kw in keywords):
            logger.warning(
                "Intent mismatch: action='%s', intent='%s', expected keywords=%s",
                action, intent, keywords
            )
            # Don't block — just flag for review
            return True, f"WARN: Intent keywords don't match action '{action}' — flagged for review"

        return True, "OK"

    def check_impact(self, impact: ImpactLevel, clearance: ClearanceLevel) -> tuple:
        """Check if clearance level permits the requested impact level."""
        allowed = IMPACT_LIMITS.get(clearance, [])
        if impact in allowed:
            return True, "OK"
        return False, f"Clearance '{clearance.value}' does not permit impact '{impact.value}'. Allowed: {[i.value for i in allowed]}"

    def authorize(self, request: AuthRequest) -> AuthResult:
        """
        Full 4-variable authorization check.
        Order: scope -> impact -> intent (intent last because HOLD is recoverable).
        """
        trace = request.trace_id

        # 1. Scope check
        scope_ok, scope_reason = self.check_scope(request.scope, request.clearance)
        if not scope_ok:
            return AuthResult(Decision.DENY, scope_reason, trace)

        # 2. Impact check
        impact_ok, impact_reason = self.check_impact(request.impact, request.clearance)
        if not impact_ok:
            return AuthResult(Decision.DENY, impact_reason, trace)

        # 3. Intent check (returns HOLD for suspicious, not DENY)
        intent_ok, intent_reason = self.check_intent(request.intent, request.action)
        if not intent_ok:
            result = AuthResult(Decision.HOLD, intent_reason, trace)
            self._hold_queue.append(result)
            return result

        return AuthResult(Decision.ALLOW, "All checks passed", trace)

    def get_hold_queue(self) -> List[AuthResult]:
        """Retrieve all items held for human review."""
        return list(self._hold_queue)

    def resolve_hold(self, trace_id: str, override_decision: Decision) -> bool:
        """
        Resolve a held request. Called by human operator.
        Returns True if the hold was found and resolved.
        """
        for i, item in enumerate(self._hold_queue):
            if item.trace_id == trace_id:
                self._hold_queue.pop(i)
                logger.info(
                    "Hold resolved: trace=%s, decision=%s",
                    trace_id, override_decision.value
                )
                return True
        return False


# ============================================================
# Integration Example for governor/base.py
# ============================================================
#
# from nexus_os.governor.kaiju_auth import (
#     KaijuAuthorizer, AuthRequest, AuthResult,
#     ScopeLevel, ImpactLevel, ClearanceLevel, Decision
# )
#
# class NexusGovernor:
#     def __init__(self, ...):
#         # ... existing init ...
#         self.kaiju = KaijuAuthorizer()
#
#     def check_access(self, agent_id, project_id, action,
#                      scope="project", intent="", impact="low",
#                      clearance="contributor"):
#         """
#         Extended access check with KAIJU 4-variable authorization.
#         Falls back to existing CVA check on ALLOW.
#         """
#         request = AuthRequest(
#             agent_id=agent_id,
#             project_id=project_id,
#             action=action,
#             scope=ScopeLevel(scope),
#             intent=intent,
#             impact=ImpactLevel(impact),
#             clearance=ClearanceLevel(clearance),
#         )
#         result = self.kaiju.authorize(request)
#
#         if result.decision == Decision.DENY:
#             return result
#         if result.decision == Decision.HOLD:
#             return result  # Queue for human review
#
#         # KAIJU passed — proceed to existing CVA trait check
#         if not self.verifier.verify_alignment(agent_id, action):
#             return AuthResult(Decision.HOLD, "CVA trait mismatch", request.trace_id)
#
#         return result
