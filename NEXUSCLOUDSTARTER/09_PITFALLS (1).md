# 09 — PITFALLS (Kimi-Specific)

What NOT to do on Kimi 2.5. Learn from these real failures.

---

## The 5 Kimi Pitfalls

### 1. The 10-Step Trap
**What happened**: Started a multi-step task (9 file writes + 3 tests + checkpoint = 13 calls). Got "This task was paused because Kimi reached the maximum number of tool calls for a single message."
**Why it happened**: Didn't count tool calls before starting.
**Lesson**: Every response must fit in 8-10 tool calls. Count before you start. Pre-stage content.

### 2. The Context Cliff
**What happened**: Long autonomous session ran until Kimi auto-switched from K2.5 Thinking to K2.5 Instant. Lost deep reasoning mid-task.
**Why it happened**: Didn't monitor context usage. Mode switching is automatic under load.
**Lesson**: Checkpoint at 70% context. Don't rely on mode stability. Plan complex work in Thinking, execute in Agent mode.

### 3. The Re-Explanation Waste
**What happened**: Started new session, spent 3 messages re-explaining the project from scratch (50,000+ tokens).
**Why it happened**: No preset system installed. No Memory Space entries.
**Lesson**: Install presets before starting work. NEXUS-RESUME = 800 tokens. Full re-explanation = 50,000+ tokens.

### 4. The Git Sandbox Failure
**What happened**: Tried `git init` in Kimi sandbox. Got symref I/O error. Lost version control.
**Why it happened**: Kimi sandbox has filesystem constraints that don't support Git.
**Lesson**: Use tar-based checkpoint system instead. `checkpoint.py create/restore/list`.

### 5. The Silent Corruption
**What happened**: Changed a file, didn't test, continued to next chunk. Found the change broke imports 3 chunks later.
**Why it happened**: No validation step after changes.
**Lesson**: Every chunk must end with validation (import check, grep verification, or test run). Checkpoint only after validation passes.

---

## Anti-Patterns

| Anti-Pattern | Symptom | Fix |
|--------------|---------|-----|
| **Single-file writes** | 1 tool call per file, 10 files = 10 calls | Bulk write via multi-line exec or Python script |
| **Read-then-edit** | Read file + edit file = 2 calls per change | Write complete replacement, or use Python multi-replace |
| **No checkpoint** | Context exhausted, all work lost | Checkpoint at every chunk boundary |
| **Mode confusion** | Started in Instant, needed Thinking | Plan in Thinking, execute in Agent |
| **Ignoring quota** | Session blocked mid-work | Monitor usage, checkpoint early, batch operations |

---

## Golden Rules for Kimi

1. **Count tool calls before starting.** 8-10 max per message.
2. **Pre-stage everything.** File contents in presets, not read-on-demand.
3. **Checkpoint at 70% context.** Don't wait for "task paused."
4. **Use presets.** NEXUS-RESUME, C[n]-[scope], P0-[issue].
5. **Validate after every change.** Import check minimum.
6. **Right mode for right job.** Thinking=plan, Agent=execute, Instant=status.
7. **Don't re-explain.** If you're describing the project, you're wasting tokens.
8. **File-based state.** worklog.md > conversation memory.
9. **Combine operations.** `sed` + `grep` + `test` in one exec call.
10. **speci wants text, not files.** Copy-paste > download.
