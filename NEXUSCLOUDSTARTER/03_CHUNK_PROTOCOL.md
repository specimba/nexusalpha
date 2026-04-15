# 03 — CHUNK PROTOCOL

How to work within Kimi's 10-step limit without losing flow.

---

## The Chunk System

Every task is broken into **chunks** that fit within 8-10 tool calls per message.

```
CHUNK = [Objective] + [8-10 tool calls] + [Checkpoint] + [Status Report]
```

### Chunk Anatomy

| Component | Purpose | Tool Calls |
|-----------|---------|------------|
| Verify state | Confirm where we are | 1-2 |
| Execute work | The actual task | 4-6 |
| Validate | Test/check results | 1-2 |
| Checkpoint | Save state for rollback | 0-1 |
| Report | Tell speci what happened | 0 |

**Total**: 8-10 tool calls. If you're at 9, checkpoint and stop. Next chunk continues.

---

## Chunk Design Rules

### Rule 1: Pre-Stage Everything
Before the chunk starts, the preset should contain all file contents needed.

**Bad** (wastes tool calls):
```
1. Read file A
2. Read file B  
3. Edit file A (change line 45)
4. Edit file B (change line 12)
5. Write test file C
6. Run tests
7. Read test output
8. Update worklog
9. Create checkpoint
= 9 calls, barely fits
```

**Good** (pre-staged):
```
1. Write files A, B, C (bulk write via multi-line exec)
2. Run tests
3. Checkpoint
= 3 calls, 6 remaining for edge cases
```

### Rule 2: Combine Operations
Use shell operators to combine multiple operations:

```bash
# BAD: 3 tool calls
cat file1.py
cat file2.py  
python3 test.py

# GOOD: 1 tool call
cat file1.py file2.py && python3 test.py
```

### Rule 3: Write First, Read Later
Don't read files just to verify — write confidently and test:

```bash
# Write + test in one call
cat > new_file.py << 'EOF'
[content]
EOF
python3 -c "import new_file; print('OK')"
```

### Rule 4: Use Python for Multi-Edits
Instead of multiple sed/awk calls:

```python
# One Python call replaces 5 sed calls
python3 -c "
import pathlib
f = pathlib.Path('file.py')
c = f.read_text()
c = c.replace('old1', 'new1')
c = c.replace('old2', 'new2')
c = c.replace('old3', 'new3')
f.write_text(c)
print('3 replacements done')
"
```

### Rule 5: Checkpoint at 70%
Don't wait for context exhaustion. At ~70% context:
1. Create checkpoint
2. Update worklog
3. Report to speci
4. Start fresh session with NEXUS-RESUME if needed

---

## Standard Chunk Templates

### C4-VAULT (Squeez fix + MINJA v2)
```
Tool calls: 8-10
1. Write fixed squeez.py (pre-staged content)
2. Write MINJA v2 integration into poisoning.py
3. Run: python3 -c "from nexus_os.observability.squeez import *; print('import OK')"
4. Run: python3 -c "from nexus_os.vault.poisoning import MINJA; print('MINJA OK')"
5. Write test file
6. Run: PYTHONPATH=src pytest tests/test_vault_integrity.py -v
7. Checkpoint: c4-vault-integrity
8. Update worklog.md
```

### C5-INTEGRATE (Full pytest + EVIDENCE.md)
```
Tool calls: 8-10
1. Run: PYTHONPATH=src pytest tests/ -v --tb=short
2. Capture output to evidence
3. Write EVIDENCE.md with test results + commit hashes
4. Run: git add . && git commit -m "M3 hardening complete"
5. Run: git tag -a m3-hardened -m "M3 gate passed"
6. Checkpoint: m3-hardened
7. Update worklog.md + STATUS.md
```

### P0-SECRETS (Single atomic fix)
```
Tool calls: 3-5
1. Write fixed bridge/server.py (remove AGENT_SECRETS, wire SecretStore)
2. Run: python3 -c "from nexus_os.bridge.server import *; print('import OK')"
3. Run: grep -n 'AGENT_SECRETS' bridge/server.py || echo 'CLEAN'
4. Checkpoint: pre-secrets
```

---

## Chunk Lifecycle

```
PLAN (in Thinking mode)
  ↓
PREPARE (write preset with pre-staged content)
  ↓
EXECUTE (run chunk in Agent mode, 8-10 calls)
  ↓
VALIDATE (test/check results)
  ↓
CHECKPOINT (save state)
  ↓
REPORT (tell speci)
  ↓
NEXT CHUNK (or PAUSE if quota/context exhausted)
```

### If Chunk Fails Mid-Execution
1. Don't panic
2. Type `continue` to resume
3. If "task paused" message appears, type `continue`
4. If context is truly exhausted, checkpoint + new session with NEXUS-RESUME

---

## Parallel Chunk Execution (Agent Swarm)

For independent chunks, use Kimi's Agent Swarm mode:

```
Lead Agent: Coordinates, receives results
Worker 1: C4-VAULT (Squeez + MINJA)
Worker 2: P0-DFS (cycle detection fix)
Worker 3: Test writing
Worker 4: Documentation (EVIDENCE.md)

Speedup: 4x vs serial execution
```

When to use parallel:
- Independent file changes (different modules)
- Test writing + implementation (different concerns)
- Documentation + code (no dependencies)

When NOT to use parallel:
- Sequential dependencies (A depends on B)
- Shared state (both writing to same file)
- Small tasks (overhead > benefit)
