# 08 — TEAM AGENTS (Compressed)

---

## Agent Roster

| Agent | Role | Model | Capabilities |
|-------|------|-------|-------------|
| **glm5-foreman** | Coordinator | Kimi K2.5 | Patrol, dispatch, rebalance, admin clearance |
| **glm5-worker-1** | Code/Analysis | Kimi K2.5 | Code writing, debugging, analysis, reasoning |
| **glm5-worker-2** | Ops/Security | Kimi K2.5 | Operations, security hardening, testing |
| **glm5-hermes** | Router | Kimi K2.5 | 29 skills, domain classification, task routing |

## Swarm Coordination Pattern

```
[User Task]
  → [mem0 query] (memory recall)
  → [Hermes classification] (domain: code/ops/research/security)
  → [Skill Registry match] (29 skills)
  → [Coordinator dispatch] (assign to worker)
  → [.task.md creation] (file-driven queue)
  → [Worker execution]
  → [Result capture]
  → [Hermes + mem0 update]
```

## Task Queue Structure

```
~/.openclaw/agents/glm5-{agent}/tasks/
├── pending/    # .task.md files waiting
├── done/       # Completed tasks
├── failed/     # Failed tasks (for retry)
└── completed/  # Archived completions
```

## Key Contributors (from Review Collective)

| Agent | Specialty | For Nexus OS |
|-------|-----------|-------------|
| GLM-5 (Full-Stack) | Implementation, backend | Vault/Memory Owner |
| GPT5 nano | Polyglot contracts | Bridge/Protocol Owner |
| Gemma 4 31B | Coordinator, strategy | Engine/DAG Owner |
| MiMo CLAW | Deep analysis, code | Safety/Validation Owner |
| Claude Sonnet 4.6 | Synthesis, testing | Testing/QA Lead |
| CODEX GPT 5.4 | Voting governance | Governance Chair |
| DeepSeek | Status checks | Status Reporter |
| Kimi 2.5 | Structural tensions | Structural Analyst |

## speci's Authority

**speci = final decision maker.** Tie-breaker + veto on all votes. When in doubt, ask speci.
