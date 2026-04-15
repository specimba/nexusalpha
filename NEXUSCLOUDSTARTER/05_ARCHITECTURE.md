# 05 — ARCHITECTURE (Ultra-Compressed)

Compressed from 4,800 words to ~500 tokens. Use `01_ARCHITECTURE.md` from GLM-5 starter pack for full detail.

---

## 4 Pillars

| Pillar | What | MVP Implementation |
|--------|------|-------------------|
| **Bridge** | Inter-agent communication | JSON-RPC 2.0 + 4 Nexus headers (Project-ID, Task-ID, Lineage-ID, Trace-ID) |
| **Vault** | S-P-E-W memory | Session(RAM) → Episodic(FTS5) → Semantic(DB) → Wisdom(permanent) |
| **Engine** | DAG task orchestration | SHA-256 task IDs, 30s heartbeat, state machine: pending→ready→claimed→working→done/failed |
| **Governor** | Policy & safety | Deny-by-default, project_id matching, immutable JSON-lines audit |

## S-P-E-W Memory

```
S (Session/RAM) → threshold → P (Episodic/FTS5) → extract → E (Semantic/DB→Zvec) → promote → W (Wisdom/permanent)
W → seed cold-start → S (bidirectional)
```

Hybrid retrieval: `score = 0.5×semantic + 0.3×value + 0.2×frequency`

## Security Stack

- SecretStore (HMAC-SHA256, constant-time comparison)
- Hard-fail encryption (no silent plaintext fallback)
- KAIJU auth (4-variable authorization)
- Agent trust scoring (Phase 1 complete: lane-scoped, context injection)
- MINJA v2 memory poisoning defense (Phase 2)

## Research Papers

| Paper | What It Gives |
|-------|---------------|
| SkillX (arXiv:2604.04804) | 3-tier skill hierarchy, Growth Loop |
| MIA (arXiv:2604.04503) | Hybrid retrieval, promotion thresholds, trajectory compression |
| eTAMP (GLM-5) | Memory poisoning defense |
| MCFA (GLM-5) | Multi-component forensic analysis |
| AgentSocialBench (MiMo) | Privacy benchmark (352 scenarios) |

## Swarm Architecture

```
[User Task] → [mem0] → [Hermes Router] → [Skill Registry] → [Coordinator] → [.task.md] → [Worker] → [Result] → [Hermes + mem0]
```

- **Foreman**: glm5-foreman (coordination, patrol, dispatch)
- **Workers**: glm5-worker-1 (code), glm5-worker-2 (ops/security)
- **Router**: glm5-hermes (29 skills, domain classification)
- **Memory**: Mem0Adapter (local JSON fallback)
- **Tasks**: File-driven (.task.md in pending/done/failed queues)
