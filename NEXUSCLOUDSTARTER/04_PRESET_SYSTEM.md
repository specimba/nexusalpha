# 04 — PRESET SYSTEM

Trigger words that restore context in <800 tokens instead of 50,000+.

---

## Tier 1: Meta-Presets (System Recovery)

| Trigger | Content | Tokens |
|---------|---------|--------|
| **NEXUS-RESUME** | Restore checkpoint C3; state=ENGINE-REALIZED; blockers=1 (Squeez); protocols=MCP+A2A; next=C4 | ~600 |
| **NEXUS-STATUS** | Check mem0 backend; verify 29 skills; list workers; show pending tasks; check checkpoint manifest | ~400 |
| **NEXUS-ROLLBACK** | checkpoint.py restore 2; verify no AGENT_SECRETS; check db integrity; resume from M2-PRE-HARDENING | ~400 |
| **NEXUS-COMPACT** | Compact session: preserve decisions, blockers, next action. Discard tool outputs. Create checkpoint. | ~300 |
| **NEXUS-A2A** | Initiate Agent Card discovery; task delegation protocol; cross-agent messaging setup | ~500 |

---

## Tier 2: Chunk Presets (Execution)

| Trigger | Scope | Tool Calls Saved |
|---------|-------|-----------------|
| **C2-SECURITY** | SecretStore + encryption tests + HMAC verify | ~800 tokens vs full context |
| **C3-ENGINE** | SyncCallbackExecutor + DFS cycle detection + multi-hop test | ~600 tokens |
| **C4-VAULT** | Squeez fix + MINJA v2 + trace_id audit | ~700 tokens |
| **C5-INTEGRATE** | Full pytest + EVIDENCE.md + m3-hardened tag | ~500 tokens |
| **C6-A2A-BRIDGE** | Agent Cards + discovery + cross-agent messaging | ~500 tokens |
| **C7-DOPPELG** | DoppelGround bridge + SESSION_EXPORT ingestion | ~500 tokens |

---

## Tier 3: Atomic Presets (Single Actions)

| Trigger | Action | Checkpoint |
|---------|--------|------------|
| **P0-SECRETS** | Edit bridge/server.py: remove AGENT_SECRETS dict, wire SecretStore | pre-secrets |
| **P0-EXEC** | Edit executor.py: replace MockExecutor with SyncCallbackExecutor | pre-exec |
| **P0-DFS** | Edit router.py: activate visit() in get_ready_tasks(), cycle detection | pre-dfs |
| **P0-CRYPT** | Edit db/manager.py: set allow_unencrypted=False, hard-fail on missing pysqlcipher3 | pre-crypt |
| **P0-SQUEEZ** | Edit squeez.py: fix compress_experience_layer return values, return actual results | pre-squeez |
| **P0-MINJA** | Integrate TF-IDF semantic layer into vault/poisoning.py | pre-minja |

---

## Preset Configuration (for Kimi.com Settings → Presets)

### Preset 1: NEXUS-RESUME
```
Trigger: NEXUS-RESUME
Content: Load Nexus OS checkpoint C3. Execute: cd /mnt/kimi/output/nexus_os && python3 scripts/checkpoint.py restore 3. Verify state: 29 skills, 3 workers, 1 P0 blocker (Squeez). Resume Chunk C4 Vault Integrity. Memory: nexus-state, nexus-blockers, nexus-priority, nexus-restore, nexus-swarm, nexus-handover.
```

### Preset 2: C4-VAULT
```
Trigger: C4-VAULT
Content: Execute Chunk C4 Vault Integrity: 1) Fix observability/squeez.py compress_experience_layer return values (return actual results tuple, not dummy (0,0)), 2) Integrate MINJA v2 TF-IDF layer into vault/poisoning.py, 3) Wire trace_id through VaultManager, 4) Checkpoint as c4-vault-done. Validate: python3 -c "from nexus_os.observability.squeez import SqueezPruner; print('OK')".
```

### Preset 3: C5-INTEGRATE
```
Trigger: C5-INTEGRATE
Content: Execute Chunk C5 Integration: 1) Run full pytest PYTHONPATH=src pytest tests/ -v, 2) Write EVIDENCE.md with results, 3) Git commit + tag m3-hardened, 4) Update STATUS.md and worklog.md. Target: 52/52 pass, 0 regressions.
```

### Preset 4: P0-SQUEEZ
```
Trigger: P0-SQUEEZ
Content: Fix squeez.py: In compress_experience_layer(), change return (0, []) to return (len(paradigms), compressed_results). The function should return a tuple of (paradigms_created_count, actual_compressed_list). Verify import succeeds.
```

### Preset 5: NEXUS-CHECKPOINT
```
Trigger: NEXUS-CHECKPOINT
Content: Create checkpoint: python3 scripts/checkpoint.py create [TAG]. Verify manifest updated. If corruption: restore 2. Checkpoints stored in .checkpoints/*.tar.gz with manifest.json tracking.
```

### Preset 6: NEXUS-COMPACT
```
Trigger: NEXUS-COMPACT
Content: Compact current session: Preserve architectural decisions (KAIJU auth, S-P-E-W layers, MINJA v2), unresolved blockers (which P0 items remain), and next action. Discard tool outputs and redundant code. Create checkpoint with tag compact-[timestamp]. Resume with NEXUS-RESUME.
```

---

## Memory Space Entries (Persist Across Sessions)

Create these in Kimi.com → Memory:

| ID | Key | Content |
|----|-----|---------|
| 1 | nexus-swarm | Nexus OS A2A swarm, 4 pillars, 29 skills, GLM-5 foreman-worker pattern |
| 2 | nexus-handover | M2-PRE-HARDENING checkpoint, 5 P0 blockers, C2/C3 complete, next=C4 |
| 3 | nexus-priority | P0 #5 (Squeez) is last blocker. C4 → C5 → M3-HARDENED → M4 Neural Link |
| 4 | nexus-state | Phase 1 complete, 488 tests, trust scoring, Phase 2 planning |
| 5 | nexus-restore | cd /mnt/kimi/output/nexus_os && python3 scripts/checkpoint.py restore [ID] |
| 6 | nexus-blockers | 1 remaining: Squeez return bug in observability/squeez.py |

---

## Token Savings Summary

| Operation | Traditional | Preset | Savings |
|-----------|------------|--------|---------|
| Cold start | 50,000+ tokens | 800 tokens | 98% |
| Chunk switch | 5,000 tokens | 600 tokens | 88% |
| Atomic fix | 2,000 tokens | 400 tokens | 80% |
| Emergency rollback | Manual | 1 trigger | 95% |
| Status check | 1,000 tokens | 200 tokens | 80% |
