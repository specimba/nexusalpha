# 06 — DECISION LOG

Every major decision, who made it, when, and why. Append-only — never delete.

---

## Architecture Decisions

| Decision | Who Decided | When | Rationale | Status |
|----------|------------|------|-----------|--------|
| 4-Pillar Architecture (Bridge/Vault/Engine/Governor) | ALL agents, unanimous | Review 1 | Clean, orthogonal decomposition mapped to real distributed systems patterns | **LOCKED** |
| S-P-E-W Memory Hierarchy | ALL agents, unanimous | Review 1 | Biomimetic approach solves context collapse | **LOCKED** |
| JSON-RPC 2.0 over HTTP | All agents | Review 1 | Simple, well-understood, polyglot-friendly | **LOCKED** |
| Python + TypeScript MVP | All agents | Review 1 | Two languages validate polyglot contract without bloat | **LOCKED** |
| Java adapter DEFERRED | All agents | Review 1 | No use case for MVP, adds implementation burden | **LOCKED** |
| FTS5-only for Phase 1 | Majority (Orchestra, Antigravity, Claude Sonnet, CODEX) | Review 2 | Sufficient for MVP, prevents premature complexity | **LOCKED** |
| Embedding columns HARD-DISABLED | Claude Sonnet + Antigravity Gemini | Review 2 | Prevents schema drift where models assume vector capabilities | **LOCKED** |
| Shadow Governance for Phase 1→2 transition | Gemma 4 31B | Review 2 | Run both engines simultaneously, flip at 100% accuracy match | **ACCEPTED** |
| Hard-coded Python governance (MVP) | Majority | Review 1 | Prevents "configuration hell", deterministic safety | **LOCKED** |
| Quantized routing REMOVED | Majority (Orchestra, MiMo, DeepSeek, Claude Sonnet, CODEX) | Review 3 | No spec, no benchmarks, no architecture — speculative R&D | **LOCKED** |
| Deny-by-default isolation | All agents | Review 1 | Most secure default posture | **LOCKED** |
| Immutable JSON-lines audit | All agents | Review 1 | Forensic trail, no modification possible | **LOCKED** |
| SHA-256 task IDs | Engine consensus | Review 1 | Atomic claims prevent redundant work | **LOCKED** |
| 30s heartbeat interval | Consensus | Review 1 | Balance between detection speed and overhead | **LOCKED** |

## Scope Decisions

| Decision | Who Decided | When | Rationale | Status |
|----------|------------|------|-----------|--------|
| "Half the full plan" MVP | Majority consensus | Review 1 | Survived 3 review cycles — rare discipline | **LOCKED** |
| Linear chains before full DAGs | Safe-Start consensus | Review 1 | Professional engineering guardrail | **LOCKED** |
| Passive logging only (Growth Loop) | Majority (Gemini, Orchestra, MiMo, CODEX, Kimi) | Review 2 | No data to feed extraction before system is running | **LOCKED** |
| 5 mandatory acceptance tests | MiMo CLAW, refined by Claude Sonnet + DeepSeek | Review 2 | Minimum validation before production-ready | **LOCKED** |
| 8 acceptance tests (Phase 1) | MiMo CLAW + GLM-5 | Review 4 | Expanded security testing (AgentSocialBench, memory poisoning) | **ACCEPTED** |
| MiMo CLAW 13→24 scope EXPANSION REJECTED | Explicit rejection | Review 3 | Scope creep via answer interpretation | **REJECTED** |
| OpenCode SQLCipher/Chroma/RBAC in Phase 1 REJECTED | Explicit rejection | Review 3 | Contradicted locked consensus | **REJECTED** |
| Growth Loop designed as passive in Phase 1 | Majority | Review 2 | Capture → extract (Phase 2) → validate (Phase 3) | **LOCKED** |

## Process Decisions

| Decision | Who Decided | When | Rationale | Status |
|----------|------------|------|-----------|--------|
| CODEX voting gate (Planning→Functional→Atomic) | CODEX GPT 5.4, adopted by all | Review 2 | Architecture convergence ≠ implementation readiness | **ACCEPTED** |
| Majority vote + Speci tie-breaker | CODEX, adopted | Review 2 | Clear governance, prevents deadlock | **ACCEPTED** |
| 48-hour vote deadline | CODEX | Review 2 | Prevents indefinite planning phase | **ACCEPTED** |
| GLM-5 corrective: redirect to backend | Kimi 2.5 flagged, Speci confirmed | Review 3 | Process violation (built during Plan Mode) | **EXECUTED** |
| Single canonical master plan | QWEN 3.6 + Claude Sonnet | Review 2 | 3x document bloat due to duplication | **ACCEPTED** |
| Agent grades removed from canonical docs | QWEN 3.6 | Review 2 | Subjective, not reproducible, no engineering value | **ACCEPTED** |

## Speci's Answers to 8 Open Questions

| # | Question | Answer | When |
|---|----------|--------|------|
| 1 | Conflict Resolution | Version field + optimistic locking + last-write-wins | Review 3 |
| 2 | Agent Health | 30s heartbeat + /health endpoint + task reclamation | Review 3 |
| 3 | Message Ordering | DAG dependency + idempotency keys + sequence numbers | Review 3 |
| 4 | Backup/Restore | SQLite WAL mode + hourly snapshots | Review 3 |
| 5 | Network Partition | Graceful degradation + state snapshots | Review 3 |
| 6 | Skill Extraction | Passive logging MVP, extraction Phase 2 | Review 3 |
| 7 | Scale | 5+ models/agents, browser-based access (Kimi, z.ai GLM-5, 3-4 others) | Review 3 |
| 8 | Compliance | GDPR + HIPAA simultaneously, unified incident response, 72-hour breach notification | Review 3 |

---

## How to Add New Decisions

```markdown
| [Decision description] | [Who decided] | [Date] | [Rationale] | [Status: ACCEPTED/LOCKED/REJECTED/CHANGED] |
```

Status lifecycle: PROPOSED → ACCEPTED → LOCKED → (optionally) CHANGED
REJECTED decisions stay in the log with their rationale for why they were rejected.
