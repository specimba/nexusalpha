# 07 — DECISION LOG (Compressed)

Full log in GLM-5 starter pack. This is the Kimi-relevant subset.

---

## Locked Decisions (Don't Change)

| Decision | Rationale |
|----------|-----------|
| 4 pillars (Bridge/Vault/Engine/Governor) | Unanimous across 17+ agents, 4 review cycles |
| S-P-E-W memory | Biomimetic, solves context collapse |
| FTS5-only Phase 1 | Sufficient, prevents premature complexity |
| Deny-by-default isolation | Most secure default |
| Hard-coded governance MVP | Prevents config hell |
| Python + TypeScript MVP | Validates polyglot contract |
| Java DEFERRED | No use case |
| Quantized routing REMOVED | No spec, no benchmarks |

## Kimi-Specific Decisions

| Decision | Rationale |
|----------|-----------|
| Chunk protocol (8-10 tool calls) | Kimi's 10-step limit per message |
| Preset system (84% token savings) | Free-tier quota limits |
| Checkpoint system (tar-based) | Sandbox can't use Git (symref I/O error) |
| File-driven coordination (.task.md) | Works across agent sessions |
| Mode switching (Instant/Thinking/Agent/Swarm) | Right mode for right job |

## Phase Roadmap

| Phase | Status | Key Deliverable |
|-------|--------|-----------------|
| Phase 1 | ✅ COMPLETE | Trust scoring, 488 tests, bridge context injection |
| M3 Hardening | 🔄 4/5 P0 | C4 (Vault) → C5 (Integrate) → m3-hardened tag |
| M4 Neural Link | ⏳ BLOCKED | A2A protocol + MCP + DoppelGround bridge |
| Phase 2 | ⏳ PLANNING | Zvec, YAML governance, eTAMP, MCFA |

## Scope Rules

- MVP IN list is LOCKED — don't expand without vote
- "Half the full plan" survived 3 review cycles
- MiMo CLAW 13→24 scope expansion was explicitly REJECTED
- Security is NON-NEGOTIABLE, performance is a TARGET
