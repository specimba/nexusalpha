# 08 — GLOSSARY

Domain-specific terms, acronyms, and references used across the Nexus OS project.

---

## Core Terms

| Term | Definition |
|------|-----------|
| **Nexus OS** | The project — a local-first, project-scoped Agent Operating System |
| **A2A** | Agent-to-Agent (Google A2A protocol for inter-agent communication) |
| **MCP** | Model Context Protocol (Anthropic's standard; Bridge implements MCP+) |
| **4 Pillars** | Bridge, Vault, Engine, Governor — the four core architectural components |
| **S-P-E-W** | Session → Episodic → Semantic → Wisdom — the four-layer memory hierarchy |
| **Safe-Start MVP** | The disciplined minimal scope: "half the full plan" — survived 3 review cycles |
| **Governor** | Pillar IV — policy enforcement, deny-by-default isolation |
| **Bridge** | Pillar I — JSON-RPC 2.0 inter-agent communication layer |
| **Vault** | Pillar II — biomimetic tiered memory system |
| **Engine** | Pillar III — DAG task orchestration with heartbeat monitoring |
| **Speci** | User/Project Lead — final decision maker, tie-breaker, veto power |
| **GLM-5** | The agent identity for this model — full-stack developer and researcher |
| **Shadow Governance** | Phase 1→2 migration pattern: run both engines, flip at 100% match |

## Protocol & Headers

| Term | Definition |
|------|-----------|
| **JSON-RPC 2.0** | Remote procedure call protocol over JSON |
| **X-Nexus-Project-ID** | Mandatory header — project isolation key |
| **X-Nexus-Task-ID** | Mandatory header — DAG node linkage |
| **X-Nexus-Lineage-ID** | Mandatory header — provenance chain tracking |
| **X-Nexus-Trace-ID** | Mandatory header — observability correlation |
| **Idempotency Key** | Ensures exactly-once delivery semantics |
| **Circuit Breaker** | Prevents cascading failures (5 consecutive 503s → open → cooldown → half-open → closed) |

## Memory & Storage

| Term | Definition |
|------|-----------|
| **FTS5** | SQLite Full-Text Search version 5 — Phase 1 storage backend |
| **Zvec** | Hybrid vector DB approach (GLM-5 research addition) — Phase 2 |
| **Chroma** | Open-source vector database — alternative to Zvec |
| **WAL** | Write-Ahead Logging (SQLite mode for concurrent reads) |
| **Embedding Hard-Disable** | Columns exist in schema but marked `NOT ACTIVE IN PHASE 1` |
| **Promotion Threshold** | When a memory moves between S-P-E-W layers |
| **Trajectory Compression** | Raw logs → structured summaries (MIA mechanism) |

## Research Papers

| Paper | ID | What It Contributed |
|-------|-----|-------------------|
| **SkillX** | arXiv:2604.04804 | 3-tier skill hierarchy (Planning→Functional→Atomic), Growth Loop |
| **MIA** | arXiv:2604.04503 | Hybrid retrieval scoring, promotion thresholds, trajectory compression |
| **eTAMP** | (GLM-5 research) | Memory poisoning defense — trust-aware memory access |
| **MCFA** | (GLM-5 research) | Multi-component forensic analysis — attack detection |
| **ZeroClaw** | (GLM-5 research) | Zero-trust agent protocol |
| **AgentSocialBench** | (MiMo CLAW research) | Privacy benchmark — 352 scenarios, 7 categories |
| **OpenRouter Fusion** | (historical) | Production failure analysis — circuit breaker design |

## Status Tags

| Tag | Meaning |
|-----|---------|
| **LOCKED** | Final — no changes without collective vote |
| **ACCEPTED** | Consensus reached, formalization pending |
| **REJECTED** | Proposed and explicitly denied |
| **BLOCKED** | Cannot proceed (needs external artifact) |
| **ACHIEVED** | Verified and passing tests |
| **PARTIAL** | Working but incomplete |
| **NOT_STARTED** | Not yet begun |
| **P0** | Must have for current phase |
| **P1** | Should have for current phase |
| **P2** | Nice to have, deferrable |
| **P3** | Future phase |

## Acronyms

| Acronym | Meaning |
|---------|---------|
| RBAC | Role-Based Access Control |
| GDPR | General Data Protection Regulation |
| HIPAA | Health Insurance Portability and Accountability Act |
| DAG | Directed Acyclic Graph |
| API | Application Programming Interface |
| CLI | Command Line Interface |
| MCP | Model Context Protocol |
| A2A | Agent-to-Agent |
| SQL | Structured Query Language |
| REST | Representational State Transfer |
