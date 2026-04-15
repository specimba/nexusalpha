"""
Token Saving Strategies
Hot path: Semantic caching, model routing
Cold path: Prompt compression, context compilation
"""

import hashlib
import time
from typing import Dict, Any, Optional, Callable


class SemanticCache:
    """
    Semantic caching for repeated queries.
    Savings: 30-60% on repeated queries
    
    Usage:
        cache = SemanticCache(threshold=0.85)
        
        # Check cache (hot path)
        result = cache.get(query_hash)
        if result:
            return result
        
        # Store (warm path)
        cache.set(query_hash, response)
    """
    
    def __init__(self, threshold: float = 0.85, max_entries: int = 10000):
        self.threshold = threshold
        self.max_entries = max_entries
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0
    
    def get(self, query_hash: str) -> Optional[Any]:
        """Get cached result (hot path)."""
        entry = self._cache.get(query_hash)
        if entry:
            self._hits += 1
            entry['hits'] = entry.get('hits', 0) + 1
            entry['last_access'] = time.time()
            return entry.get('response')
        
        self._misses += 1
        return None
    
    def set(self, query_hash: str, response: Any, score: float = 1.0) -> None:
        """Store result in cache (warm path)."""
        if len(self._cache) >= self.max_entries:
            # Evict oldest
            oldest = min(self._cache.items(), key=lambda x: x[1].get('last_access', 0))
            del self._cache[oldest[0]]
        
        self._cache[query_hash] = {
            'response': response,
            'score': score,
            'timestamp': time.time(),
            'last_access': time.time(),
            'hits': 0,
        }
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        return {
            'entries': len(self._cache),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': f"{hit_rate:.1f}%",
        }


class ModelRouter:
    """
    Complexity-based model routing.
    Routes simple → cheap/fast, complex → frontier.
    
    Usage:
        router = ModelRouter()
        model = router.route(task_type='code', complexity='low')
    """
    
    # Model ladder (cheapest → most expensive)
    MODELS = {
        'code': {
            'low': 'qwen3:4b-thinking',
            'medium': 'osman-coder',
            'high': 'gpt-5.4',
        },
        'research': {
            'low': 'osman-speed',
            'medium': 'osman-reasoning',
            'high': 'gemini-3.1-pro',
        },
        'security': {
            'low': 'osman-agent',
            'medium': 'gemma-4-e4b',
            'high': 'gemini-3.1-pro',
        },
        'default': {
            'low': 'osman-speed',
            'medium': 'osman-agent',
            'high': 'gpt-5.4',
        },
    }
    
    def route(
        self,
        task_type: str = 'default',
        complexity: str = 'low',
        budget_remaining: int = 100000,
    ) -> str:
        """Route task to appropriate model."""
        ladder = self.MODELS.get(task_type, self.MODELS['default'])
        
        # Check budget
        if budget_remaining < 10000:
            # Force cheap model
            return ladder['low']
        
        if budget_remaining > 50000:
            # Can afford better
            return ladder.get(complexity, ladder['medium'])
        
        return ladder['low']
    
    def get_fallback(self, primary_model: str) -> str:
        """Get fallback model for primary."""
        fallbacks = {
            'gpt-5.4': 'gpt-5.4-mini',
            'gemini-3.1-pro': 'gemini-2.0-flash',
            'osman-reasoning': 'osman-agent',
            'osman-coder': 'qwen3:4b-thinking',
        }
        return fallbacks.get(primary_model, 'osman-speed')


class BudgetManager:
    """
    Budget allocation and tracking.
    Distributes tokens across agents, skills, sessions.
    """
    
    def __init__(self, total_budget: int):
        self.total_budget = total_budget
        self._allocations: Dict[str, int] = {}
        self._reservations: Dict[str, int] = {}
    
    def allocate(self, category: str, amount: int) -> bool:
        """Allocate budget to category."""
        if self.available < amount:
            return False
        
        self._allocations[category] = self._allocations.get(category, 0) + amount
        return True
    
    def reserve(self, category: str, amount: int) -> Optional[str]:
        """Reserve budget for operation."""
        if not self.can_reserve(category, amount):
            return None
        
        self._reservations[f"{category}:{time.time()}"] = amount
        return f"{category}:{time.time()}"
    
    def can_reserve(self, category: str, amount: int) -> bool:
        """Check if reservation possible."""
        allocated = self._allocations.get(category, 0)
        reserved = sum(
            v for k, v in self._reservations.items()
            if k.startswith(category)
        )
        return (allocated - reserved) >= amount
    
    @property
    def available(self) -> int:
        """Get available budget."""
        allocated = sum(self._allocations.values())
        return self.total_budget - allocated
    
    def reset(self, category: Optional[str] = None) -> None:
        """Reset budget."""
        if category:
            self._allocations.pop(category, None)
        else:
            self._allocations.clear()
            self._reservations.clear()
