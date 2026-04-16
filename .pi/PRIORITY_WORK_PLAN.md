# NEXUS OS — Priority Work Plan

**Version**: 3.0.0-beta  
**Date**: 2026-04-16  
**Author**: Pi Agent  
**Status**: PLANNING DOCUMENT

---

## Current State Assessment

### Test Status (2026-04-16)
```
499 passed, 2 failed, 1 skipped
Previous: 497 passed, 4 failed, 24 errors
Progress: Fixed 24 errors + 2 failures
Remaining: 2 test failures (non-critical)
```

### Completed Integrations
- ✅ Vault ↔ Bridge
- ✅ Vault ↔ MINJA
- ✅ Governor ↔ KAIJU
- ✅ Governor ↔ Compliance
- ✅ Engine ↔ Hermes
- ✅ Skill Adapter ↔ Hermes

### Pending Integrations
- ❌ TokenGuard ↔ Bridge (P0)
- ❌ TokenGuard ↔ Governor (P0)
- ❌ Hermes ↔ TokenGuard (P1)

---

## P0: Immediate Priorities (This Week)

### 1. TokenGuard Integration

**Goal**: Connect TokenGuard to Bridge and Governor for budget enforcement.

#### 1.1 Bridge Integration

**File**: `src/nexus_os/bridge/server.py`

**Changes Required**:
```python
# Add import
from nexus_os.monitoring.token_guard import TokenGuard

# In BridgeServer.__init__
self.token_guard = TokenGuard(
    budgets={'agent': 50000, 'session': 500000},
    warning_threshold=80.0,
    hard_stop_threshold=95.0
)

# In request handler
async def handle_jsonrpc(self, request):
    agent_id = request.get('agent_id', 'unknown')
    
    # Pre-check: Budget available?
    if not self.token_guard.check(agent_id, 1000):
        return {
            'jsonrpc': '2.0',
            'error': {'code': 429, 'message': 'Token budget exceeded'},
            'id': request.get('id')
        }
    
    # Process request...
    result = await self._process_request(request)
    
    # Track usage
    self.token_guard.track(
        agent_id=agent_id,
        tokens=result.tokens_used,
        operation=request.get('method', 'unknown')
    )
    
    # Add headers
    result['token_used'] = result.tokens_used
    result['token_remaining'] = self.token_guard.remaining(agent_id)
    
    return result
```

**Testing**:
```bash
pytest tests/monitoring/test_token_guard.py -v
pytest tests/bridge/ -v -k "token"
```

#### 1.2 Governor Integration

**File**: `src/nexus_os/governor/compliance.py`

**Changes Required**:
```python
# Add to ComplianceEngine.__init__
self.token_guard = None  # Injected post-init

def set_token_guard(self, guard):
    """Inject TokenGuard for budget compliance."""
    self.token_guard = guard

# Add to evaluate()
def evaluate(self, agent_id, action, context):
    # ... existing rules ...
    
    # TOKEN-BUDGET rule
    if self.token_guard:
        required = context.get('required_tokens', 1000)
        if not self.token_guard.check(agent_id, required):
            result.violations.append(ComplianceViolation(
                rule_id="TOKEN-BUDGET-001",
                level=ComplianceLevel.VIOLATION,
                message=f"Token budget exceeded: {agent_id} needs {required}"
            ))
            result.status = ComplianceStatus.HARD_STOP
    
    return result
```

**Testing**:
```bash
pytest tests/integration/test_compliance.py -v -k "token"
```

---

### 2. Test Stabilization

**Remaining Failures**:
1. `test_skill_adapter.py::TestHermesIntegration::test_records_can_be_registered_with_hermes`
2. `test_coordinator.py::TestWorkerProfile::test_worker_profile_queue_paths`

**Root Causes**:
- Windows file locking (PermissionError)
- Path assertions (Windows backslashes)
- Module-level cleanup code

**Fix Strategy**:
- Use pytest fixtures with proper teardown
- Use `tmp_path` fixture for temp files
- Use `pathlib.Path.parts` for path assertions

---

## P1: Short-term Priorities (Next 2 Weeks)

### 1. Hermes ↔ TokenGuard Routing

**Goal**: Hermes should consider token budget when selecting models.

**File**: `src/nexus_os/engine/hermes.py`

**Changes**:
```python
class HermesRouter:
    def __init__(self, db, models, quality_threshold=0.6, token_guard=None):
        self.token_guard = token_guard
    
    def route(self, task_id, description, context):
        # Get budget remaining
        if self.token_guard:
            budget = self.token_guard.remaining(context.get('agent_id', 'default'))
        else:
            budget = float('inf')
        
        # Pass budget to optimizer
        model, score, reason = self.optimizer.select(
            scores, models, complexity, budget_remaining=budget
        )
```

**Update CostOptimizer**:
```python
def select(self, scores, models, complexity, budget_remaining=float('inf')):
    # Filter out models that exceed budget
    affordable = [m for m in models if self._estimate_cost(m) <= budget_remaining]
    if not affordable:
        # Trigger fallback
        return self._fallback_model()
    # ... rest of selection logic
```

---

### 2. Semantic Cache Warming

**Goal**: Pre-populate cache with common queries.

**Implementation**:
```python
# In TokenGuard
def warm_cache(self, queries: List[str], responses: List[Any]):
    """Pre-populate semantic cache."""
    for query, response in zip(queries, responses):
        query_hash = self._hash(query)
        self.semantic_cache_set(query_hash, response)

# Usage at startup
guard.warm_cache(
    queries=["status check", "list agents", "health"],
    responses=[status_response, agents_response, health_response]
)
```

---

### 3. Metrics Export

**Goal**: Export TokenGuard metrics for monitoring.

**Implementation**:
```python
# In TokenGuard
def get_metrics(self) -> Dict[str, Any]:
    """Prometheus-compatible metrics."""
    return {
        'token_guard_budget_total': self._budgets,
        'token_guard_budget_used': {k: v.used for k, v in self._budgets.items()},
        'token_guard_audit_entries': len(self._audit),
        'token_guard_cache_hits': self._cache_hits,
        'token_guard_cache_misses': self._cache_misses,
    }
```

---

## P2: Medium-term Priorities (Next Month)

### 1. Event-Driven Architecture

**Goal**: Decouple components with event bus.

**Design**:
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Bridge    │────▶│  Event Bus   │────▶│  Governor   │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Monitoring  │
                    └──────────────┘
```

**Events**:
- `request.received`
- `request.authorized`
- `request.processing`
- `request.completed`
- `token.used`
- `memory.written`
- `compliance.violation`

### 2. Redis Integration

**Goal**: Multi-instance support with shared state.

**Use Cases**:
- Distributed token budgets
- Shared semantic cache
- Cross-instance audit log
- Agent presence tracking

### 3. OpenTelemetry Integration

**Goal**: Distributed tracing and metrics.

**Implementation**:
```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

tracer = trace.get_tracer(__name__)

@tracer.start_as_current_span("process_request")
async def handle_request(self, request):
    span = trace.get_current_span()
    span.set_attribute("agent_id", request.agent_id)
    span.set_attribute("method", request.method)
    # ... process ...
```

---

## Task Breakdown

### This Week (P0)

| Day | Task | Est. Hours | Owner |
|-----|------|------------|-------|
| Mon | TokenGuard → Bridge integration | 4 | CODEX |
| Tue | TokenGuard → Governor integration | 4 | CODEX |
| Wed | Integration tests | 2 | CODEX |
| Thu | Test fixes (remaining 2) | 2 | PI |
| Fri | Documentation update | 2 | PI |

### Next Week (P1 Start)

| Day | Task | Est. Hours | Owner |
|-----|------|------------|-------|
| Mon | Hermes ↔ TokenGuard routing | 4 | CODEX |
| Tue | Semantic cache warming | 2 | PI |
| Wed | Metrics export | 2 | PI |
| Thu | Code review | 2 | SPECI |
| Fri | Integration testing | 2 | ALL |

---

## Success Criteria

### P0 Complete When:
- [ ] TokenGuard integrated into Bridge
- [ ] TokenGuard integrated into Governor
- [ ] All tests passing (501 passed, 0 failed)
- [ ] Documentation updated

### P1 Complete When:
- [ ] Hermes uses TokenGuard for routing
- [ ] Semantic cache warmed at startup
- [ ] Metrics exported to monitoring
- [ ] Performance benchmarks documented

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Windows file locking | High | Medium | Use tmp_path fixture |
| Integration conflicts | Medium | High | Coordinate with SPECI |
| Performance regression | Low | High | Benchmark before/after |
| Breaking changes | Medium | High | Feature flags |

---

## Notes for SPECI

1. **Test fixes are non-blocking** — The 2 remaining failures are in cleanup code, not core functionality
2. **TokenGuard integration is critical path** — Blocking other P1 work
3. **Documentation is complete** — ARCHITECTURE_DEEP_DIVE.md is ready for review
4. **Branch coordination needed** — We're working on main simultaneously

---

**Document Status**: COMPLETE  
**Next Update**: 2026-04-17  
**Owner**: Pi Agent
