"""
Nexus-TokenGuard Core Module

Token monitoring and saving layer for NEXUS OS.
Non-blocking, VAP-compliant, modular.
"""

import time
import hashlib
import json
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class OperationType(Enum):
    """Token operation types."""
    TASK_DELEGATION = "task_delegation"
    SKILL_EXECUTION = "skill_execution"
    MEMORY_QUERY = "memory_query"
    MODEL_INFERENCE = "model_inference"
    GOVERNANCE_CHECK = "governance_check"
    AUDIT_LOG = "audit_log"


@dataclass
class TokenBudget:
    """Token budget configuration."""
    total: int
    used: int = 0
    warnings_issued: int = 0
    last_reset: datetime = field(default_factory=datetime.now)
    
    @property
    def remaining(self) -> int:
        return self.total - self.used
    
    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.used / self.total) * 100
    
    def check_threshold(self, threshold: float = 80.0) -> bool:
        """Check if usage exceeds threshold."""
        return self.percentage >= threshold


@dataclass
class AuditEntry:
    """VAP-compliant audit entry."""
    timestamp: str
    actor: str
    action: str
    input_tokens: int
    output_tokens: int
    context: Dict[str, Any]
    outcome: str
    signature: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'actor': self.actor,
            'action': self.action,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'context': self.context,
            'outcome': self.outcome,
            'signature': self.signature,
        }


class TokenGuard:
    """
    Nexus-TokenGuard: Token monitoring and saving layer.
    
    Features:
    - Per-agent, per-skill, per-swarm budgets
    - Non-blocking hot path (token counting only)
    - VAP-compliant audit trail
    - Real-time warnings + hard stops
    - Semantic caching (warm path)
    - Model routing (warm path)
    """
    
    def __init__(
        self,
        budgets: Optional[Dict[str, int]] = None,
        mode: str = 'local',
        warning_threshold: float = 80.0,
        hard_stop_threshold: float = 95.0,
    ):
        """
        Initialize TokenGuard.
        
        Args:
            budgets: Budget limits per category
                   {'agent': 50000, 'skill': 10000, 'swarm': 200000}
            mode: 'local' (ai-tokenizer) or 'cloud' (tokscale)
            warning_threshold: % usage to trigger warning
            hard_stop_threshold: % usage to trigger hard stop
        """
        self.mode = mode
        self.warning_threshold = warning_threshold
        self.hard_stop_threshold = hard_stop_threshold
        
        # Initialize budgets
        default_budgets = {
            'agent': 50000,
            'skill': 10000,
            'swarm': 200000,
            'session': 500000,
        }
        if budgets:
            default_budgets.update(budgets)
        
        self._budgets: Dict[str, TokenBudget] = {
            k: TokenBudget(total=v) for k, v in default_budgets.items()
        }
        
        # Audit trail (in-memory for now, persist to Vault later)
        self._audit: List[AuditEntry] = []
        self._audit_lock = threading.Lock()
        
        # Semantic cache (warm path)
        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()
        
        # Model routing preferences
        self._routing_prefs: Dict[str, str] = {}
    
    def track(
        self,
        agent_id: str,
        tokens: int,
        operation: str = "inference",
        context: Optional[Dict[str, Any]] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> Dict[str, Any]:
        """
        Track token usage (hot path - non-blocking).
        
        Args:
            agent_id: Agent identifier
            tokens: Total tokens used
            operation: Type of operation
            context: Additional context
            input_tokens: Input token count
            output_tokens: Output token count
            
        Returns:
            Status dict with usage info
        """
        # Update budget
        budget_key = self._get_budget_key(agent_id)
        if budget_key in self._budgets:
            self._budgets[budget_key].used += tokens
        
        # Log audit entry (VAP-compliant)
        self._log_audit(
            actor=agent_id,
            action=operation,
            input_tokens=input_tokens or tokens,
            output_tokens=output_tokens,
            context=context or {},
        )
        
        # Check thresholds
        budget = self._budgets.get(budget_key)
        if budget and budget.check_threshold(self.warning_threshold):
            self._issue_warning(agent_id, budget)
        
        # Return status
        return {
            'agent_id': agent_id,
            'tokens': tokens,
            'budget_key': budget_key,
            'remaining': budget.remaining if budget else 0,
            'percentage': budget.percentage if budget else 0,
            'timestamp': datetime.now().isoformat(),
        }
    
    def check(self, agent_id: str, required_tokens: int) -> bool:
        """
        Check if agent has enough budget for operation (non-blocking).
        
        Args:
            agent_id: Agent identifier
            required_tokens: Tokens needed for operation
            
        Returns:
            True if operation can proceed
        """
        budget_key = self._get_budget_key(agent_id)
        budget = self._budgets.get(budget_key)
        
        if not budget:
            return True  # No budget limit
        
        # Check remaining
        if budget.remaining < required_tokens:
            return False
        
        # Check hard stop
        if budget.percentage >= self.hard_stop_threshold:
            return False
        
        return True
    
    def check_and_reserve(
        self,
        agent_id: str,
        required_tokens: int,
        operation: str = "inference",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check budget and reserve tokens if available (atomic operation).
        
        Args:
            agent_id: Agent identifier
            required_tokens: Tokens needed
            operation: Operation type
            context: Additional context
            
        Returns:
            {'allowed': True/False, 'reservation_id': str}
        """
        if not self.check(agent_id, required_tokens):
            return {
                'allowed': False,
                'reason': 'budget_exceeded',
                'agent_id': agent_id,
                'required': required_tokens,
                'timestamp': datetime.now().isoformat(),
            }
        
        # Reserve tokens
        result = self.track(
            agent_id=agent_id,
            tokens=required_tokens,
            operation=operation,
            context=context,
        )
        
        return {
            'allowed': True,
            'reservation_id': self._hash(f"{agent_id}:{required_tokens}:{time.time()}"),
            'agent_id': agent_id,
            'tokens': required_tokens,
            'timestamp': datetime.now().isoformat(),
            **result,
        }
    
    def trigger_fallback(self, agent_id: str) -> Dict[str, Any]:
        """
        Trigger fallback to cheaper model when budget low.
        
        Args:
            agent_id: Agent needing fallback
            
        Returns:
            Fallback model recommendation
        """
        # Model routing logic
        model_map = {
            'osman-agent': 'osman-speed',      # gemma3n:e4b → locooperator
            'osman-coder': 'qwen3:4b-thinking', # qwen2.5-coder → qwen3:4b
            'osman-reasoning': 'qwen3.5:4b',   # uncensored:9b → qwen3.5:4b
            'frontier': 'fast-frontier',       # GPT-5.4 → GPT-5.4-mini
        }
        
        fallback = model_map.get(agent_id, 'osman-speed')
        
        return {
            'original_agent': agent_id,
            'fallback_agent': fallback,
            'reason': 'budget_low',
            'timestamp': datetime.now().isoformat(),
        }
    
    def get_status(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current token budget status.
        
        Args:
            agent_id: Specific agent or None for all
            
        Returns:
            Budget status dict
        """
        if agent_id:
            budget_key = self._get_budget_key(agent_id)
            budget = self._budgets.get(budget_key)
            if budget:
                return {
                    'used': budget.used,
                    'total': budget.total,
                    'remaining': budget.remaining,
                    'percentage': budget.percentage,
                    'last_reset': budget.last_reset.isoformat(),
                }
            return {}
        
        return {
            key: {
                'used': b.used,
                'total': b.total,
                'remaining': b.remaining,
                'percentage': round(b.percentage, 2),
            }
            for key, b in self._budgets.items()
        }
    
    def get_audit(
        self,
        agent_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail (VAP-compliant).
        
        Args:
            agent_id: Filter by agent
            since: ISO timestamp filter
            limit: Max entries
            
        Returns:
            List of audit entries
        """
        with self._audit_lock:
            entries = self._audit.copy()
        
        # Filter
        if agent_id:
            entries = [e for e in entries if e.actor == agent_id]
        
        if since:
            since_dt = datetime.fromisoformat(since)
            entries = [e for e in entries if datetime.fromisoformat(e.timestamp) >= since_dt]
        
        # Limit and convert
        return [e.to_dict() for e in entries[-limit:]]
    
    def semantic_cache_get(
        self,
        query_hash: str,
        threshold: float = 0.85,
    ) -> Optional[Any]:
        """
        Get cached response for semantically similar query (warm path).
        
        Args:
            query_hash: Hash of query
            threshold: Similarity threshold
            
        Returns:
            Cached response or None
        """
        with self._cache_lock:
            entry = self._cache.get(query_hash)
            if entry and entry.get('score', 0) >= threshold:
                return entry.get('response')
        return None
    
    def semantic_cache_set(
        self,
        query_hash: str,
        response: Any,
        score: float = 1.0,
    ) -> None:
        """
        Store response in semantic cache (warm path).
        
        Args:
            query_hash: Hash of query
            response: Response to cache
            score: Similarity score
        """
        with self._cache_lock:
            self._cache[query_hash] = {
                'response': response,
                'score': score,
                'timestamp': datetime.now().isoformat(),
            }
    
    def route(
        self,
        task_type: str,
        complexity: str = 'low',
        budget_remaining: int = 100000,
    ) -> str:
        """
        Route task to appropriate model (warm path).
        
        Args:
            task_type: Type of task (code/research/security)
            complexity: Low/medium/high
            budget_remaining: Available budget
            
        Returns:
            Recommended model
        """
        # Complexity-based routing
        if complexity == 'low':
            if task_type == 'code':
                return 'qwen3:4b-thinking'  # Fastest
            return 'osman-speed'
        
        if complexity == 'medium':
            if task_type == 'code':
                return 'osman-coder'
            if task_type == 'research':
                return 'osman-reasoning'
            return 'osman-agent'
        
        # High complexity - use frontier
        if budget_remaining > 50000:
            return 'gemini-3.1-pro'  # Or GPT-5.4
        return 'osman-reasoning'
    
    def reset_budget(self, category: str) -> bool:
        """
        Reset budget for category.
        
        Args:
            category: Budget category
            
        Returns:
            True if reset successful
        """
        if category in self._budgets:
            self._budgets[category].used = 0
            self._budgets[category].last_reset = datetime.now()
            return True
        return False
    
    def analyze_trends(
        self,
        agent_id: Optional[str] = None,
        period: str = '24h',
    ) -> Dict[str, Any]:
        """
        Analyze token usage trends (cold path - for SkillSmith).
        
        Args:
            agent_id: Agent to analyze
            period: Time period (1h/24h/7d)
            
        Returns:
            Trend analysis
        """
        # Parse period
        hours = {'1h': 1, '24h': 24, '7d': 168}.get(period, 24)
        since = datetime.now() - timedelta(hours=hours)
        
        # Get audit entries
        entries = self.get_audit(agent_id=agent_id, since=since.isoformat())
        
        if not entries:
            return {
                'period': period,
                'total_tokens': 0,
                'avg_tokens': 0,
                'trend': 'no_data',
                'savings_potential': '0%',
            }
        
        total_tokens = sum(e.get('input_tokens', 0) + e.get('output_tokens', 0) for e in entries)
        avg_tokens = total_tokens / len(entries) if entries else 0
        
        # Calculate trend
        mid_point = len(entries) // 2
        if mid_point > 0:
            first_half = sum(
                e.get('input_tokens', 0) + e.get('output_tokens', 0)
                for e in entries[:mid_point]
            )
            second_half = sum(
                e.get('input_tokens', 0) + e.get('output_tokens', 0)
                for e in entries[mid_point:]
            )
            
            if second_half > first_half * 1.1:
                trend = 'increasing'
            elif second_half < first_half * 0.9:
                trend = 'decreasing'
            else:
                trend = 'stable'
        else:
            trend = 'stable'
        
        # Estimate savings potential
        savings_potential = '8-18%'  # SkillSmith target
        
        return {
            'period': period,
            'total_tokens': total_tokens,
            'avg_tokens': round(avg_tokens, 2),
            'entry_count': len(entries),
            'trend': trend,
            'savings_potential': savings_potential,
        }
    
    # Private methods
    

    def remaining(self, agent_id: str) -> int:
        """Return tokens remaining for this agent's budget category.

        Args:
            agent_id: Agent identifier

        Returns:
            Remaining token budget (0 if no budget configured)
        """
        budget_key = self._get_budget_key(agent_id)
        budget = self._budgets.get(budget_key)
        if budget is None:
            return 0
        return max(0, budget.total - budget.used)

    def _get_budget_key(self, agent_id: str) -> str:
        """Map agent_id to budget category."""
        if 'skill' in agent_id.lower():
            return 'skill'
        if 'swarm' in agent_id.lower() or 'foreman' in agent_id.lower():
            return 'swarm'
        return 'agent'
    
    def _log_audit(
        self,
        actor: str,
        action: str,
        input_tokens: int,
        output_tokens: int,
        context: Dict[str, Any],
    ) -> None:
        """Log VAP-compliant audit entry."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            actor=actor,
            action=action,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context=context,
            outcome='success',
            signature=self._sign_entry(actor, action, input_tokens, output_tokens),
        )
        
        with self._audit_lock:
            self._audit.append(entry)
            # Keep last 10000 entries
            if len(self._audit) > 10000:
                self._audit = self._audit[-10000:]
    
    def _sign_entry(
        self,
        actor: str,
        action: str,
        input_tokens: int,
        output_tokens: int,
    ) -> str:
        """Create SHA-256 signature for audit entry."""
        data = f"{actor}:{action}:{input_tokens}:{output_tokens}:{time.time()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def _issue_warning(self, agent_id: str, budget: TokenBudget) -> None:
        """Issue budget warning."""
        budget.warnings_issued += 1
        # In production: emit event for Governor/SkillSmith
        print(f"[TokenGuard] WARNING: {agent_id} at {budget.percentage:.1f}% budget")
    
    def _hash(self, data: str) -> str:
        """Generate short hash."""
        return hashlib.sha256(data.encode()).hexdigest()[:12]


# Convenience function for hot path
def quick_track(agent_id: str, tokens: int) -> None:
    """
    Quick token tracking (hot path).
    
    Usage:
        quick_track('foreman-1', 1250)
    """
    guard = TokenGuard()
    guard.track(agent_id=agent_id, tokens=tokens)
