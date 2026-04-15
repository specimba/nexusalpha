================================================================================
TOKENGUARD INTEGRATION GUIDE
================================================================================
Nexus OS v3.0 - Token Monitoring Layer

================================================================================
QUICK START
================================================================================

1. Import TokenGuard:
   from src.nexus_os.monitoring.token_guard import TokenGuard

2. Initialize with budgets:
   guard = TokenGuard(budgets={
       'agent': 50000,
       'skill': 10000,
       'swarm': 200000,
       'session': 500000
   })

3. Track token usage:
   guard.track('foreman-1', 1250, operation='inference')

4. Check budget before operation:
   if guard.check('foreman-1', 5000):
       # Proceed with operation
       pass

5. Atomic reserve:
   result = guard.check_and_reserve('foreman-1', 5000)
   if result['allowed']:
       # Execute operation

================================================================================
INTEGRATION POINTS
================================================================================

BRIDGE (bridge/server.py):
  - Add X-Nexus-Input-Tokens header to responses
  - Track tokens per agent call

GOVERNOR (governor/):
  - Check budget before task delegation
  - Enforce hard stops at 95% threshold
  - Log to VAP audit trail

ENGINE (engine/executor.py):
  - Track tokens per task execution
  - Route to fallback model when budget low
  - Update Mem0 with usage patterns

VAULT (vault/):
  - Store token events in memory layer
  - Query historical usage for SkillSmith
  - Semantic cache for repeated queries

SKILLS (skills/):
  - Track tokens per skill execution
  - Optimize skill manifest based on usage

================================================================================
HOT PATH (Non-Blocking)
================================================================================

Foreman track() call:
  # ~1ms latency
  guard.track(agent_id, tokens)

Bridge response header:
  # No blocking
  X-Nexus-Input-Tokens: 1250
  X-Nexus-Output-Tokens: 890

================================================================================
WARM PATH (Async)
================================================================================

Model routing:
  model = guard.route(task_type='code', complexity='low')
  
Semantic cache check:
  result = guard.semantic_cache_get(query_hash)
  if result:
      return cached_result

================================================================================
COLD PATH (Background)
================================================================================

Trend analysis:
  python -c "
  from src.nexus_os.monitoring.token_guard import TokenGuard
  guard = TokenGuard()
  print(guard.analyze_trends('foreman-1', '24h'))
  "

Budget optimization:
  # SkillSmith reads trends and proposes optimization
  # 8-18% savings per cycle

================================================================================
COUNTERS
================================================================================

Local (ai-tokenizer):
  from src.nexus_os.monitoring.counters import LocalCounter
  counter = LocalCounter()
  count = counter.count("text to count")

Cloud (tokscale):
  from src.nexus_os.monitoring.counters import TokscaleCounter
  counter = TokscaleCounter()
  count = counter.count("text to count")

Native (Ollama/OpenAI):
  from src.nexus_os.monitoring.counters import NativeCounter
  counter = NativeCounter('qwen3:4b-thinking')
  count = counter.count("text to count")

================================================================================
STRATEGIES
================================================================================

Semantic Cache:
  from src.nexus_os.monitoring.strategies import SemanticCache
  cache = SemanticCache(threshold=0.85)
  cache.set(query_hash, response)
  result = cache.get(query_hash)
  print(cache.stats())  # hit rate

Model Router:
  from src.nexus_os.monitoring.strategies import ModelRouter
  router = ModelRouter()
  model = router.route('code', 'low')
  fallback = router.get_fallback('gpt-5.4')

Budget Manager:
  from src.nexus_os.monitoring.strategies import BudgetManager
  manager = BudgetManager(total_budget=500000)
  manager.allocate('agent', 50000)

================================================================================
