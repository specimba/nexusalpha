# Nexus OS — Unified Token-Efficient Information Architecture Blueprint

A single blueprint for maximizing token efficiency across GLM-5 and Kimi 2.5 systems.

---

## The Core Problem

Every new AI session starts at **zero context**. Rebuilding context from conversation history costs 50,000+ tokens. Within a 100k-token context window, that's 50% gone before you do any work. Within Kimi's free tier with quota limits, that's several days of quota just for re-reading.

**The answer**: Don't rebuild context. **Index it, compress it, reference it.**

---

## The 5-Layer Information Architecture

```
┌─────────────────────────────────────────────────────┐
│  LAYER 5: EXECUTION                                 │
│  "Do the work"                                      │
│  Tokens: 0 (uses tool calls, not conversation)      │
├─────────────────────────────────────────────────────┤
│  LAYER 4: CHUNK PROTOCOL                           │
│  "How to do work within limits"                     │
│  Tokens: ~500 (pre-staged, fits in 10 tool calls)   │
├─────────────────────────────────────────────────────┤
│  LAYER 3: PRESETS / TRIGGERS                       │
│  "Fast recovery shortcuts"                          │
│  Tokens: ~800 (index, not content)                  │
├─────────────────────────────────────────────────────┤
│  LAYER 2: COMPRESSED KNOWLEDGE                      │
│  "What you need to know"                            │
│  Tokens: ~2,000 (tables + terse prose)              │
├─────────────────────────────────────────────────────┤
│  LAYER 1: GROUND TRUTH                              │
│  "The single source of truth"                       │
│  Tokens: ~500 (state file, always current)          │
└─────────────────────────────────────────────────────┘

TOTAL BOOT COST: ~3,800 tokens (vs 50,000+ traditional)
```

---

## Layer 1: Ground Truth (The State File)

**One file. Always current. Everything else references it.**

### What Goes Here
- Current phase and status
- Blockers (with proof-level tags)
- Last checkpoint ID
- Next action
- Test count and pass/fail

### What Does NOT Go Here
- Architecture details (→ Layer 2)
- Historical decisions (→ Layer 2 reference)
- Implementation code (→ Layer 5)
- Full agent rosters (→ Layer 2)

### Rules
1. **Update after every milestone** — this is the first thing read on boot
2. **Maximum 1 page** (~400 tokens). If it's bigger, you're putting detail in the wrong layer
3. **Proof-level tags mandatory**: ✅ ACHIEVED, 🔄 IN PROGRESS, ⏳ PENDING, ❌ BLOCKED
4. **No duplication** — if another file says the same thing, one of them is wrong

### Token Budget: ~400

---

## Layer 2: Compressed Knowledge (Reference Files)

**Domain-specific files, loaded on-demand only.**

### Structure

| File | When Loaded | Tokens |
|------|------------|--------|
| Architecture | Building core system | ~500 |
| Workflow | Review/voting/planning | ~500 |
| Team Roster | Assigning tasks | ~300 |
| Decision Log | Checking rationale | ~400 |
| Limitations | Understanding constraints | ~600 |
| Pitfalls | Before starting new work | ~400 |

### Compression Rules

**Rule 1: Tables over prose**
```
BAD (50 tokens):
"The Bridge implements JSON-RPC 2.0 over HTTP with mandatory headers 
including X-Nexus-Project-ID for isolation, X-Nexus-Task-ID for DAG linking, 
X-Nexus-Lineage-ID for provenance tracking, and X-Nexus-Trace-ID for 
observability correlation."

GOOD (20 tokens):
| Pillar | Protocol | Headers |
|--------|----------|---------|
| Bridge | JSON-RPC 2.0 | Project-ID, Task-ID, Lineage-ID, Trace-ID |
```

**Rule 2: Reference don't repeat**
```
BAD (each section restates):
"Security uses HMAC-SHA256 for..." (×8 sections)

GOOD (one section defines, others reference):
Architecture doc: "Security: HMAC-SHA256 + SecretStore + hard-fail encryption"
Other docs: "Security model per 05_ARCHITECTURE.md"
```

**Rule 3: Link don't inline**
```
BAD:
[Include 500-line code block inline]

GOOD:
"Code: see /src/nexus_os/bridge/server.py (127 lines)"
```

**Rule 4: Decision rationale, not decision history**
```
BAD:
"Agent A proposed X. Agent B disagreed. Agent C suggested Y. After debate..."
(100 tokens of debate history)

GOOD:
"Decision: FTS5-only Phase 1. Rationale: sufficient for MVP, prevents 
premature complexity. Source: majority consensus, Review 2."
(20 tokens, same information)
```

### Token Budget: ~2,000 (loaded on-demand, not all at boot)

---

## Layer 3: Presets / Triggers (Fast Recovery)

**Index cards that point to information, not the information itself.**

### Three Tiers

```
TIER 1: META (System Recovery)
  NEXUS-RESUME  → Restore full state from checkpoint
  NEXUS-STATUS  → Quick health check
  NEXUS-ROLLBACK → Emergency reset
  
  Tokens: ~600 each. Used once per session.

TIER 2: CHUNKS (Execution Units)
  C4-VAULT      → Fix Squeez + MINJA v2
  C5-INTEGRATE  → Full pytest + EVIDENCE.md
  
  Tokens: ~600 each. Used once per chunk.

TIER 3: ATOMIC (Single Actions)
  P0-SECRETS    → Fix hardcoded secrets
  P0-EXEC       → Replace MockExecutor
  
  Tokens: ~400 each. Used for isolated fixes.
```

### Preset Anatomy

```yaml
Trigger: "C4-VAULT"
Content: |
  Execute Chunk C4 Vault Integrity:
  1. Fix observability/squeez.py (return actual results, not dummy)
  2. Integrate MINJA v2 TF-IDF into vault/poisoning.py
  3. Wire trace_id through VaultManager
  4. Checkpoint: c4-vault-done
  Validate: python3 -c "from nexus_os.observability.squeez import SqueezPruner"
```

The preset contains:
- **What** to do (compressed action list)
- **Where** to do it (file paths)
- **How** to verify (validation command)
- **When** done (checkpoint tag)

It does NOT contain:
- Why (→ Layer 2 decision log)
- Full file contents (→ pre-staged in execution)
- Architecture context (→ already loaded)

### Token Budget: ~800 per trigger (vs 50,000 for full re-explanation)

---

## Layer 4: Chunk Protocol (Execution Framework)

**How to fit work within platform limits.**

### Platform-Specific Constraints

| Platform | Limit | Workaround |
|----------|-------|------------|
| Kimi 2.5 free | 10 tool calls/message | Chunk to 8-10 calls, pre-stage content |
| Kimi 2.5 free | Context exhaustion | Checkpoint at 70%, use presets |
| Kimi 2.5 free | Quota limits | Batch ops, mode switching |
| GLM-5 | Varies | Same chunk protocol applies |
| Any LLM | Context degradation at >50% | Summarize-then-resume |

### Chunk Design Formula

```
CHUNK = [Verify State (1-2 calls)]
      + [Execute Work (4-6 calls)]
      + [Validate (1-2 calls)]
      + [Checkpoint (0-1 calls)]
      + [Report (0 calls, inline)]
      = 8-10 total
```

### Token-Saving Execution Patterns

**Pattern 1: Bulk Write**
```bash
# 1 tool call instead of 5
cat > file1.py << 'EOF'
[content]
EOF
cat > file2.py << 'EOF'
[content]
EOF
python3 -c "import file1, file2; print('OK')"
```

**Pattern 2: Combined Operations**
```bash
# 1 tool call instead of 3
sed -i 's/old/new/g' file.py && grep -n 'new' file.py && python3 test.py
```

**Pattern 3: Python Multi-Edit**
```python
# 1 tool call instead of 5 seds
python3 -c "
import pathlib
f = pathlib.Path('file.py')
c = f.read_text()
for old, new in [('a','b'), ('c','d'), ('e','f')]:
    c = c.replace(old, new)
f.write_text(c)
print('3 replacements done')
"
```

### Token Budget: ~500 (protocol is learned once, applied many times)

---

## Layer 5: Execution (Zero Conversation Tokens)

**Work happens here. But it doesn't cost conversation tokens — it costs tool calls.**

### Token-Free Operations

| Operation | Cost | Token Cost |
|-----------|------|------------|
| File write | 1 tool call | ~50 tokens (response) |
| File read | 1 tool call | ~200-2000 tokens (content) |
| Shell exec | 1 tool call | ~100 tokens (output) |
| Web search | 1 tool call | ~500-2000 tokens (results) |
| Test run | 1 tool call | ~200-500 tokens (output) |

### The Key Insight

Most tokens are spent on **reading and writing**, not on **reasoning**. A file write costs ~50 tokens. A re-explanation of the project costs ~50,000 tokens.

**Therefore**: Minimize re-explanation. Maximize file-based state.

```
BAD: Explain the architecture in every session (50,000 tokens)
GOOD: Read the architecture file when needed (500 tokens)
```

---

## Cross-System Integration Blueprint

### GLM-5 ↔ Kimi 2.5 Handoff Protocol

```
GLM-5 Session (full context, no limits)
  ↓
  1. Update worklog.md (ground truth)
  2. Create checkpoint
  3. Update 00_PROJECT_STATE.md (state file)
  ↓
Kimi Session (limited context)
  4. Boot with 00_BOOT_PROMPT.md (~800 tokens)
  5. Auto-read state files (~1,500 tokens)
  6. Resume from checkpoint
  ↓
  7. Execute chunk
  8. Update worklog.md
  9. Checkpoint
  ↓
Hand back to GLM-5 (or continue on Kimi)
```

### Shared State Files (The Bridge)

Both systems read/write the same files:

| File | GLM-5 | Kimi | Purpose |
|------|-------|------|---------|
| worklog.md | ✅ Write | ✅ Write | Ground truth — latest work done |
| 00_PROJECT_STATE.md | ✅ Write | ✅ Read | Current phase, blockers, next action |
| .checkpoints/ | ✅ Write | ✅ Read/Write | State snapshots |
| .task.md queue | ✅ Write | ✅ Write | Task coordination |
| MEMORY.md | ✅ Write | ❌ Skip | Long-term memory (GLM-5 only) |

### Mode Selection Guide

| Task | Best System | Why |
|------|------------|-----|
| Architecture decisions | GLM-5 | No limits, full context |
| Complex debugging | GLM-5 | Can read entire codebase |
| Long autonomous runs | Kimi (Agent mode) | 24/7 cloud, persistent |
| Quick fixes | Kimi (Instant mode) | Fast, cheap |
| Deep research | Kimi (Thinking mode) | 256k context |
| Parallel execution | Kimi (Agent Swarm) | 100 sub-agents |
| Review/voting | GLM-5 | Full conversation history |
| Checkpoint/backup | Either | Shared checkpoint system |

---

## Token Budget Calculator

### Per-Session Budget (Kimi 2.5 free tier)

```
ESTIMATED DAILY TOKEN BUDGET: ~100,000 tokens (varies by quota)

BOOT COST (once per session):
  Preset trigger:           800 tokens
  State files:            1,500 tokens
  Limitations awareness:    600 tokens
  ─────────────────────────────
  Total boot:             2,900 tokens

PER-CHUNK COST (repeat per chunk):
  Preset trigger:           600 tokens
  File reads:             1,000 tokens
  Execution output:         500 tokens
  Validation:               300 tokens
  Status report:            200 tokens
  ─────────────────────────────
  Total per chunk:        2,600 tokens

CHUNKS PER SESSION:
  (100,000 - 2,900) / 2,600 = ~37 chunks/day

VS. TRADITIONAL (no presets):
  Boot: 50,000 tokens
  Per-chunk: 5,000 tokens (with re-explanation)
  Chunks per session: (100,000 - 50,000) / 5,000 = 10 chunks/day

EFFICIENCY GAIN: 37 / 10 = 3.7× more work per day
```

### Per-Session Budget (GLM-5, no limits)

```
BOOT COST: N/A (context persists across messages)
PER-CHUNK COST: ~500 tokens (mostly output)
CHUNKS PER SESSION: Unlimited

TOKEN SAVINGS: N/A (no quota limits)
BUT: Time savings from not re-explaining = faster iteration
```

---

## Maintenance Rules

### When to Update What

| Event | Update This |
|-------|------------|
| Milestone completed | 00_PROJECT_STATE.md + worklog.md |
| New decision made | Decision log + 00_PROJECT_STATE.md |
| New blocker found | 00_PROJECT_STATE.md (proof-level tag) |
| New pitfall discovered | Pitfalls file |
| Phase change | Phase roadmap + 00_PROJECT_STATE.md |
| Checkpoint created | Checkpoint manifest + worklog.md |
| New agent added | Team roster |
| Scope changed | Decision log + Phase roadmap |

### What NEVER Changes

| Item | Why |
|------|-----|
| 4 pillars | Locked across 4 review cycles |
| S-P-E-W | Locked |
| MVP scope IN/OUT | Locked |
| Boot prompt structure | Process, not project data |
| Chunk protocol | Platform constraint, not project scope |

### The Golden Rule

```
IF you're explaining the project from scratch:
  → You're in the wrong layer
  → Go to Layer 1 (state file)
  → Go to Layer 3 (presets)
  → Don't rebuild context — recover it
```

---

## Summary: The Complete Token Strategy

```
┌──────────────────────────────────────────────┐
│           INFORMATION ARCHITECTURE           │
├──────────────────────────────────────────────┤
│                                              │
│  Layer 1: STATE (400 tokens)                 │
│    → Where are we RIGHT NOW?                 │
│    → Updated after every milestone           │
│                                              │
│  Layer 2: KNOWLEDGE (2,000 tokens, on-demand)│
│    → What do I need to know?                 │
│    → Compressed tables, not prose            │
│                                              │
│  Layer 3: PRESETS (800 tokens)               │
│    → How do I recover fast?                  │
│    → Index cards, not encyclopedias          │
│                                              │
│  Layer 4: PROTOCOL (500 tokens)              │
│    → How do I work within limits?            │
│    → Chunk design, platform constraints      │
│                                              │
│  Layer 5: EXECUTION (0 conversation tokens)  │
│    → Do the work                             │
│    → Tool calls, not conversation            │
│                                              │
├──────────────────────────────────────────────┤
│  BOOT COST: ~3,700 tokens                    │
│  TRADITIONAL: ~50,000 tokens                 │
│  SAVINGS: 93%                                │
│  GAIN: 3.7× more work per quota period       │
└──────────────────────────────────────────────┘
```

**The principle**: Information has a hierarchy. State → Knowledge → Presets → Protocol → Execution. Each layer references the one above it. You never rebuild — you recover. You never re-explain — you reference. You never inline — you index.

That's how you turn 50,000 tokens of context waste into 3,700 tokens of context efficiency.

Regards,
{{}}
