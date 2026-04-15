# 03 — WORKFLOW

How the Nexus OS collective works. Follow this or create chaos.

---

## Review Cycle

```
REVIEW N (new agent input)
  ↓
GAP ANALYSIS (identify unresolved issues)
  ↓
TENSION RESOLUTION (debate → consensus)
  ↓
VOTING GATE (Planning → Functional → Atomic)
  ↓
ROLE ASSIGNMENT (ownership clarity)
  ↓
MASTER PLAN FREEZE (single canonical document)
  ↓
IMPLEMENTATION (phase-based, test-first)
  ↓
REVIEW N+1 (new agents, new input, new questions)
```

### Review Cycle Rules

1. **No coding before Combined Master Plan approval** — this was violated once (GLM-5 website) and explicitly corrected
2. **Every agent gets a section** — full coverage, no skipping
3. **Reading limitations OFF** — every line read, cross-referenced
4. **Proof-level tags** — BLOCKED / ACHIEVED / PARTIAL / NOT_STARTED

---

## Voting Gate Structure

Three tiers, mirrors the SkillX Planning-Functional-Atomic hierarchy:

### Tier 1: Planning (Architecture-level)
- Who owns what pillar
- Majority vote, weighted by contribution
- Speci holds tie-breaker + veto

### Tier 2: Functional (Workstream-level)
- 7 Phase 1 workstreams mapped to owners
- Each workstream has a lead + team

### Tier 3: Atomic (Task-level)
- 6 first-wave tasks attached to functional owners
- Concrete deliverables with acceptance criteria

### Voting Rules
- Weighted voting: higher weight for agents who contributed core design of a pillar
- Self-voting allowed, abstention also allowed
- Clear deadline to prevent indefinite planning
- Majority = pass; Speci = tie-breaker

---

## Decision Making

| Decision Type | Who Decides | Process |
|---------------|-------------|---------|
| Architecture | Collective vote + Speci | Vote → Speci confirms/ties |
| MVP Scope | Locked consensus | Cannot change without new vote |
| New Agents | Speci | Welcome → read all prior work → contribute |
| Process Changes | CODEX + Speci | Proposal → review → approve |
| Scope Creep | Anyone can flag | Must be explicitly rejected in master plan |

---

## 8 Open Questions (ALL ANSWERED by Speci)

| # | Question | Speci's Answer |
|---|----------|----------------|
| 1 | Conflict Resolution | Version field + optimistic locking + last-write-wins |
| 2 | Agent Health | 30s heartbeat + /health endpoint + task reclamation |
| 3 | Message Ordering | DAG dependency + idempotency keys + sequence numbers |
| 4 | Backup/Restore | SQLite WAL mode + hourly snapshots |
| 5 | Network Partition | Graceful degradation + state snapshots |
| 6 | Skill Extraction | Passive logging MVP, extraction Phase 2 |
| 7 | Scale | 5+ models/agents, browser-based access (Kimi, z.ai GLM-5, 3-4 others) |
| 8 | Compliance | GDPR + HIPAA simultaneously, unified incident response, 72-hour breach notification |

---

## 14 Critical Gaps (ALL RESOLVED)

| # | Gap | Resolution | Source |
|---|-----|-----------|--------|
| 1 | Conflict Resolution | Version field + optimistic locking + last-write-wins | GPT5, GLM 5 |
| 2 | Agent Health | 30s heartbeat + /health endpoint + task reclamation | GLM 5, QWEN |
| 3 | Message Ordering | DAG dependency + idempotency keys + sequence numbers | Gemma, GLM 5 |
| 4 | Backup/Restore | SQLite WAL mode + hourly snapshots | QWEN, GLM 5 |
| 5 | Serialization | JSON canonical, Protocol Buffers Phase 2 | GPT5 |
| 6 | Network Partition | Graceful degradation + state snapshots | Orchestra |
| 7 | Disaster Recovery | State snapshots + graceful degradation | GLM 5, Orchestra |
| 8 | Monitoring | JSON-lines logs + circuit breaker metrics | MiMo CLAW |
| 9 | Governance Over-Engineering | Hard-coded MVP, YAML deferred to Phase 2 | Gemini, Orchestra |
| 10 | Growth Loop Activation | Passive logging MVP only | Majority consensus |
| 11 | Vector Embeddings | FTS5-only, embedding hard-disable | Majority consensus |
| 12 | Judge Role | Deferred to Phase 3 (aspirational) | Majority consensus |
| 13 | Quantized Routing | REMOVED entirely | Majority consensus |
| 14 | Encryption at Rest | Deferred to Phase 2 (AES-256) | Majority consensus |

---

## 5 Mandatory Acceptance Tests

Written BEFORE any production code (test-driven development):

| Test | What It Validates |
|------|-------------------|
| MEMORY-001 | Two projects with same memory key get different results (zero leakage) |
| DAG-001 | Diamond dependency completes correctly, single failure doesn't kill parallel branches |
| HEARTBEAT-001 | Agent crash → task reclaimed → reassigned within 2 heartbeat cycles |
| CIRCUIT-001 | 5 consecutive 503s → circuit opens → requests blocked → recovery on cooldown |
| RECOVERY-001 | Write data → backup → corrupt DB → restore from snapshot → data matches |

---

## 8 Acceptance Tests (Phase 1 — from MiMo CLAW + GLM-5)

| # | Test | Source |
|---|------|--------|
| 1 | Zero Leakage | Memory Isolation |
| 2 | Idempotency | Exactly-once delivery |
| 3 | DAG Correctness | Task graph execution |
| 4 | Heartbeat Recovery | Agent liveness |
| 5 | S-to-P Promotion | Memory promotion trigger |
| 6 | AgentSocialBench Privacy | 352 scenarios |
| 7 | Memory Poisoning Defense | eTAMP + MCFA |
| 8 | Golden Test | <150ms response time (target, not blocker) |

**Priority rule**: Security (zero leakage, 100% isolation) is NON-NEGOTIABLE. Performance (<150ms) is a TARGET, not a blocker.
