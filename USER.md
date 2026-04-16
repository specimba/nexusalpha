# USER.md - About Your Human

- **Name:** speci
- **What to call them:** speci
- **Pronouns:** —
- **Timezone:** unknown (UTC assumed)
- **Notes:** Direct communicator. No filler. Expects proof tags (FILE_CONFIRMED | CODE_CONFIRMED | INFERRED). Final authority on all decisions.

## Context

Building **Nexus OS** — a local-first Agent Operating System.

**4 Pillars:**
- **Bridge** — JSON-RPC 2.0, SDK, HMAC-SHA256 auth, circuit breaker
- **Vault** — S-P-E-W memory layers, Ebbinghaus trust decay, Bayesian HPv3 scoring
- **Engine** — DAG routing, DFS cycle detection, Hermes 3-layer router, skill adapter
- **Governor** — KAIJU auth, AEGIS firewall, OWASP ASI compliance, AutoHarness pipeline, proof chains

**Current Phase:**
- Phase 1 ✅ (488 tests passing)
- Phase 2 🔄 in progress (978 tests, 7 milestones: M3-HARDENED ✅, M4 Neural Link ✅)
- 23 integration targets tracked

**Critical Open Gaps (P0):**
- ASI04 supply chain — SkillFortify trust verification missing
- ASI02 tool misuse — No risk_level on SkillDefinition
- Bridge compliance bug — `is_registered` never set in context
- ASI06 memory poisoning — stub only, no real defense
- ASI10 rogue agents — no kill switch

**Known Fixes Queued:**
- `bridge/server.py`: add `context["is_registered"] = True` after auth
- `executor.py`: enforce `default_timeout=30` via threading.Timer
- `sdk.py`: change timeout 30→45 per speci decision
- `skill_adapter.py`: add `risk_level: str = "MEDIUM"` to SkillDefinition

**Tech Stack:**
- Runtime: OpenClaw (KiloClaw)
- Memory: mem0ai (3-tier fallback: mem0ai → SQLite → in-memory)
- Language: Python 3
- Testing: pytest
- Security: OWASP ASI Top 10, CSA-TRUST, IMDA-MGF

**Research interests:**
- A2A protocol standards, multi-agent trust, LLM governance
- OWASP ASI updates, supply chain AI attacks, tool misuse detection
- DAG orchestration, Bayesian trust, memory poisoning defenses
- Competitor moves: AutoGen, CrewAI, LangGraph, OpenAI Swarm, Google A2A, Anthropic MCP

**Style:**
- No filler, no pleasantries in technical docs
- Proof tags required on all code/file claims
- Direct decisions, no re-debating locked items
- Sign-off: "regards, speci"
