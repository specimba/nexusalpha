# 07 — PHASE ROADMAP

The plan from MVP to production. Scope is locked — changes require collective vote.

---

## Phase Status

| Phase | Status | Key Milestone |
|-------|--------|---------------|
| **Phase 1** | ✅ COMPLETE | Trust scoring, bridge context injection, 488 tests passing |
| **Phase 2** | 🔄 PLANNING | Research complete, integration plan being built |
| **Phase 3** | ⏳ FUTURE | Not yet designed |

---

## MVP Scope (LOCKED — IN)

| # | Component | Priority | Notes |
|---|-----------|----------|-------|
| 1 | SQLite Schema (S-P-E-W tables) | P0 | FTS5 for P+E, WAL mode |
| 2 | JSON-RPC 2.0 Bridge over HTTP | P0 | With Nexus headers |
| 3 | DAG Engine (linear chains) | P0 | Basic execution, heartbeat monitoring |
| 4 | A2A Bridge Protocol + Nexus Headers | P0 | 4 mandatory headers |
| 5 | Hard-coded Python Governance | P0 | Deny-by-default, project_id matching |
| 6 | Audit Logging (JSON-lines) | P0 | Immutable, all cross-boundary access |
| 7 | 5 Mandatory Acceptance Tests | P0 | Written BEFORE production code |
| 8 | CLI Tool (basic) | P0 | Status, run, view tasks |
| 9 | TypeScript HTTP Client | P0 | Validates polyglot contract |
| 10 | Skill Capture (passive logging only) | P0 | Raw trajectory storage, no extraction |

## MVP Scope (LOCKED — OUT)

| # | Component | Deferred To | Why |
|---|-----------|------------|-----|
| 1 | Full 7-step Growth Loop | 2 | No data before system is running |
| 2 | SQLite-Vector / Chroma / FAISS | 2 | FTS5 sufficient |
| 3 | YAML Governance Engine | 2 | Hard-coded first |
| 4 | Vector Embeddings | 2 | Hard-disable in Phase 1 |
| 5 | Quantized Routing | REMOVED | No spec exists |
| 6 | Java Adapter | 3+ | No use case |
| 7 | Full DAG (diamond chains) | 2 | Linear chains MVP |
| 8 | Encryption at Rest (AES-256) | 2 | Defer, not remove |
| 9 | Langfuse Tracing | N/A | JSON logs suffice |
| 10 | The Judge Role | 3 | Aspirational only |
| 11 | Swarm View CLI | N/A | No spec |

---

## Phase 2 Scope (PLANNING — Research Complete)

Research has been completed (3 rounds: MiMo, GLM-5, deeper searches). Integration plan in progress.

### Phase 2 Additions (from Research)

| Component | Source | Rationale |
|-----------|--------|-----------|
| Zvec hybrid vector DB | GLM-5 (arXiv research) | Better than raw Chroma for local-first |
| YAML governance engine | Gemma 4 (Shadow Governance) | Run parallel, flip at 100% accuracy |
| A2A signed capability cards | A2A v0.3 standard | Agent discovery and trust |
| eTAMP memory poisoning defense | GLM-5 research | Critical security gap |
| MCFA forensic analysis | GLM-5 research | Multi-component attack detection |
| RBAC with resource quotas | CODEX + Claude Sonnet | Phase 2 governance upgrade |
| SQLCipher encryption (AES-256) | Deferred from Phase 1 | Privacy compliance (GDPR/HIPAA) |
| Vector search (Zvec/Chroma) | Deferred from Phase 1 | Performance upgrade from FTS5 |
| AgentSocialBench privacy validation | MiMo CLAW | 352 scenarios, 7 categories |
| Prometheus/Grafana metrics | DeepSeek | Operational observability |

### Phase 2 Workstreams

1. **Vector DB Migration** — FTS5 → Zvec via adapter pattern (config change, not rewrite)
2. **Governance Upgrade** — Shadow Governance activation, YAML engine parallel run
3. **Security Hardening** — eTAMP, MCFA, AgentSocialBench, memory poisoning defense
4. **Auth Upgrade** — Simple tokens → A2A signed capability cards
5. **Observability** — Prometheus metrics, structured logging
6. **Encryption** — SQLCipher AES-256 at rest
7. **Growth Loop Activation** — Passive → active (extract, refine, validate)

---

## Phase 3 (FUTURE — Not Yet Designed)

- Full DAG execution (diamond chains)
- The Judge role
- Multi-host deployment
- Full Growth Loop with autonomous skill deployment
- LangChain / MCP / A2A ecosystem integration

---

## 8 Acceptance Tests (Before Phase 1 Code)

| # | Test | What It Validates | Priority |
|---|------|-------------------|----------|
| 1 | MEMORY-001 | Zero leakage (two projects, same key, different results) | NON-NEGOTIABLE |
| 2 | DAG-001 | Diamond dependency correctness | P0 |
| 3 | HEARTBEAT-001 | Agent crash → reclamation → reassignment | P0 |
| 4 | CIRCUIT-001 | Circuit breaker open/close behavior | P0 |
| 5 | RECOVERY-001 | Backup → corrupt → restore → data match | P0 |
| 6 | Idempotency | Exactly-once delivery | P1 |
| 7 | S-to-P Promotion | Memory promotion trigger | P1 |
| 8 | AgentSocialBench Privacy | 352 scenarios, 7 categories | P1 |

**Security is NON-NEGOTIABLE. Performance is a TARGET (<150ms), not a blocker.**
