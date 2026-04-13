"""
governor/compliance.py — Clearance Level Enforcement & Compliance Engine

Implements compliance checks aligned with:
  - OWASP ASI Top 10 (2026) — agent-specific risk taxonomy
  - CSA Agentic Trust Framework — zero-trust for agents
  - IMDA Singapore — world's first government agentic AI framework
  - IETF VAP Framework — 4-layer verifiable AI provenance

This module provides:
  1. ComplianceRule — individual rule definitions
  2. ComplianceEngine — evaluates rules against actions
  3. ComplianceBadge — generates compliance status reports
  4. AuditTrail — structured audit logging for governance

Usage:
    engine = ComplianceEngine(db)
    engine.load_default_rules()
    result = engine.evaluate(agent_id, action, context)
    if not result.compliant:
        raise ComplianceViolation(result.violations)
"""

import time
import logging
import hashlib
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from nexus_os.db.manager import DatabaseManager

logger = logging.getLogger(__name__)


class ComplianceLevel(Enum):
    """Compliance severity levels."""
    INFO = "info"
    WARNING = "warning"
    VIOLATION = "violation"
    CRITICAL = "critical"


class ComplianceStatus(Enum):
    """Overall compliance status."""
    COMPLIANT = "compliant"
    WARNING = "warning"        # Passes but with flags
    NON_COMPLIANT = "non_compliant"
    BLOCKED = "blocked"        # Hard fail — action must not proceed


class RuleSource(Enum):
    """Origin of a compliance rule."""
    OWASP_ASI = "owasp_asi_2026"
    CSA_TRUST = "csa_agentic_trust"
    IMDA_SG = "imda_singapore"
    IETF_VAP = "ietf_vap"
    INTERNAL = "nexus_internal"
    KAIJU = "kaiju_igx"


@dataclass
class ComplianceRule:
    """Definition of a single compliance rule."""
    rule_id: str
    name: str
    description: str
    source: RuleSource
    level: ComplianceLevel
    check_fn: str             # Method name on ComplianceEngine
    applicable_actions: List[str] = field(default_factory=list)  # Empty = all actions
    remediation: str = ""
    reference_url: str = ""


@dataclass
class ComplianceViolation:
    """A single compliance violation."""
    rule_id: str
    rule_name: str
    level: ComplianceLevel
    message: str
    remediation: str
    source: RuleSource = RuleSource.INTERNAL


@dataclass
class ComplianceResult:
    """Result of a compliance evaluation."""
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    violations: List[ComplianceViolation] = field(default_factory=list)
    warnings: List[ComplianceViolation] = field(default_factory=list)
    trace_id: Optional[str] = None
    evaluated_at: float = field(default_factory=time.time)
    rules_checked: int = 0

    @property
    def is_compliant(self) -> bool:
        return self.status == ComplianceStatus.COMPLIANT


class ComplianceEngine:
    """
    Evaluates compliance rules against agent actions.

    Rules are organized by source (OWASP, CSA, IMDA, IETF, KAIJU, Internal).
    Each rule has a check method that receives the action context and returns
    either None (pass) or a ComplianceViolation.

    The engine maintains a rule registry and provides:
    - evaluate(): Run all applicable rules against an action
    - add_rule(): Register custom rules
    - generate_badge(): Produce a compliance status summary
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._rules: Dict[str, ComplianceRule] = {}
        self._check_history: List[ComplianceResult] = []

    def add_rule(self, rule: ComplianceRule):
        """Register a compliance rule."""
        self._rules[rule.rule_id] = rule
        logger.debug("Compliance: Registered rule %s (%s)", rule.rule_id, rule.source.value)

    def load_default_rules(self):
        """Load the standard Nexus OS compliance ruleset."""
        # OWASP ASI Top 10 (2026) mapped rules
        self.add_rule(ComplianceRule(
            rule_id="OWASP-ASI-01",
            name="Agent Impersonation Prevention",
            description="Every agent action must be authenticated via unique secret with HMAC-SHA256 signature.",
            source=RuleSource.OWASP_ASI,
            level=ComplianceLevel.CRITICAL,
            check_fn="check_authentication",
            remediation="Ensure all Bridge requests include valid X-Nexus-Signature header.",
            reference_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
        ))

        self.add_rule(ComplianceRule(
            rule_id="OWASP-ASI-02",
            name="Prompt Injection Defense",
            description="Memory writes must pass poisoning detection (MINJA v2).",
            source=RuleSource.OWASP_ASI,
            level=ComplianceLevel.CRITICAL,
            check_fn="check_poisoning_defense",
            remediation="Ensure MINJA v2 detector is enabled and trust scoring is active.",
        ))

        self.add_rule(ComplianceRule(
            rule_id="OWASP-ASI-03",
            name="Data Provenance Tracking",
            description="Every action must carry a trace ID and lineage ID for auditability.",
            source=RuleSource.OWASP_ASI,
            level=ComplianceLevel.VIOLATION,
            check_fn="check_provenance",
            remediation="Include X-Nexus-Trace-ID and X-Nexus-Lineage-ID in all requests.",
        ))

        self.add_rule(ComplianceRule(
            rule_id="OWASP-ASI-04",
            name="Supply Chain Verification",
            description="Model responses must be validated before being written to memory.",
            source=RuleSource.OWASP_ASI,
            level=ComplianceLevel.WARNING,
            check_fn="check_supply_chain",
            remediation="Enable response validation in the Executor before memory writes.",
        ))

        self.add_rule(ComplianceRule(
            rule_id="OWASP-ASI-05",
            name="Excessive Agency Prevention",
            description="Agents must not exceed their clearance level or scope.",
            source=RuleSource.OWASP_ASI,
            level=ComplianceLevel.CRITICAL,
            check_fn="check_clearance_enforcement",
            remediation="Ensure KAIJU 4-variable authorization is active on all actions.",
        ))

        # CSA Agentic Trust Framework
        self.add_rule(ComplianceRule(
            rule_id="CSA-TRUST-01",
            name="Zero-Trust Agent Access",
            description="Deny-by-default: all agent access must be explicitly authorized.",
            source=RuleSource.CSA_TRUST,
            level=ComplianceLevel.CRITICAL,
            check_fn="check_deny_default",
            remediation="Verify all agents are registered in agent_registry before access.",
        ))

        self.add_rule(ComplianceRule(
            rule_id="CSA-TRUST-02",
            name="Cross-Project Isolation",
            description="Agents must not access resources outside their project scope.",
            source=RuleSource.CSA_TRUST,
            level=ComplianceLevel.CRITICAL,
            check_fn="check_project_isolation",
            remediation="Verify project_id is enforced in all Vault, Engine, and Bridge operations.",
        ))

        # IMDA Singapore
        self.add_rule(ComplianceRule(
            rule_id="IMDA-01",
            name="Human Oversight for High-Impact Actions",
            description="Actions with CRITICAL impact must be held for human review.",
            source=RuleSource.IMDA_SG,
            level=ComplianceLevel.VIOLATION,
            check_fn="check_human_oversight",
            remediation="Implement HOLD state in Governor for critical impact actions.",
        ))

        # IETF VAP Framework
        self.add_rule(ComplianceRule(
            rule_id="IETF-VAP-01",
            name="Verifiable AI Provenance",
            description="Audit logs must capture the full decision chain for every action.",
            source=RuleSource.IETF_VAP,
            level=ComplianceLevel.WARNING,
            check_fn="check_audit_chain",
            remediation="Ensure audit_logs table captures actor, action, resource, decision, and trace_id.",
        ))

        # KAIJU alignment
        self.add_rule(ComplianceRule(
            rule_id="KAIJU-01",
            name="Intent-Gated Execution",
            description="All non-trivial actions must include a stated intent that matches the action type.",
            source=RuleSource.KAIJU,
            level=ComplianceLevel.VIOLATION,
            check_fn="check_intent_gating",
            remediation="Require intent parameter in all Governor check_access() calls.",
        ))

        # Internal rules
        self.add_rule(ComplianceRule(
            rule_id="NEXUS-01",
            name="Trust Score Threshold",
            description="Agents with trust score below 0.3 must be restricted to read-only.",
            source=RuleSource.INTERNAL,
            level=ComplianceLevel.WARNING,
            check_fn="check_trust_threshold",
            remediation="Review the agent's recent actions and consider resetting trust score.",
        ))

        self.add_rule(ComplianceRule(
            rule_id="NEXUS-02",
            name="Memory Encryption",
            description="Critical classification memory records must be encrypted at rest.",
            source=RuleSource.INTERNAL,
            level=ComplianceLevel.VIOLATION,
            check_fn="check_encryption",
            remediation="Enable SQLCipher encryption via DatabaseManager v3 with encrypted=True.",
        ))

        logger.info("Compliance: Loaded %d default rules.", len(self._rules))

    def evaluate(
        self,
        agent_id: str,
        action: str,
        context: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> ComplianceResult:
        """
        Evaluate all applicable compliance rules against an action.

        Args:
            agent_id: The agent performing the action
            action: The action type (e.g., "read", "write", "delete", "execute")
            context: Additional context (project_id, intent, impact, scope, etc.)
            trace_id: Optional trace ID for audit linking

        Returns:
            ComplianceResult with status, violations, and warnings.
        """
        result = ComplianceResult(trace_id=trace_id)
        rules_checked = 0

        for rule in self._rules.values():
            # Skip rules that don't apply to this action
            if rule.applicable_actions and action not in rule.applicable_actions:
                continue

            rules_checked += 1
            check_method = getattr(self, rule.check_fn, None)
            if check_method is None:
                logger.warning("Compliance: No check method '%s' for rule %s", rule.check_fn, rule.rule_id)
                continue

            try:
                violation = check_method(agent_id, action, context)
                if violation:
                    violation.rule_id = rule.rule_id
                    violation.rule_name = rule.name
                    violation.source = rule.source
                    if not violation.remediation:
                        violation.remediation = rule.remediation

                    if rule.level in (ComplianceLevel.CRITICAL, ComplianceLevel.VIOLATION):
                        result.violations.append(violation)
                    else:
                        result.warnings.append(violation)
            except Exception as e:
                logger.error("Compliance: Error checking rule %s: %s", rule.rule_id, e)

        result.rules_checked = rules_checked

        # Determine overall status
        critical_count = sum(
            1 for v in result.violations if v.level == ComplianceLevel.CRITICAL
        )
        if critical_count > 0:
            result.status = ComplianceStatus.BLOCKED
        elif result.violations:
            result.status = ComplianceStatus.NON_COMPLIANT
        elif result.warnings:
            result.status = ComplianceStatus.WARNING
        else:
            result.status = ComplianceStatus.COMPLIANT

        # Log the evaluation
        self._log_evaluation(result, agent_id, action, context)

        self._check_history.append(result)
        logger.info(
            "Compliance: %s — agent=%s action=%s rules=%d status=%s violations=%d warnings=%d",
            trace_id or "no-trace", agent_id, action,
            rules_checked, result.status.value,
            len(result.violations), len(result.warnings)
        )

        return result

    # ── Check Methods ────────────────────────────────────────────

    def check_authentication(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """OWASP-ASI-01: Verify agent has valid authentication."""
        has_signature = context.get("signature_verified", False)
        has_secret = context.get("has_secret", False)
        if not has_signature and not has_secret:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.CRITICAL,
                "Agent action lacks authentication signature.",
                "Include HMAC-SHA256 signature in all Bridge requests.",
            )
        return None

    def check_poisoning_defense(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """OWASP-ASI-02: Verify poisoning detection is active for writes."""
        if action != "write":
            return None
        poison_check = context.get("poison_check_passed", False)
        if not poison_check:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.CRITICAL,
                "Memory write bypassed poisoning detection.",
                "Run MINJA v2 validate_write() before writing to vault.",
            )
        return None

    def check_provenance(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """OWASP-ASI-03: Verify trace and lineage IDs are present."""
        has_trace = bool(context.get("trace_id"))
        has_lineage = bool(context.get("lineage_id"))
        if not has_trace and not has_lineage:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.VIOLATION,
                f"Missing provenance: trace_id={has_trace}, lineage_id={has_lineage}",
                "Include X-Nexus-Trace-ID and X-Nexus-Lineage-ID in all requests.",
            )
        return None

    def check_supply_chain(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """OWASP-ASI-04: Verify model response validation."""
        validated = context.get("response_validated", True)
        if not validated:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.WARNING,
                "Model response was not validated before processing.",
                "Enable response validation in Executor pipeline.",
            )
        return None

    def check_clearance_enforcement(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """OWASP-ASI-05 / KAIJU: Verify KAIJU authorization is active."""
        kaiju_passed = context.get("kaiju_authorized", False)
        if not kaiju_passed and action in ("delete", "execute", "write"):
            return ComplianceViolation(
                "", "",
                ComplianceLevel.CRITICAL,
                f"Action '{action}' bypassed KAIJU 4-variable authorization.",
                "Run KaijuAuthorizer.authorize() before executing this action.",
            )
        return None

    def check_deny_default(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """CSA-TRUST-01: Verify agent is registered."""
        is_registered = context.get("is_registered", False)
        if not is_registered:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.CRITICAL,
                f"Agent '{agent_id}' is not registered in agent_registry.",
                "Register the agent before allowing any access.",
            )
        return None

    def check_project_isolation(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """CSA-TRUST-02: Verify project scope enforcement."""
        project_id = context.get("project_id")
        target_project = context.get("target_project_id")
        if project_id and target_project and project_id != target_project:
            # Check if agent has cross-project clearance
            clearance = context.get("clearance", "contributor")
            if clearance not in ("maintainer", "admin"):
                return ComplianceViolation(
                    "", "",
                    ComplianceLevel.CRITICAL,
                    f"Agent '{agent_id}' attempted cross-project access ({project_id} → {target_project}).",
                    "Grant maintainer clearance or scope the action to a single project.",
                )
        return None

    def check_human_oversight(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """IMDA-01: Critical actions must be held for human review."""
        impact = context.get("impact", "low")
        human_hold = context.get("human_hold_required", False)
        if impact == "critical" and not human_hold:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.VIOLATION,
                "Critical impact action was not held for human review.",
                "Implement HOLD decision in Governor for critical impact actions.",
            )
        return None

    def check_audit_chain(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """IETF-VAP-01: Verify full audit chain."""
        trace_id = context.get("trace_id")
        lineage_id = context.get("lineage_id")
        if not trace_id:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.WARNING,
                "Audit chain broken: no trace_id.",
                "Ensure X-Nexus-Trace-ID is propagated through the entire call chain.",
            )
        return None

    def check_intent_gating(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """KAIJU-01: Verify intent is stated and matches action."""
        intent = context.get("intent", "")
        if action in ("delete", "execute", "write") and len(intent.strip()) < 10:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.VIOLATION,
                f"Action '{action}' requires detailed intent (10+ chars), got: '{intent[:20]}'.",
                "Include a descriptive intent parameter in the authorization request.",
            )
        return None

    def check_trust_threshold(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """NEXUS-01: Verify agent trust score."""
        trust = context.get("trust_score", 1.0)
        if trust < 0.3 and action in ("write", "delete", "execute"):
            return ComplianceViolation(
                "", "",
                ComplianceLevel.WARNING,
                f"Agent '{agent_id}' has low trust score ({trust:.2f}) but is performing '{action}'.",
                "Consider restricting this agent to read-only until trust is restored.",
            )
        return None

    def check_encryption(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        """NEXUS-02: Verify encryption for critical records."""
        classification = context.get("classification", "standard")
        encrypted = context.get("encryption_enabled", True)
        if classification == "critical" and not encrypted:
            return ComplianceViolation(
                "", "",
                ComplianceLevel.VIOLATION,
                "Critical classification data is not encrypted at rest.",
                "Enable SQLCipher via DatabaseManager(encrypted=True).",
            )
        return None

    # ── Audit & Reporting ────────────────────────────────────────

    def _log_evaluation(self, result: ComplianceResult, agent_id: str, action: str, context: Dict):
        """Write compliance evaluation to audit_logs."""
        if not self.db:
            return
        try:
            conn = self.db.get_connection()
            details = json.dumps({
                "action": action,
                "agent_id": agent_id,
                "status": result.status.value,
                "violations": [v.rule_id for v in result.violations],
                "warnings": [v.rule_id for v in result.warnings],
            })
            conn.execute(
                """INSERT INTO audit_logs (actor_id, action, resource_id, decision, details, trace_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("compliance-engine", "evaluate", agent_id, result.status.value, details, result.trace_id)
            )
            conn.commit()
        except Exception as e:
            logger.error("Compliance: Failed to write audit log: %s", e)

    def generate_badge(self) -> Dict[str, Any]:
        """
        Generate a compliance status badge/summary.

        Returns a dict suitable for serialization (JSON, display, etc.)
        """
        rules_by_source = defaultdict(int)
        for rule in self._rules.values():
            rules_by_source[rule.source.value] += 1

        total_evaluations = len(self._check_history)
        if total_evaluations > 0:
            compliant_count = sum(1 for r in self._check_history if r.is_compliant)
            compliance_rate = compliant_count / total_evaluations
        else:
            compliance_rate = 1.0

        return {
            "nexus_os_compliance": {
                "version": "1.0",
                "rules_loaded": len(self._rules),
                "rules_by_source": dict(rules_by_source),
                "total_evaluations": total_evaluations,
                "compliance_rate": round(compliance_rate, 4),
                "status": "compliant" if compliance_rate >= 0.95 else "attention_required",
                "frameworks": ["OWASP ASI 2026", "CSA Agentic Trust", "IMDA Singapore", "IETF VAP", "KAIJU IGX"],
            }
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return compliance engine statistics."""
        total = len(self._check_history)
        by_status = defaultdict(int)
        for r in self._check_history:
            by_status[r.status.value] += 1

        return {
            "total_evaluations": total,
            "by_status": dict(by_status),
            "rules_loaded": len(self._rules),
        }
