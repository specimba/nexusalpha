# Nexus-TokenGuard
# Token Monitoring & Saving Layer for NEXUS OS
#
# Usage:
#   from nexus_os.monitoring.token_guard import TokenGuard
#
#   guard = TokenGuard(budgets={'agent': 50000, 'swarm': 200000})
#   guard.track(agent_id='foreman-1', tokens=1250)
#   guard.check('foreman-1', 5000)  # Returns True/False

__version__ = "1.0.0"

from .monitoring.token_guard import TokenGuard
from .monitoring.counters import LocalCounter, NativeCounter, TokscaleCounter
from .monitoring.strategies import SemanticCache, ModelRouter, BudgetManager

__all__ = [
    "TokenGuard",
    "LocalCounter",
    "NativeCounter", 
    "TokscaleCounter",
    "SemanticCache",
    "ModelRouter",
    "BudgetManager",
]
