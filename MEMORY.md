# MEMORY.md — Long-Term Memory

## Identity
- I am KiloClaw, running on OpenClaw/KiloClaw platform
- Model: kilocode/kilo-auto/balanced (dynamic routing)
- Workspace: /root/.openclaw/workspace

---

## Key Person: speci
- Building Nexus OS — a local-first Agent Operating System
- Direct, no-filler communication style
- Proof tags required: FILE_CONFIRMED | CODE_CONFIRMED | INFERRED
- Final authority on all project decisions
- Sign-off: "regards, speci"

---

## Nexus OS — Project State (as of 2026-04-15)
**Ground truth doc**: 01_PROJECT_STATE.md v2.2 | Sessions: 6 (GLM-5×4, Kimi×3, MiMo×3)

### Architecture (LOCKED — 4 pillars, never re-debate)
- **Bridge** (I): JSON-RPC 2.0, SDK, HMAC-SHA256 auth, circuit breaker, SecretStore. 4 mandatory headers: X-Nexus-Project-ID, X-Nexus-Task-ID, X-Nexus-Lineage-ID, X-Nexus-Trace-ID
- **Vault** (II): S-P-E-W layers (Session→RAM, Episodic→SQLite FTS5, Semantic→SQLite, Wisdom→SQLite). Phase 1: FTS5 only, vector HARD-DISABLED. Phase 2: Zvec/FAISS
- **Engine** (III): DAG routing, DFS cycle detection, Hermes 3-layer router, skill adapter, heartbeat (30s), forge
- **Governor** (IV): KAIJU→CVA→Compliance chain. Deny-by-default. AEGIS 3-stage firewall. OWASP ASI Top 10. Proof chains (SHA-256). Policy-as-Code YAML. Goodhart detection.

### Phase Status
- Phase 1: ✅ COMPLETE (488 tests) — trust scoring, lane-scoped, context injection
- Phase 2: 🔄 IN PROGRESS (978 tests, 0 failures) — milestones 7-A through 8-D all ✅
- M3 Hardened ✅, M4 Neural Link ✅ (A2A+MCP dual-stack, 4 agents, 4 MCP servers)
- Ultra-Compact v2.0 ✅ (250 token boot, 99.5% savings)
- 23 integration targets: P0×5, P1×5, P2×8, P3×5

### P0 Integration Targets (blocking Phase 2 completion)
1. OWASP ASI Top 10 — IN_PROGRESS
2. AutoHarness pipeline — IN_PROGRESS (spec written, needs engine/autoharness.py)
3. **A2A v1.0 compliance** — NOT_STARTED (gap analysis vs current bridge)
4. **VAP 4-layer audit trail** — NOT_STARTED (L1 Identity + L2 Provenance, SHA-256 + Ed25519)
5. **SkillFortify trust algebra** — NOT_STARTED (4-level trust + ASBOM)

### Critical Code Gaps (P0 bugs)
1. **ASI04** — Supply chain: No trust verification on skill loading, no ASBOM
2. **ASI02** — Tool misuse: No risk_level on SkillDefinition in skill_adapter.py
3. **Bridge bug** — `is_registered` never set in context → deny-by-default blocks authenticated agents
4. **Executor timeout** — default_timeout=30 set but NEVER ENFORCED in execute()
5. **ASI10** — Kill switch: KAIJU HOLD queue exists but no real-time termination

### Locked Fixes (decisions final, do not re-debate)
- `bridge/server.py`: add `context["is_registered"] = True` after auth
- `executor.py`: wrap handler() in threading.Timer (45s per I2 decision)
- `sdk.py`: timeout 30 → 45 (I2: speci decision 2026-04-14)
- `skill_adapter.py`: add `risk_level: str = "MEDIUM"` to SkillDefinition
- AutoHarness: rule-based YAML first (I1), ML deferred
- CRITICAL actions → KAIJU HOLD queue for human approval (I3)
- Fail-closed (I4): pipeline crash → reject + log
- YAML constitution hot-reload via file-watch (I5)

### Stack
- Runtime: OpenClaw (KiloClaw)
- Memory backend: mem0ai (3-tier: mem0ai → SQLite → in-memory)
- Language: Python 3 / pytest
- Security: OWASP ASI Top 10 + CSA-TRUST-01 + IMDA-MGF
- Source: downloads/NexusOS_All_Source_Code.md (Phase1, 550KB), NexusOS_Phase2_All_Source.md (239KB)

### Critical Path
`ASI04 (SkillFortify) → ASI02 (Tool Misuse) → AutoHarness → ASI03 (Identity) → A2A v1.0`

### Quick Wins (5-30 min each)
1. Fix bridge compliance bug — 5 min
2. Fix executor timeout (threading.Timer, 45s) — 5 min
3. Add risk_level to SkillDefinition — 5 min
4. `pip install skillfortify` + integrate trust algebra — 20 min

---

## Research Context (Active Tracking)
Topics of interest for speci's work:
- A2A protocol standards (Google A2A, Anthropic MCP)
- OWASP ASI updates (especially ASI02, ASI04, ASI06, ASI10)
- Supply chain attacks on AI agents / skill verification
- Memory poisoning defenses for agent systems
- Multi-agent trust and Bayesian scoring advances
- Competitor moves: AutoGen, CrewAI, LangGraph, OpenAI Swarm

---

## Session Log
- 2026-04-15: First contact with speci. Read project files (00_BOOT, 02_OPENCLAW_SETUP, 05_GOVERNANCE, 06_SOURCE_MAP). Set up HEARTBEAT.md with Nexus OS research checklist. Updated USER.md and MEMORY.md.
