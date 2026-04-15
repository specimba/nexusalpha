# 06 — CHECKPOINT SYSTEM

Tar-based version control with Git-equivalent features. Prevents rework.

---

## Quick Reference

| Command | Git Equivalent | What It Does |
|---------|---------------|-------------|
| `python3 scripts/checkpoint.py create <tag>` | `git commit` | Save snapshot |
| `python3 scripts/checkpoint.py list` | `git log` | Show history |
| `python3 scripts/checkpoint.py restore <id>` | `git checkout` | Rollback |
| `python3 scripts/checkpoint.py status` | `git status` | Current state |

## Storage

- Location: `.checkpoints/*.tar.gz`
- Manifest: `.checkpoints/manifest.json`
- Each checkpoint: timestamped tar.gz archive of project root

## When to Checkpoint

| Event | Action |
|-------|--------|
| After each chunk completes | `checkpoint create c[N]-[scope]-done` |
| Before risky changes | `checkpoint create pre-[action]` |
| Context at 70% | `checkpoint create compact-[timestamp]` |
| Test suite passes | `checkpoint create tests-pass-[count]` |
| Milestone reached | `checkpoint create m[N]-[status]` |

## Checkpoint Tags Used

| ID | Tag | What |
|----|-----|------|
| 0 | M0-FOUNDATION | Base swarm init |
| 1 | M1-SECURITY-VALIDATED | C2 complete |
| 2 | M2-PRE-HARDENING | Pre-C3 baseline |
| 3 | c3-engine-realization | C3 complete |

## Rollback Procedure

```bash
# List available checkpoints
python3 scripts/checkpoint.py list

# Restore to specific checkpoint
python3 scripts/checkpoint.py restore 2

# Verify after restore
PYTHONPATH=src pytest tests/ -v --tb=short
```

## Recovery After Failure

1. If files corrupted: `python3 scripts/checkpoint.py restore 2` (last known good)
2. If test suite broke: Restore pre-change checkpoint, re-apply fix
3. If context exhausted: Checkpoint → new session → NEXUS-RESUME
4. If total disaster: `rm -rf project && git clone [backup] && restore 2`
