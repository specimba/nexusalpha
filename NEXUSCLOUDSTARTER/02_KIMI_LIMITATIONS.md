# 02 — KIMI 2.5 LIMITATIONS & WORKAROUNDS

Every Kimi 2.5 session hits these walls. Know them. Work around them. Don't let them break your flow.

---

## Known Limitations

### L1: 10-Step Tool Call Cap Per Message
**What**: Kimi limits to ~10 tool calls (file reads, writes, exec, search) per single message.
**When it hits**: Mid-task execution — "This task was paused because Kimi reached the maximum number of tool calls for a single message."
**Impact**: Autonomous multi-step workflows break mid-execution.

**Workaround**:
1. **Chunk everything**: Design tasks to complete in 8-10 tool calls max
2. **Pre-stage files**: Write content in bulk (multi-file writes, single exec with `cat > file1 && cat > file2`)
3. **Combine reads**: `cat file1 file2 file3` instead of 3 separate reads
4. **Batch edits**: Use `sed` or `python -c` to make multiple changes in one exec call
5. **End with checkpoint**: After chunk completes, checkpoint before next message

### L2: Context Window Exhaustion
**What**: Kimi's context fills up during long sessions. Agent loses earlier conversation context.
**When it hits**: After ~50-100 messages (depends on content size). "High demand. Switched to K2.5 Instant for speed."
**Impact**: Agent forgets project state, decisions, and work done.

**Workaround**:
1. **Compaction before exhaustion**: At ~70% context, type `NEXUS-COMPACT` to trigger summarization
2. **Preset system**: Use trigger words (NEXUS-RESUME, C2-SECURITY) instead of re-explaining
3. **Memory Space entries**: Store atomic facts in Kimi's Memory Space (IDs persist across sessions)
4. **File-based state**: Store state in files (worklog.md, .checkpoints/) not in conversation
5. **Checkpoint-then-new-session**: When context is filling, checkpoint + start fresh with NEXUS-RESUME

### L3: Free-Tier Quota Limits
**What**: Kimi free tier has daily/hourly message and tool call quotas.
**When it hits**: After heavy usage. Rate limiting kicks in.
**Impact**: Session blocked until quota resets.

**Workaround**:
1. **Token-efficient presets**: 84% savings (5000 tokens → 800 tokens per cold start)
2. **Mode switching**: Use K2.5 Instant (cheaper) for reads/status, Thinking (expensive) only for decisions
3. **Batch operations**: Do more per message (within 10-step limit)
4. **Off-peak usage**: Heavy workloads during off-peak hours
5. **Checkpoint frequently**: Don't lose work to quota limits

### L4: Tool Call Loss on Long Sessions
**What**: Long-running Kimi sessions may lose exec tool access after accumulation.
**When it hits**: After many tool calls in a session.
**Impact**: Can't run commands.

**Workaround**:
1. **Isolate sessions**: Each chunk in a fresh or near-fresh session
2. **60-minute max runtime**: Don't run sessions longer than 1 hour
3. **File-based execution**: Write scripts to files, then exec them (not inline code)

### L5: Mode Switching Under Load
**What**: Kimi auto-switches from K2.5 Thinking to K2.5 Instant under high demand.
**When it hits**: During complex multi-step tasks.
**Impact**: Loss of deep reasoning capability mid-task.

**Workaround**:
1. **Pre-plan in Thinking mode**: Do all complex reasoning before execution
2. **Simple execution in Agent mode**: Let Agent mode handle file writes/edits
3. **Don't rely on mode stability**: Plan for mode switches, keep checkpoints

---

## Token Budget Calculator

| Operation | Tokens (est.) | Notes |
|-----------|---------------|-------|
| New session boot (full) | 50,000+ | Reading full conversation — AVOID |
| New session boot (preset) | 800 | NEXUS-RESUME trigger — USE THIS |
| Chunk switch (preset) | 600 | C2-SECURITY, C3-ENGINE, etc. |
| Atomic fix (preset) | 400 | P0-SECRETS, P0-EXEC, etc. |
| File read | 200-2000 | Depends on file size |
| File write | 100-500 | Depends on content |
| Web search | 500-2000 | Depends on results |
| Status check | 200 | Quick health check |
| Full context dump | 50,000+ | NEVER DO THIS |

**Golden Rule**: If you're explaining the project from scratch, you're burning 50,000+ tokens. Use presets instead.

---

## Emergency Protocols

### Context Exhausted Mid-Task
```
Type: NEXUS-COMPACT
→ Preserves: architectural decisions, unresolved blockers, next action
→ Discards: tool outputs, redundant code
→ Creates checkpoint with tag compact-[timestamp]
→ Resume in new session with NEXUS-RESUME
```

### Quota Hit
```
1. Checkpoint current state immediately
2. Save worklog.md update
3. Wait for quota reset
4. Resume with NEXUS-RESUME → last chunk
```

### Files Corrupted
```
Type: NEXUS-ROLLBACK
→ Restores to last good checkpoint (M2-PRE-HARDENING)
→ If persists: rm -rf project && git clone [backup] && restore checkpoint
```

### Agent Forgets Everything
```
1. Type NEXUS-RESUME (if presets installed)
2. OR: Paste 00_BOOT_PROMPT.md into new session
3. OR: Paste 01_PROJECT_STATE.md + "Continue from C[chunk]"
```

---

## Web Research Findings (Solutions)

### From Reddit r/LocalLLaMA — Double-Buffering Technique
"Every LLM agent framework does stop-the-world compaction when context fills — pause, summarize, resume."
**Applied**: NEXUS-COMPACT triggers context summarization, keeps last N messages verbatim, replaces older messages with summary. Preserves turn boundaries (never cut mid-turn).

### From pi-mono (GitHub) — Compaction Architecture
- Trigger at: `contextTokens > model.contextWindow - reserveTokens`
- reserveTokens = 16384 (room for summary output)
- keepRecentTokens = 20000 (preserves recent context verbatim)
- Session file appends compaction events (never inserts mid-file)
- Summary injected as user message with prefix framing
**Applied**: NEXUS-COMPACT follows this pattern. Checkpoint system mirrors it.

### From Agenta Blog — 6 Context Management Techniques
1. Truncation — Cut old messages (lose context)
2. RAG — Retrieve relevant chunks (needs vector DB)
3. Memory buffering — Keep important info in external store
4. Compression — Summarize old messages (preserves gist)
5. Sliding window — Keep last N messages (simple)
6. Hierarchical summarization — Multi-level compression
**Applied**: Preset system uses #3 (Memory Space) + #4 (compaction) + #5 (keep last messages)

### From Claude Code Best Practices
- "Performance degrades as context fills. When context window is getting full, Claude may start forgetting earlier instructions."
- Track context usage continuously
- Give verification criteria (tests, screenshots, expected outputs)
**Applied**: Checkpoint system verifies state after each chunk. Tests validate before proceeding.

### From Kimi K2.5 Capabilities
- Agent Swarm: 100 sub-agents, 1500+ parallel tool calls
- 256k token context window
- 4 modes: Instant, Thinking, Agent, Agent Swarm
- Kimi Claw: 24/7 cloud operation with 40GB storage
**Applied**: Use Agent Swarm for parallel chunk execution. Use Kimi Claw for 24/7 foreman operation.
