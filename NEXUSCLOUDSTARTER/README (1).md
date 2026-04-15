# Kimi 2.5 Nexus OS Swarm — Conversation Starter Pack

A token-efficient, limitation-aware starter pack for Kimi 2.5 sessions running the Nexus OS Swarm Controller.

## What This Is

This pack restores full Nexus OS project context into a new Kimi 2.5 session while **staying within Kimi's sandbox limitations**: 10-step tool call cap per message, context window exhaustion, free-tier quota limits. Every file is designed for minimum token burn and maximum recovery speed.

## File Map

| File | Purpose | Tokens (est.) | Read When |
|---|---|---|---|
| `00_BOOT_PROMPT.md` | THE PROMPT — paste into new Kimi session | ~800 | **EVERY NEW SESSION** |
| `01_PROJECT_STATE.md` | Where we are right now | ~400 | Boot sequence step 1 |
| `02_KIMI_LIMITATIONS.md` | Sandbox constraints + workarounds | ~600 | Boot sequence step 2 |
| `03_CHUNK_PROTOCOL.md` | How to work within 10-step limit | ~500 | Boot sequence step 3 |
| `04_PRESET_SYSTEM.md` | Trigger words for fast recovery | ~400 | Reference as needed |
| `05_ARCHITECTURE.md` | 4 pillars + S-P-E-W (compressed) | ~500 | When building |
| `06_CHECKPOINT_SYSTEM.md` | Backup/restore/rollback | ~400 | Before each chunk |
| `07_DECISION_LOG.md` | Key decisions (compressed) | ~400 | When checking rationale |
| `08_TEAM_AGENTS.md` | Agent roster + roles | ~300 | When assigning |
| `09_PITFALLS.md` | What NOT to do | ~400 | Before starting work |

## Boot Sequence (New Kimi Session)

```
PASTE: 00_BOOT_PROMPT.md (triggers auto-read of state files)
TYPE: NEXUS-RESUME (if presets are installed)
TYPE: C[chunk]-[scope] to start work
TYPE: NEXUS-CHECKPOINT when done
```

## Token Budget

| Component | Tokens |
|---|---|
| Boot prompt | ~800 |
| State recovery (auto) | ~400 |
| Limitations awareness | ~600 |
| Work context | ~500 |
| **Total boot cost** | **~2,300** |

**vs. full conversation history**: 40,000+ lines = ~50,000+ tokens
**Savings**: ~95%

## Origins

Built from 9 source files:
- Kimi 2.5 conversation history (last session, context exhaustion)
- GLM-5 deployment plan + Phase 1 milestone
- A2A scoring/memory/governance spec
- DoppelGround × Nexus collaboration spec
- Agentic team research
- Kimi swarm starter code

Date: 2026-04-14
Project: Nexus OS A2A (Agent-to-Agent) System
Platform: Kimi 2.5 (kimi.com free tier)
```
