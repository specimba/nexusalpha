#!/usr/bin/env python3
"""
GLM-5 Foreman — Patrol Agent
Monitors worker task queues, balances load, detects stalls, logs activity.
Runs via OpenClaw cron every 30 minutes or manually.
"""

import os
import re
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path.home() / ".openclaw" / "agents"
WORKERS = [BASE / "glm5-worker-1", BASE / "glm5-worker-2"]
FOREMAN = BASE / "glm5-foreman"
MEMORY_DIR = FOREMAN / "memory"
FOREMAN_LOG = MEMORY_DIR / "foreman-log.md"
STALL_THRESHOLD = timedelta(minutes=10)

def read_frontmatter(filepath: Path) -> dict:
    """Parse YAML frontmatter from a Markdown file."""
    text = filepath.read_text()
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm

def count_pending(worker_dir: Path) -> int:
    pending = worker_dir / "tasks" / "pending"
    if not pending.exists():
        return 0
    return len(list(pending.glob("*.task.md")))

def count_done(worker_dir: Path) -> int:
    done = worker_dir / "tasks" / "done"
    if not done.exists():
        return 0
    return len(list(done.glob("*.task.md")))

def count_failed(worker_dir: Path) -> int:
    failed = worker_dir / "tasks" / "failed"
    if not failed.exists():
        return 0
    return len(list(failed.glob("*.task.md")))

def find_stalled_tasks(worker_dir: Path) -> list:
    """Find tasks in_progress for longer than STALL_THRESHOLD."""
    pending = worker_dir / "tasks" / "pending"
    stalled = []
    if not pending.exists():
        return stalled
    now = datetime.now(timezone.utc)
    for f in pending.glob("*.task.md"):
        fm = read_frontmatter(f)
        if fm.get("status") == "in_progress":
            created = fm.get("created", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if now - created_dt > STALL_THRESHOLD:
                        stalled.append(f.name)
                except ValueError:
                    pass
    return stalled

def patrol():
    """Execute one patrol cycle."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report_lines = [
        f"## Patrol Report — {timestamp}",
        "",
        "| Worker | Pending | Done | Failed | Stalled |",
        "|--------|---------|------|--------|---------|",
    ]

    total_pending = 0
    stall_actions = 0

    for wdir in WORKERS:
        wname = wdir.name
        pending = count_pending(wdir)
        done = count_done(wdir)
        failed = count_failed(wdir)
        stalled = find_stalled_tasks(wdir)
        total_pending += pending
        stall_actions += len(stalled)
        report_lines.append(f"| {wname} | {pending} | {done} | {failed} | {len(stalled)} |")

        if stalled:
            report_lines.append(f"  - **STALLED**: {', '.join(stalled)} — flagging for reassignment")

    report_lines.append("")

    # Load balancing recommendation
    if total_pending > 0:
        counts = [(count_pending(w), w.name) for w in WORKERS]
        counts.sort()
        if counts[0][0] < counts[1][0] - 2:
            report_lines.append(f"**Load Imbalance**: {counts[0][1]} ({counts[0][0]}) vs {counts[1][1]} ({counts[1][1]}). Rebalance recommended.")
        else:
            report_lines.append("**Load**: Balanced across workers.")
    else:
        report_lines.append("**Load**: No pending tasks. Workers idle.")

    report_lines.append("")

    # Append to foreman log
    entry = "\n---\n" + "\n".join(report_lines) + "\n"

    if FOREMAN_LOG.exists():
        existing = FOREMAN_LOG.read_text()
        FOREMAN_LOG.write_text(existing + entry)
    else:
        FOREMAN_LOG.write_text("# GLM-5 Foreman Log\n\n" + entry)

    # Print summary to stdout
    print(f"[FOREMAN] Patrol complete at {timestamp}")
    print(f"  Total pending: {total_pending}")
    print(f"  Stalled tasks: {stall_actions}")
    for line in report_lines:
        if line.startswith("|") or line.startswith("**"):
            print(f"  {line}")

    return {"timestamp": timestamp, "total_pending": total_pending, "stalled": stall_actions}

if __name__ == "__main__":
    result = patrol()
    print(json.dumps(result, indent=2))
