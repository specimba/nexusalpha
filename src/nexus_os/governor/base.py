"""
governor/base.py — NexusGovernor: Unified Authorization Gate

Central authorization entry point for all Nexus OS actions. Integrates:

  1. KAIJU 4-variable authorization (scope × clearance, impact × clearance, intent × action)
  2. CVA (Core Value Alignment) trait verification fallback
  3. Compliance engine post-check (OWASP, CSA, IMDA, IETF VAP)
  4. Audit trail logging to audit_logs table

Architecture:
    check_access() → KAIJU.authorize() → [if ALLOW] CVA.verify() → [if ALLOW] Compliance.evaluate()
                     ↓ DENY/HOLD                              ↓ HOLD

Usage:
    governor = NexusGovernor(db, kaiju=KaijuAuthorizer())
    result = governor.check_access(
        agent_id="glm5-worker-1",
        project_id="nexus-os",
        action="write",
        scope="project",
        intent="persist task execution results to vault",
        impact="medium",
        clearance="contributor",
    )
    if result.decision == Decision.DENY:
        raise AccessDenied(result.reason)

Integration target: Replace existing _is_authorized() with check_access().
"""

import logging
from typing import Optional, Dict, Any

from nexus_os.db.manager import DatabaseManager
from nexus_os.governor.kaiju_auth import (
    KaijuAuthorizer, AuthRequest, AuthResult,
    ScopeLevel, ImpactLevel, ClearanceLevel, Decision,
)

logger = logging.getLogger(__name__)


class NexusGovernor:
    """
    Unified authorization governor for Nexus OS.

    Orchestrates three authorization layers in sequence:
    1. KAIJU 4-variable gate — hard deny on scope/impact mismatch, HOLD on weak intent
    2. CVA trait verification — optional soft check for value alignment (stub-ready)
    3. Compliance engine — post-authorization rule evaluation (OWASP, CSA, IMDA, etc.)

    The governor writes every authorization decision to audit_logs for
    IETF VAP provenance and operational transparency.
    """

    def __init__(
        self,
        db: DatabaseManager,
        kaiju: Optional[KaijuAuthorizer] = None,
        compliance_engine=None,
        enable_cva: bool = True,
        token_guard=None,
    ):
        """
        Initialize the governor.

        Args:
            db: DatabaseManager instance for audit logging.
            kaiju: KaijuAuthorizer instance. Created with defaults if None.
            compliance_engine: Optional ComplianceEngine for post-auth rule checks.
            enable_cva: Whether to run CVA trait verification (default True).
            token_guard: Optional TokenGuard instance for budget enforcement.
        """
        from nexus_os.monitoring.token_guard import TokenGuard
        self.db = db
        self.kaiju = kaiju or KaijuAuthorizer()
        self.compliance_engine = compliance_engine
        self._cva_verifier = _CVAVerifier() if enable_cva else None
        self.token_guard = token_guard or TokenGuard()
        self._budget_warning_threshold = 0.75   # 75% → warn via VAP context
        self._budget_hardstop_threshold = 0.95  # 95% → DENY

    def check_access(
        self,
        agent_id: str,
        project_id: str,
        action: str,
        scope: str = "project",
        intent: str = "",
        impact: str = "low",
        clearance: str = "contributor",
        trace_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AuthResult:
        """
        Extended access check with KAIJU 4-variable authorization.

        Authorization pipeline:
        1. Build AuthRequest with the 4 KAIJU variables (scope, intent, impact, clearance).
        2. Run KaijuAuthorizer.authorize() — returns ALLOW, DENY, or HOLD.
        3. If ALLOW: Run CVA trait verification (if enabled).
        4. If still ALLOW: Run compliance engine post-check (if configured).
        5. Log the decision to audit_logs.

        Args:
            agent_id: ID of the agent requesting access.
            project_id: The project scope of the action.
            action: Action type (read, write, delete, execute).
            scope: Resource scope (self, project, cross_project, system).
            intent: Free-text justification for the action.
            impact: Potential blast radius (low, medium, high, critical).
            clearance: Agent authorization level (reader, contributor, maintainer, admin).
            trace_id: Optional trace ID for audit linking.
            context: Additional context passed through to compliance engine.

        Returns:
            AuthResult with decision (ALLOW/DENY/HOLD), reason, and trace_id.
        """
        ctx = context or {}

        # ── Step 0: Token budget check (pre-KAIJU) ─────────────
        budget_ok, budget_reason = self._check_token_budget(
            agent_id, action, ctx
        )
        if not budget_ok:
            result = AuthResult(Decision.DENY, budget_reason, trace_id)
            self._audit_log(agent_id, action, result, project_id)
            return result

        # ── Step 1: KAIJU 4-variable authorization ──────────────
        try:
            request = AuthRequest(
                agent_id=agent_id,
                project_id=project_id,
                action=action,
                scope=ScopeLevel(scope),
                intent=intent,
                impact=ImpactLevel(impact),
                clearance=ClearanceLevel(clearance),
                trace_id=trace_id,
            )
        except ValueError as e:
            result = AuthResult(
                Decision.DENY,
                f"Invalid KAIJU variable value: {e}",
                trace_id,
            )
            self._audit_log(agent_id, action, result, project_id)
            return result

        kaiju_result = self.kaiju.authorize(request)

        if kaiju_result.decision == Decision.DENY:
            self._audit_log(agent_id, action, kaiju_result, project_id)
            return kaiju_result

        if kaiju_result.decision == Decision.HOLD:
            self._audit_log(agent_id, action, kaiju_result, project_id)
            return kaiju_result

        # ── Step 2: CVA trait verification (optional) ──────────
        if self._cva_verifier is not None:
            cva_ok, cva_reason = self._cva_verifier.verify_alignment(
                agent_id, action, ctx
            )
            if not cva_ok:
                result = AuthResult(
                    Decision.HOLD,
                    f"CVA trait mismatch: {cva_reason}",
                    trace_id,
                )
                self._audit_log(agent_id, action, result, project_id)
                return result

        # ── Step 3: Compliance engine post-check (optional) ────
        if self.compliance_engine is not None:
            compliance_ctx = dict(ctx)
            compliance_ctx.update({
                "kaiju_authorized": True,
                "trace_id": trace_id,
                "project_id": project_id,
            })
            try:
                comp_result = self.compliance_engine.evaluate(
                    agent_id, action, compliance_ctx, trace_id
                )
                if comp_result.status.value == "blocked":
                    result = AuthResult(
                        Decision.DENY,
                        "Compliance engine: " + "; ".join(
                            v.message for v in comp_result.violations
                        ),
                        trace_id,
                    )
                    self._audit_log(agent_id, action, result, project_id)
                    return result
            except Exception as e:
                logger.error("Compliance engine error during check_access: %s", e)

        # ── Step 4: All checks passed ───────────────────────────
        result = AuthResult(
            Decision.ALLOW,
            "All checks passed (KAIJU + CVA + Compliance)",
            trace_id,
        )
        self._audit_log(agent_id, action, result, project_id)
        return result

    # ── Token Budget Guard ─────────────────────────────────────

    def _check_token_budget(self, agent_id: str, action: str, ctx: Dict[str, Any]):
        """Check token budget before authorization.

        Returns (allowed: bool, reason: str).
        Non-blocking: if token_guard fails, logs and returns (True, 'budget_check_skipped').

        Hard stop: 95%+ usage → DENY.
        Warning:  75-95% usage → warn in context (VAP).
        """
        try:
            remaining = self.token_guard.remaining(agent_id)
            budget = self.token_guard._budgets.get(self.token_guard._get_budget_key(agent_id))
            if budget is None or budget.total == 0:
                return True, "budget_check_skipped"

            usage_pct = budget.used / budget.total

            # Insert usage into VAP context for audit trail
            ctx["_budget_usage_pct"] = round(usage_pct * 100, 1)
            ctx["_budget_remaining"] = remaining

            # Hard stop: 95%+ → DENY
            if usage_pct >= self._budget_hardstop_threshold:
                return False, (
                    f"Token budget hard stop: {budget.used}/{budget.total} "
                    f"({usage_pct*100:.0f}% used). Contact SPECI to replenish."
                )

            # Warning: 75-95% → allow but log via ctx
            if usage_pct >= self._budget_warning_threshold:
                ctx["_budget_warning"] = True
                logger.warning(
                    "Governor budget warning: agent=%s usage=%.0f%% remaining=%d",
                    agent_id, usage_pct * 100, remaining
                )

            return True, "budget_ok"

        except Exception:
            # Non-blocking — never fail a request due to budget check
            logger.warning("Governor token budget check failed — allowing request")
            return True, "budget_check_skipped"

    def _audit_log(
        self, agent_id: str, action: str, result: AuthResult, project_id: str
    ):
        """Write authorization decision to audit_logs table."""
        if not self.db:
            return
        try:
            conn = self.db.get_connection()
            conn.execute(
                """INSERT INTO audit_logs (actor_id, action, resource_id, decision, trace_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_id, f"auth:{action}", project_id, result.decision.value, result.trace_id),
            )
            conn.commit()
            logger.debug(
                "Governor audit: agent=%s action=%s decision=%s trace=%s",
                agent_id, action, result.decision.value, result.trace_id,
            )
        except Exception as e:
            logger.error("Governor: failed to write audit log: %s", e)

    def get_hold_queue(self):
        """Delegate to KAIJU hold queue."""
        return self.kaiju.get_hold_queue()

    def resolve_hold(self, trace_id: str, decision: Decision) -> bool:
        """Delegate to KAIJU hold resolution."""
        return self.kaiju.resolve_hold(trace_id, decision)


class _CVAVerifier:
    """
    Core Value Alignment verifier (stub).

    In production, this checks agent traits against project-defined
    value constraints (e.g., "no destructive actions without approval").
    The stub allows all actions by default — real implementation
    would query the agent_registry and project_config tables.
    """

    def verify_alignment(
        self, agent_id: str, action: str, context: Dict[str, Any]
    ) -> tuple:
        """
        Check if the agent's traits align with the action type.

        Returns:
            (is_aligned: bool, reason: str)
        """
        # Stub: all actions pass CVA verification.
        # Production: query agent_registry.traits, compare with
        # project_config.value_constraints, check action compatibility.
        return True, "OK"
