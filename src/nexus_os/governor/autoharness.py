"""
AutoHarness - 6-Step Governance Pipeline with mem0 Integration
Parse → Risk → Permission → Execute → Sanitize → Audit
"""

import os
import json
import yaml
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from nexus_os.vault.mem0_adapter import Mem0Adapter, get_adapter


class RiskLevel(Enum):
    """Risk classification levels"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionType(Enum):
    """Action types for risk classification"""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    API_CALL = "api_call"
    SHELL = "shell"
    SECRET_ACCESS = "secret_access"
    DEPLOY = "deploy"
    BROADCAST = "broadcast"


@dataclass
class TaskIntent:
    """Parsed task intent"""
    action: str
    target: str
    parameters: Dict[str, Any]
    raw_input: str
    entities: List[str]


@dataclass
class RiskAssessment:
    """Risk assessment result"""
    level: RiskLevel
    score: float
    factors: List[str]
    mem0_history_checked: bool
    similar_incidents: int
    requires_approval: bool


@dataclass
class PermissionResult:
    """Permission check result"""
    allowed: bool
    reason: str
    constraints: List[str]
    approver: Optional[str]


@dataclass
class ExecutionResult:
    """Execution result"""
    success: bool
    output: Any
    error: Optional[str]
    duration_ms: int
    token_usage: int


@dataclass
class AuditRecord:
    """Audit trail record"""
    timestamp: str
    task_id: str
    pipeline_step: str
    risk_level: str
    action_taken: str
    mem0_refs: List[str]
    token_usage: int


class AutoHarness:
    """
    6-Step Governance Pipeline:
    1. Parse - extract intent and entities
    2. Risk - classify risk using mem0 history
    3. Permission - check against policy
    4. Execute - run approved action
    5. Sanitize - clean output
    6. Audit - log to mem0
    """
    
    def __init__(self, 
                 constitution_path: Optional[str] = None,
                 mem0_adapter: Optional[Mem0Adapter] = None):
        self.mem0 = mem0_adapter or get_adapter()
        
        # Load constitution
        if constitution_path is None:
            constitution_path = os.path.join(
                os.path.dirname(__file__), "constitution.yaml"
            )
        self.constitution = self._load_constitution(constitution_path)
        
        # Pipeline state
        self._audit_log: List[AuditRecord] = []
        self._step_handlers: Dict[str, Callable] = {
            "parse": self._step_parse,
            "risk": self._step_risk,
            "permission": self._step_permission,
            "execute": self._step_execute,
            "sanitize": self._step_sanitize,
            "audit": self._step_audit
        }
    
    def _load_constitution(self, path: str) -> Dict[str, Any]:
        """Load constitution YAML"""
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            # Return default constitution if file not found
            return self._default_constitution()
    
    def _default_constitution(self) -> Dict[str, Any]:
        """Default constitution if YAML not found"""
        return {
            "risk_rules": [
                {"pattern": "read_file, read_memory, search", "risk": "LOW", "mem0_check": False},
                {"pattern": "write_file, update_state, create_task", "risk": "MEDIUM", "mem0_check": True},
                {"pattern": "exec, web_fetch, api_call, shell", "risk": "HIGH", "mem0_check": True},
                {"pattern": "secret_*, delete_*, broadcast, deploy", "risk": "CRITICAL", "mem0_check": True, "human_approval": True}
            ],
            "permissions": {
                "LOW": {"auto_approve": True, "max_tokens": 10000},
                "MEDIUM": {"auto_approve": True, "max_tokens": 5000, "rate_limit": "10/min"},
                "HIGH": {"auto_approve": False, "requires_review": True},
                "CRITICAL": {"auto_approve": False, "requires_human": True}
            },
            "sanitization": {
                "remove_secrets": True,
                "mask_pii": True,
                "truncate_output": 10000
            }
        }
    
    def run_pipeline(self, task_id: str, task_input: str, 
                     executor: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Run full 6-step governance pipeline
        Returns complete execution report
        """
        context = {
            "task_id": task_id,
            "input": task_input,
            "executor": executor,
            "intent": None,
            "risk": None,
            "permission": None,
            "execution": None,
            "sanitized_output": None,
            "audit_refs": []
        }
        
        # Step 1: Parse
        context = self._step_parse(context)
        
        # Step 2: Risk
        context = self._step_risk(context)
        
        # Step 3: Permission
        context = self._step_permission(context)
        
        # Step 4: Execute (if permitted)
        if context["permission"].allowed:
            context = self._step_execute(context)
            context = self._step_sanitize(context)
        
        # Step 5: Audit
        context = self._step_audit(context)
        
        return {
            "task_id": task_id,
            "success": context["execution"].success if context["execution"] else False,
            "risk_level": context["risk"].level.value if context["risk"] else "UNKNOWN",
            "allowed": context["permission"].allowed if context["permission"] else False,
            "output": context["sanitized_output"] or (context["execution"].output if context["execution"] else None),
            "error": context["execution"].error if context["execution"] else None,
            "audit_refs": context["audit_refs"],
            "token_usage": context["execution"].token_usage if context["execution"] else 0
        }
    
    def _step_parse(self, context: Dict) -> Dict:
        """Step 1: Parse - extract intent and entities"""
        task_input = context["input"]
        
        # Simple intent extraction
        action = "unknown"
        target = ""
        entities = []
        
        # Extract action keywords
        action_keywords = {
            "read": ["read", "get", "fetch", "load"],
            "write": ["write", "save", "update", "create"],
            "execute": ["run", "exec", "call", "invoke"],
            "delete": ["delete", "remove", "clear"],
            "search": ["search", "find", "query", "lookup"]
        }
        
        input_lower = task_input.lower()
        for act, keywords in action_keywords.items():
            if any(kw in input_lower for kw in keywords):
                action = act
                break
        
        # Extract entities (file paths, URLs, etc.)
        words = task_input.split()
        for word in words:
            if "." in word and "/" in word:
                entities.append(word)
                if not target:
                    target = word
        
        context["intent"] = TaskIntent(
            action=action,
            target=target,
            parameters={},
            raw_input=task_input,
            entities=entities
        )
        
        return context
    
    def _step_risk(self, context: Dict) -> Dict:
        """Step 2: Risk - classify with mem0 history check"""
        intent = context["intent"]
        
        # Match against constitution rules
        risk_level = RiskLevel.LOW
        factors = []
        mem0_checked = False
        similar_incidents = 0
        
        # Check action type
        action = intent.action
        
        # Match against risk rules
        for rule in self.constitution.get("risk_rules", []):
            pattern = rule.get("pattern", "")
            if action in pattern.lower() or any(p.strip() in action for p in pattern.split(",")):
                risk_level = RiskLevel(rule.get("risk", "LOW"))
                factors.append(f"Matched rule: {pattern}")
                
                # Check mem0 if required
                if rule.get("mem0_check", False):
                    mem0_checked = True
                    try:
                        similar = self.mem0.search_experience(
                            query=intent.raw_input,
                            limit=5
                        )
                        failures = sum(1 for r in similar if r.outcome == "failure")
                        similar_incidents = failures
                        
                        if failures > 2:
                            # Escalate risk if history shows failures
                            if risk_level == RiskLevel.MEDIUM:
                                risk_level = RiskLevel.HIGH
                            elif risk_level == RiskLevel.HIGH:
                                risk_level = RiskLevel.CRITICAL
                            factors.append(f"History shows {failures} similar failures")
                    except Exception:
                        pass
                
                break
        
        # Calculate risk score
        base_scores = {
            RiskLevel.LOW: 0.25,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.75,
            RiskLevel.CRITICAL: 1.0
        }
        score = base_scores[risk_level]
        
        if similar_incidents > 0:
            score += similar_incidents * 0.1
            score = min(score, 1.0)
        
        # Check if human approval required
        requires_approval = risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
        
        context["risk"] = RiskAssessment(
            level=risk_level,
            score=score,
            factors=factors,
            mem0_history_checked=mem0_checked,
            similar_incidents=similar_incidents,
            requires_approval=requires_approval
        )
        
        return context
    
    def _step_permission(self, context: Dict) -> Dict:
        """Step 3: Permission - check against policy"""
        risk = context["risk"]
        intent = context["intent"]
        
        permissions = self.constitution.get("permissions", {})
        risk_perm = permissions.get(risk.level.value, {})
        
        allowed = risk_perm.get("auto_approve", False)
        reason = "Auto-approved by policy" if allowed else "Requires review"
        constraints = []
        approver = None
        
        if risk.level == RiskLevel.CRITICAL:
            allowed = False
            reason = "CRITICAL risk requires human approval"
            approver = "human"
        elif risk.level == RiskLevel.HIGH:
            allowed = False
            reason = "HIGH risk requires review"
            approver = "reviewer"
        elif risk.level == RiskLevel.MEDIUM:
            constraints.append(f"Rate limit: {risk_perm.get('rate_limit', 'none')}")
            constraints.append(f"Max tokens: {risk_perm.get('max_tokens', 'unlimited')}")
        
        context["permission"] = PermissionResult(
            allowed=allowed,
            reason=reason,
            constraints=constraints,
            approver=approver
        )
        
        return context
    
    def _step_execute(self, context: Dict) -> Dict:
        """Step 4: Execute - run approved action"""
        intent = context["intent"]
        executor = context.get("executor")
        
        start_time = datetime.now()
        
        try:
            if executor:
                output = executor(intent.raw_input)
            else:
                # Default execution
                output = f"Simulated execution of: {intent.action} on {intent.target}"
            
            success = True
            error = None
        except Exception as e:
            output = None
            success = False
            error = str(e)
        
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        
        context["execution"] = ExecutionResult(
            success=success,
            output=output,
            error=error,
            duration_ms=duration,
            token_usage=0  # Would be populated by actual LLM call
        )
        
        return context
    
    def _step_sanitize(self, context: Dict) -> Dict:
        """Step 5: Sanitize - clean output"""
        execution = context["execution"]
        
        if not execution or not execution.output:
            context["sanitized_output"] = None
            return context
        
        output = str(execution.output)
        
        # Apply sanitization rules
        rules = self.constitution.get("sanitization", {})
        
        if rules.get("remove_secrets", False):
            # Remove potential secrets (simple patterns)
            import re
            output = re.sub(r'(api[_-]?key|token|secret|password)["\']?\s*[:=]\s*["\']?[^\s"\']+', r'\1=***REDACTED***', output, flags=re.IGNORECASE)
        
        if rules.get("mask_pii", False):
            # Simple PII masking
            import re
            output = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '***-**-****', output)  # SSN
            output = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '***@***.***', output)  # Email
        
        if rules.get("truncate_output"):
            max_len = rules["truncate_output"]
            if len(output) > max_len:
                output = output[:max_len] + "\n... [truncated]"
        
        context["sanitized_output"] = output
        return context
    
    def _step_audit(self, context: Dict) -> Dict:
        """Step 6: Audit - log to mem0"""
        task_id = context["task_id"]
        risk = context["risk"]
        execution = context["execution"]
        permission = context["permission"]
        
        # Create audit record
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            task_id=task_id,
            pipeline_step="complete",
            risk_level=risk.level.value if risk else "UNKNOWN",
            action_taken="allowed" if permission and permission.allowed else "denied",
            mem0_refs=[],
            token_usage=execution.token_usage if execution else 0
        )
        
        # Store in mem0
        try:
            mem0_id = self.mem0.add_experience(
                content=f"Task {task_id}: {context['input'][:200]}",
                domain="governance",
                outcome="success" if (execution and execution.success) else "failure",
                metadata={
                    "risk_level": risk.level.value if risk else "UNKNOWN",
                    "allowed": permission.allowed if permission else False,
                    "duration_ms": execution.duration_ms if execution else 0
                }
            )
            record.mem0_refs.append(mem0_id)
        except Exception:
            pass
        
        self._audit_log.append(record)
        context["audit_refs"] = record.mem0_refs
        
        return context
    
    def get_audit_log(self) -> List[AuditRecord]:
        """Get full audit log"""
        return self._audit_log.copy()
    
    def get_constitution(self) -> Dict[str, Any]:
        """Get current constitution"""
        return self.constitution.copy()
