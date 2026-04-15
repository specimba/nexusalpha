# 01 — ARCHITECTURE: The 4 Pillars

**Status**: UNANIMOUSLY LOCKED across all review cycles. No agent has proposed replacing any pillar.

---

## Pillar I: The Bridge (MCP+ System Bus)

Inter-agent communication layer. JSON-RPC 2.0 over HTTP.

**Mandatory Headers (every envelope)**:
- `X-Nexus-Project-ID` — isolation key (prevents cross-project leakage)
- `X-Nexus-Task-ID` — links to DAG node
- `X-Nexus-Lineage-ID` — tracks provenance chains
- `X-Nexus-Trace-ID` — observability correlation

**Reliability Mechanisms**:
- Idempotency keys for exactly-once delivery
- Sequence numbers for ordering within lineage chains
- Circuit breakers at every layer (learned from OpenRouter Fusion production analysis)
- Error taxonomy: 503 (service overload) vs 401 (auth failure) — distinct handling

**Polyglot Support (MVP)**:
- Python (native)
- TypeScript (HTTP client)
- Java explicitly DEFERRED — no adapter bloat

**Phase 2 Additions**:
- A2A signed capability cards (RFC-style agent discovery)
- gRPC streaming for high-throughput lanes

---

## Pillar II: The Vault (S-P-E-W Biomimetic Memory)

Four-layer memory hierarchy solving "context collapse" in long-running agents.

| Layer | Name | Storage | Retention | Purpose |
|-------|------|---------|-----------|---------|
| S | Session | RAM/in-memory | Current interaction | Active working memory |
| P | Episodic | SQLite FTS5 | Days→weeks | Event logs, agent experiences |
| E | Semantic | SQLite (Phase 1) → Chroma/Zvec (Phase 2) | Weeks→months | Extracted facts, deduplicated |
| W | Wisdom | SQLite | Permanent | Policies, skills, validated knowledge |

**MIA Enhancements (from arXiv:2604.04503)**:
- Hybrid retrieval: `score = 0.5 × semantic + 0.3 × value_reward + 0.2 × frequency_reward`
- Importance-based promotion thresholds
- Trajectory compression (raw logs → structured summaries)
- Bidirectional flow: Wisdom seeds Session prompts (cold-start optimization)

**Phase 1 Rules**:
- FTS5 ONLY — no vector DB
- Embedding columns exist in schema but are HARD-DISABLED with `NOT ACTIVE IN PHASE 1` annotation
- VectorStoreAdapter interface locked but only implements FTS5

**Phase 2 Migration**:
- Zvec hybrid approach (new from GLM-5 research)
- FTS5 → SQLite-Vector or Chroma via config change (adapter pattern)

---

## Pillar III: The Engine (DAG Orchestration)

Dependency-aware task graph execution.

**State Machine**: `pending → ready → claimed → working → completed | failed`

**Task IDs**: SHA-256 hash of `(project_id, description, timestamp)` — atomic claims prevent redundant work

**Heartbeat**: 30-second intervals → liveness detection → auto-reclamation on failure

**Routing (MVP)**: Deterministic rule-based matching
**Routing (Phase 3)**: Quantized coordination model — REMOVED from roadmap per collective decision

**MVP Scope**: Linear task chains (not full DAGs). Basic DAG deferred to Phase 2.

---

## Pillar IV: The Governor (Policy and Safety)

Deny-by-default isolation. No agent accesses resources outside its project scope.

**MVP Implementation**: Hard-coded Python class. If `request.project_id != agent.project_id` → DROP.

**Audit Trail**: Immutable JSON-lines logging of all cross-boundary access.

**Shadow Governance (for Phase 1→2 transition)**:
1. Run hard-coded rules + YAML engine simultaneously
2. Hard-coded rules make actual decisions
3. YAML engine runs in background logging mode
4. When YAML matches hard-coded with 100% accuracy → flip switch
5. Zero-risk migration path

**Phase 2**: YAML policy engine, RBAC, resource quotas, configurable retention

---

## S-P-E-W Data Flow

```
Session (RAM) → importance threshold → Episodic (SQLite FTS5)
Episodic → dedup/extract → Semantic (DB)
Semantic → validate/promote → Wisdom (permanent)

Wisdom → seed cold-start → Session (bidirectional)
```

---

## Research Integration

**SkillX** (arXiv:2604.04804):
- 3-tier hierarchy: Planning → Functional → Atomic
- Iterative refinement: Merge → Filter → Update
- Growth Loop: Plan → Execute → Capture → Extract → Refine → Validate → Deploy

**MIA** (arXiv:2604.04503):
- Hybrid retrieval scoring formula
- Importance-based promotion thresholds
- Trajectory compression
- Bidirectional memory flow

**Research Phase 2 Additions (GLM-5)**:
- eTAMP (memory poisoning defense)
- MCFA (multi-component forensic analysis)
- ZeroClaw (zero-trust agent protocol)
- A2A v0.3 compliance

---

## Security Model

| Property | Status | Notes |
|----------|--------|-------|
| Project isolation | HARD ENFORCED | Deny-by-default, project_id matching |
| Cross-boundary access | AUDITED | JSON-lines immutable log |
| Encryption at rest | DEFERRED to Phase 2 | AES-256 planned |
| Memory poisoning defense | Phase 2 | eTAMP + MCFA |
| Agent trust scoring | Phase 1 COMPLETE | Lane-scoped, context injection |
| AgentSocialBench privacy | Phase 1 test | 352 scenarios, 7 categories |
