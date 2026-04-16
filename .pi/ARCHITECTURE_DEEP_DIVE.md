# NEXUS OS — Architecture Deep Dive

**Version**: 3.0.0-beta  
**Date**: 2026-04-16  
**Author**: Pi Agent (Research & Documentation)  
**Status**: CANONICAL REFERENCE

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Four Pillars Architecture](#four-pillars-architecture)
3. [Data Flow Topology](#data-flow-topology)
4. [Module Deep Dives](#module-deep-dives)
5. [Integration Points](#integration-points)
6. [Security Model](#security-model)
7. [Performance Characteristics](#performance-characteristics)
8. [Extensibility Patterns](#extensibility-patterns)
9. [Gaps & Future Work](#gaps--future-work)

---

## Executive Summary

NEXUS OS is a **local-first Agent Operating System** implementing three major protocols:
- **A2A v1.0** — Agent-to-Agent communication
- **MCP** — Model Context Protocol
- **JSON-RPC 2.0** — Remote procedure calls

The system is organized around **four pillars**:
1. **Bridge** — External interface (API, SDK, secrets)
2. **Vault** — Memory management (S-P-E-W hierarchy)
3. **Engine** — Execution routing (Hermes, skills)
4. **Governor** — Compliance & governance (KAIJU, VAP)

---

## Four Pillars Architecture

### 1. Bridge (`src/nexus_os/bridge/`)

**Purpose**: External interface layer — handles all incoming requests and authentication.

```
┌─────────────────────────────────────────────────────────────┐
│                        BRIDGE LAYER                         │
├─────────────────────────────────────────────────────────────┤
│  server.py        │ JSON-RPC 2.0 server                     │
│  sdk.py           │ Python SDK for programmatic access      │
│  secrets.py       │ HMAC secret management                  │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
    ┌─────────┐
    │ HMAC    │ ← Request signing
    │ Auth    │
    └─────────┘
```

**Key Components**:
- `server.py` (27KB) — FastAPI-based JSON-RPC server
- `sdk.py` (16KB) — Python SDK with client helpers
- `secrets.py` (4KB) — Secret store integration

**TokenGuard Integration Point**:
```python
# PENDING: Add token headers to all responses
response.headers["X-Token-Used"] = str(tokens_used)
response.headers["X-Token-Remaining"] = str(guard.remaining(agent_id))
```

---

### 2. Vault (`src/nexus_os/vault/`)

**Purpose**: Memory lifecycle management with S-P-E-W hierarchy and MINJA poisoning protection.

```
┌─────────────────────────────────────────────────────────────┐
│                        VAULT LAYER                          │
├─────────────────────────────────────────────────────────────┤
│  manager.py       │ S-P-E-W memory operations               │
│  memory_adapter.py│ Mem0-compatible adapter (31KB)          │
│  poisoning.py     │ MINJA v2 detection engine               │
│  trust.py         │ Bayesian trust scoring                  │
└─────────────────────────────────────────────────────────────┘
```

**S-P-E-W Memory Hierarchy**:

| Layer | Description | TTL | Storage |
|-------|-------------|-----|---------|
| **S**ession | Ephemeral, task-scoped | Minutes | In-memory |
| **P**roject | Medium-term, FTS5-indexed | Days-Weeks | SQLite |
| **E**xperience | Compressed paradigms | Months | SQLite + Archive |
| **W**isdom | High-trust, promoted | Permanent | Encrypted SQLite |

**MINJA v2 Poisoning Protection**:

The `poisoning.py` module implements multi-layer defense:

```python
class PoisoningDetector:
    """
    MINJA v2: Multi-layer Injection Neutralization & Judgment Analysis
    
    Layers:
    1. VELOCITY CHECK — Rate limiting (writes/minute)
    2. PATTERN CHECK — Duplicate/contradiction detection
    3. TRUST CHECK — Agent reputation gating
    4. CONTENT CHECK — Injection pattern matching
    """
```

**Trust Scoring** (Bayesian):

```python
# From trust.py
class BayesianTrustScorer:
    """
    Bayesian reputation with prior smoothing.
    
    Formula: score = (successes + PRIOR_SUCCESS) / (total + PRIOR_SUCCESS + PRIOR_FAILURE)
    
    Prior: 10 successes, 2 failures → base rate ~83%
    This prevents overfitting to small sample sizes.
    """
    PRIOR_SUCCESS = 10
    PRIOR_FAILURE = 2
```

---

### 3. Engine (`src/nexus_os/engine/`)

**Purpose**: Task execution, model routing, skill management.

```
┌─────────────────────────────────────────────────────────────┐
│                        ENGINE LAYER                         │
├─────────────────────────────────────────────────────────────┤
│  hermes.py        │ 3-layer experience-based router (12KB)  │
│  executor.py      │ Task execution pipeline                 │
│  heartbeat.py     │ Health monitoring                       │
│  router.py        │ A2A message routing                     │
│  forge.py         │ Task orchestration                      │
└─────────────────────────────────────────────────────────────┘
```

**Hermes Router — 3-Layer Strategy**:

```
┌──────────────────────────────────────────────────────────┐
│                    HERMES ROUTER                         │
├──────────────────────────────────────────────────────────┤
│  Layer 1: TASK CLASSIFICATION                            │
│  ├── TaskClassifier.classify(description)                │
│  ├── Returns: (TaskDomain, TaskComplexity)               │
│  └── Keywords → domain/complexity mapping                │
│                                                          │
│  Layer 2: EXPERIENCE SCORING                             │
│  ├── ExperienceScorer.score(domain, models)              │
│  ├── Backend 1: model_performance (Bayesian)             │
│  ├── Backend 2: memory_records (provenance)              │
│  └── Domain-affinity boost: +0.2 for capability match    │
│                                                          │
│  Layer 3: COST-OPTIMIZED SELECTION                       │
│  ├── CostOptimizer.select(scores, models, complexity)    │
│  ├── TRIVIAL/STANDARD: cheapest above threshold          │
│  ├── COMPLEX: quality-first                              │
│  └── CRITICAL: best local → best cloud                   │
└──────────────────────────────────────────────────────────┘
```

**Task Domains**:
```python
class TaskDomain(Enum):
    CODE = "code"        # Generation, debugging, review
    ANALYSIS = "analysis" # Data, research, metrics
    REASONING = "reasoning" # Logic, math, planning
    CREATIVE = "creative" # Writing, design
    OPERATIONS = "operations" # Deploy, configure
    SECURITY = "security" # Audits, policy
```

**Task Complexity**:
```python
class TaskComplexity(Enum):
    TRIVIAL = "trivial"    # Simple lookup, formatting
    STANDARD = "standard"  # Normal code, analysis
    COMPLEX = "complex"    # Multi-step reasoning
    CRITICAL = "critical"  # Architecture, security
```

---

### 4. Governor (`src/nexus_os/governor/`)

**Purpose**: Compliance, authorization, audit trail.

```
┌─────────────────────────────────────────────────────────────┐
│                       GOVERNOR LAYER                        │
├─────────────────────────────────────────────────────────────┤
│  compliance.py    │ OWASP ASI, CSA, IMDA rules (23KB)      │
│  kaiju_auth.py    │ KAIJU 4-variable gate (10KB)           │
│  base.py          │ Governor base class (12KB)             │
│  autoharness.py   │ Automated harness testing              │
│  proof_chain.py   │ VAP audit chain                        │
└─────────────────────────────────────────────────────────────┘
```

**KAIJU 4-Variable Gate**:

```
┌──────────────────────────────────────────────────────────┐
│                    KAIJU AUTH                            │
├──────────────────────────────────────────────────────────┤
│  Variable    │ Values                          │ Rule     │
├──────────────────────────────────────────────────────────┤
│  Scope       │ self, project, system           │ Clear    │
│  Intent      │ Free text (10+ chars)           │ Keywords │
│  Impact      │ low, med, high, critical        │ Hold     │
│  Clearance   │ reader, contributor, admin      │ Deny     │
└──────────────────────────────────────────────────────────┘
```

**Compliance Frameworks**:

| Framework | Focus | Rules |
|-----------|-------|-------|
| OWASP ASI 2026 | Agent Security | Authentication, Provenance |
| CSA Agentic Trust | Cross-agent | Trust scoring, Reputation |
| IMDA Singapore | Human oversight | Critical operations hold |
| IETF VAP | Audit | Verifiable Audit Path |
| KAIJU IGX | Intent | 4-variable gate |

---

## Data Flow Topology

### Request Processing Flow

```
┌──────────┐     ┌─────────┐     ┌───────┐     ┌──────────┐
│  Client  │────▶│ Bridge  │────▶│ Vault │────▶│ Governor │
│ (SDK)    │     │ Server  │     │ Auth  │     │ KAIJU    │
└──────────┘     └─────────┘     └───────┘     └──────────┘
                      │               │              │
                      ▼               ▼              ▼
                 ┌─────────────────────────────────────────┐
                 │              Engine Layer               │
                 │  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
                 │  │ Hermes  │─▶│Executor │─▶│ Result  │  │
                 │  │ Router  │  │ Pipeline│  │ Handler │  │
                 │  └─────────┘  └─────────┘  └─────────┘  │
                 └─────────────────────────────────────────┘
                                     │
                                     ▼
                 ┌─────────────────────────────────────────┐
                 │              Vault Layer                │
                 │  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
                 │  │ Memory  │  │ Trust   │  │ MINJA   │  │
                 │  │ Write   │  │ Update  │  │ Check   │  │
                 │  └─────────┘  └─────────┘  └─────────┘  │
                 └─────────────────────────────────────────┘
```

### Memory Write Flow (with MINJA)

```
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY WRITE FLOW                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Agent requests memory write                             │
│     │                                                       │
│     ▼                                                       │
│  2. MINJA Poisoning Check                                   │
│     ├── Velocity: Agent wrote X entries in last Y seconds   │
│     ├── Pattern: Duplicate/contradiction detection          │
│     ├── Trust: Agent trust score < threshold?               │
│     └── Content: Injection pattern match                    │
│     │                                                       │
│     ├── BLOCK → raise PoisoningError                        │
│     └── PASS → continue                                     │
│                                                             │
│  3. Write to S-P-E-W layer                                  │
│     │                                                       │
│     ▼                                                       │
│  4. Update trust score (success/failure)                    │
│     │                                                       │
│     ▼                                                       │
│  5. Audit log entry (VAP)                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Module Deep Dives

### TokenGuard (`monitoring/token_guard.py`)

**Purpose**: Token budget management with VAP-compliant audit.

```python
class TokenGuard:
    """
    Token monitoring and saving layer.
    
    Features:
    - Per-agent, per-skill, per-swarm budgets
    - Non-blocking hot path (token counting only)
    - VAP-compliant audit trail
    - Real-time warnings + hard stops
    - Semantic caching (warm path)
    - Model routing suggestions (warm path)
    """
    
    # Default budgets
    default_budgets = {
        'agent': 50000,
        'skill': 10000,
        'swarm': 200000,
        'session': 500000,
    }
```

**Key Methods**:

| Method | Purpose | Path |
|--------|---------|------|
| `track()` | Record token usage | Hot |
| `check()` | Budget availability check | Hot |
| `check_and_reserve()` | Atomic reserve | Hot |
| `semantic_cache_get()` | Cache lookup | Warm |
| `route()` | Model recommendation | Warm |
| `analyze_trends()` | Usage analytics | Cold |
| `get_audit()` | VAP audit trail | Cold |

**Integration Points**:

1. **Bridge** (PENDING):
```python
# In server.py response handler
guard.track(agent_id, tokens_used)
response.headers["X-Token-Used"] = str(tokens_used)
```

2. **Governor** (PENDING):
```python
# In compliance.py hard stop check
if not guard.check(agent_id, required_tokens):
    return ComplianceResult(status=ComplianceStatus.HARD_STOP)
```

---

### Hermes Router (`engine/hermes.py`)

**Purpose**: Experience-based model routing.

**Routing Algorithm**:

```python
def route(self, task_id: str, description: str, context: dict) -> RoutingDecision:
    """
    3-layer routing:
    
    1. Classify task (domain + complexity)
    2. Check for skill match (fast path)
    3. Score models by experience
    4. Select cheapest above quality threshold
    """
    
    # Layer 1: Classification
    domain, complexity = self.classifier.classify(description)
    
    # Fast path: Skill match
    skill = self._match_skill(description, domain)
    if skill:
        return RoutingDecision(
            selected_model=skill.recommended_model,
            score=skill.success_rate,
            matched_skill=skill.skill_id
        )
    
    # Layer 2: Score by experience
    scores = self.scorer.score(domain, models)
    
    # Layer 3: Cost-optimize
    model, score, reason = self.optimizer.select(scores, models, complexity)
    
    return RoutingDecision(selected_model=model, score=score, reason=reason)
```

**Experience Scoring Backend**:

```sql
-- Backend 1: model_performance (Bayesian)
CREATE TABLE model_performance (
    model_id TEXT NOT NULL,
    task_class TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    total_latency_ms REAL DEFAULT 0,
    PRIMARY KEY (model_id, task_class)
);

-- Backend 2: memory_records (provenance trail)
-- Uses existing memory_records table with type='experience'
```

---

## Integration Points

### Current Integration Status

| Integration | Status | Priority |
|-------------|--------|----------|
| Vault ↔ Bridge | ✅ Complete | — |
| Vault ↔ MINJA | ✅ Complete | — |
| Governor ↔ KAIJU | ✅ Complete | — |
| Governor ↔ Compliance | ✅ Complete | — |
| Engine ↔ Hermes | ✅ Complete | — |
| **TokenGuard ↔ Bridge** | ❌ Pending | P0 |
| **TokenGuard ↔ Governor** | ❌ Pending | P0 |
| Hermes ↔ TokenGuard | ❌ Pending | P1 |
| Skill Adapter ↔ Hermes | ✅ Complete | — |

### Required Integrations

**1. TokenGuard → Bridge** (P0):

```python
# In bridge/server.py
from nexus_os.monitoring.token_guard import TokenGuard

class BridgeServer:
    def __init__(self):
        self.token_guard = TokenGuard()
    
    async def handle_request(self, request):
        # Check budget before processing
        if not self.token_guard.check(request.agent_id, ESTIMATED_TOKENS):
            return {"error": "budget_exceeded", "code": 429}
        
        # Process request...
        result = await self._process(request)
        
        # Track actual usage
        self.token_guard.track(
            agent_id=request.agent_id,
            tokens=result.tokens_used,
            operation=request.method
        )
        
        # Add token headers
        result.headers["X-Token-Used"] = str(result.tokens_used)
        result.headers["X-Token-Remaining"] = str(
            self.token_guard.remaining(request.agent_id)
        )
        
        return result
```

**2. TokenGuard → Governor** (P0):

```python
# In governor/compliance.py
class ComplianceEngine:
    def evaluate(self, agent_id, action, context):
        # ... existing rules ...
        
        # TokenGuard hard stop
        if hasattr(self, 'token_guard'):
            required = context.get('required_tokens', 1000)
            if not self.token_guard.check(agent_id, required):
                return ComplianceResult(
                    status=ComplianceStatus.HARD_STOP,
                    violations=[ComplianceViolation(
                        rule_id="TOKEN-BUDGET-001",
                        level=ComplianceLevel.VIOLATION,
                        message=f"Token budget exceeded for {agent_id}"
                    )]
                )
        
        return result
```

---

## Security Model

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION FLOW                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Request received with signature                        │
│     │                                                       │
│     ▼                                                       │
│  2. Bridge validates HMAC signature                        │
│     │                                                       │
│     ├── Invalid → 401 Unauthorized                         │
│     └── Valid → Continue                                    │
│                                                             │
│  3. KAIJU 4-Variable Check                                  │
│     │                                                       │
│     ├── Scope verified                                      │
│     ├── Intent sufficient (10+ chars)                      │
│     ├── Impact assessed                                     │
│     └── Clearance confirmed                                 │
│                                                             │
│  4. Compliance Rules Evaluation                             │
│     │                                                       │
│     ├── OWASP ASI: Authentication, Provenance              │
│     ├── CSA: Trust score check                             │
│     ├── IMDA: Human hold for critical                      │
│     └── VAP: Audit log append                              │
│                                                             │
│  5. Request authorized                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Encryption Policy

```python
# From db/manager.py
class DatabaseManager:
    """
    Security policy:
    - If encrypted=True and pysqlcipher3 missing:
      - If allow_unencrypted=False: RAISE ImportError (hard fail)
      - If allow_unencrypted=True: Log WARNING, fall back to plaintext
    
    Default: allow_unencrypted=False (production-safe)
    """
```

---

## Performance Characteristics

### Hot Path Latency

| Operation | Target | Actual |
|-----------|--------|--------|
| KAIJU check | <1ms | ~0.5ms |
| TokenGuard track | <1ms | ~0.2ms |
| Hermes classify | <5ms | ~2ms |
| MINJA velocity | <2ms | ~1ms |

### Cold Path Latency

| Operation | Target | Notes |
|-----------|--------|-------|
| Trust smoothing | <100ms | Background job |
| VAP audit write | <50ms | Async |
| Hermes experience update | <20ms | Post-request |

---

## Extensibility Patterns

### Adding a New Skill

```python
# In skills/my_skill/SKILL.md
---
skill_id: "my-custom-skill"
name: "My Custom Skill"
task_type: "code"
pattern: "implement.*feature"
recommended_model: "osman-coder"
---

# Skill description and usage
```

```python
# Register with Hermes
from nexus_os.engine.hermes import SkillRecord

skill = SkillRecord(
    skill_id="my-custom-skill",
    name="My Custom Skill",
    task_type="code",
    pattern=r"implement.*feature",
    recommended_model="osman-coder",
    success_rate=0.85,
    execution_count=0
)
router.register_skill(skill)
```

### Adding a New Compliance Rule

```python
# In governor/compliance.py
class MyCustomRule(ComplianceRule):
    rule_id = "CUSTOM-001"
    source = RuleSource.INTERNAL
    level = ComplianceLevel.WARNING
    
    def check(self, agent_id, action, context) -> Optional[ComplianceViolation]:
        if action == "my_sensitive_action":
            if not context.get("special_approval"):
                return ComplianceViolation(
                    rule_id=self.rule_id,
                    level=self.level,
                    message="My sensitive action requires special approval"
                )
        return None
```

---

## Gaps & Future Work

### Known Gaps

| Gap | Priority | Status |
|-----|----------|--------|
| TokenGuard ↔ Bridge integration | P0 | Pending |
| TokenGuard ↔ Governor integration | P0 | Pending |
| Test flakiness (Windows file locking) | P1 | Partial fix |
| Semantic cache warming | P2 | Not started |
| Hermes ↔ TokenGuard routing | P2 | Not started |

### Architecture Improvements

1. **Event Bus**: Consider event-driven architecture for async operations
2. **Caching Layer**: Redis integration for multi-instance deployments
3. **Metrics Export**: Prometheus/OpenTelemetry integration
4. **Rate Limiting**: Token bucket per agent/skill
5. **Circuit Breaker**: For external model API calls

---

## Appendix: Quick Reference

### File Locations

```
src/nexus_os/
├── bridge/
│   ├── server.py      # JSON-RPC server (27KB)
│   ├── sdk.py         # Python SDK (16KB)
│   └── secrets.py     # HMAC secrets (4KB)
├── vault/
│   ├── manager.py     # S-P-E-W operations (13KB)
│   ├── memory_adapter.py # Mem0 adapter (31KB)
│   ├── poisoning.py   # MINJA v2 (10KB)
│   └── trust.py       # Bayesian scoring (6KB)
├── engine/
│   ├── hermes.py      # Experience router (12KB)
│   ├── executor.py    # Task execution
│   └── router.py      # A2A routing
├── governor/
│   ├── compliance.py  # OWASP/CSA rules (23KB)
│   ├── kaiju_auth.py  # 4-variable gate (10KB)
│   └── proof_chain.py # VAP audit (2.5KB)
├── monitoring/
│   └── token_guard.py # Token budget (15KB)
└── db/
    └── manager.py     # Database layer (10KB)
```

### Key Classes

```python
# Bridge
BridgeServer, NexusSDK, SecretStore

# Vault
VaultManager, PoisoningDetector, BayesianTrustScorer

# Engine
HermesRouter, TaskClassifier, ExperienceScorer, CostOptimizer

# Governor
ComplianceEngine, KAIJUAuth, VAPProofChain

# Monitoring
TokenGuard, TokenBudget, AuditEntry
```

---

**Document Status**: COMPLETE  
**Next Review**: 2026-04-23  
**Owner**: Pi Agent (Research & Documentation)
