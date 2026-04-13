#!/usr/bin/env python3
"""
GLM-5 Autonomous Background Worker v2
Dual-format: supports both .task.json (legacy Nexus OS) and .task.md (Markdown + YAML frontmatter, OpenClaw standard).
Polls OpenClaw worker directories OR Nexus OS project directories for pending tasks.
"""

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional


PROJECT_ROOT = Path(__file__).parent.parent
OPENCLAW_WORKERS = [
    Path.home() / '.openclaw' / 'agents' / 'glm5-worker-1',
    Path.home() / '.openclaw' / 'agents' / 'glm5-worker-2',
]

FRONTMATTER_RE = re.compile(r'^---[\s\S]*?\n---')


class GLM5Worker:
    """Polls a worker directory for .task.md / .task.json files and executes them."""

    def __init__(self, worker_dir=None):
        self.worker_id: str = f'glm5-{uuid.uuid4().hex[:6]}'
        self.worker_dir: Path = Path(worker_dir) if worker_dir else PROJECT_ROOT
        self.pending_dir: Path = self.worker_dir / 'tasks' / 'pending'
        self.done_dir: Path = self.worker_dir / 'tasks' / 'done'
        self.completed_dir: Path = self.worker_dir / 'tasks' / 'completed'
        self.failed_dir: Path = self.worker_dir / 'tasks' / 'failed'
        self.workspace_root: Path = self.worker_dir / 'workspaces'
        self._ensure_dirs()
        self._stats: Dict[str, int] = {'processed': 0, 'failed': 0, 'heartbeat_ok': 0}

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        for d in (self.pending_dir, self.done_dir, self.completed_dir,
                  self.failed_dir, self.workspace_root):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def output_dir(self) -> Path:
        """Return the appropriate success output directory for the current worker."""
        return self.done_dir if self.worker_dir != PROJECT_ROOT else self.completed_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_and_execute(self) -> bool:
        """Check for pending tasks.  Processes .task.md first, then .task.json."""
        # Priority 1: Markdown tasks (OpenClaw standard)
        md_tasks = sorted(self.pending_dir.glob('*.task.md'))
        if md_tasks:
            task_file = md_tasks[0]
            task = self._parse_markdown_task(task_file)
            title = task.get('title', task_file.stem)
            print(f'[{self.worker_id}] Processing (MD): {title}')
            self._execute_md_task(task, task_file)
            return True

        # Priority 2: JSON tasks (legacy Nexus OS format)
        json_tasks = sorted(self.pending_dir.glob('*.task.json'))
        for task_file in json_tasks:
            task = json.loads(task_file.read_text())
            owner = task.get('owner')
            if owner not in ('glm5', None, ''):
                continue
            print(f'[{self.worker_id}] Processing (JSON): {task.get("title", task_file.stem)}')
            self._execute_json_task(task, task_file)
            return True

        # Nothing to do
        self._stats['heartbeat_ok'] += 1
        print(f'[{self.worker_id}] HEARTBEAT_OK (polls: {self._stats["heartbeat_ok"]})')
        return False

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Markdown task parsing / execution
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_markdown_task(filepath: Path) -> Dict[str, Any]:
        """Parse YAML frontmatter and body from a .task.md file.

        Uses regex r'^---[\\s\\S]*?\\n---' to match the frontmatter block,
        then parses simple ``key: value`` YAML lines (no full YAML parser
        required).
        """
        text = filepath.read_text()
        frontmatter: Dict[str, str] = {}

        match = re.match(r'^---[\s\S]*?\n---', text)
        if match:
            raw_fm = match.group(0)
            # Strip the leading/trailing '---' delimiters
            inner = raw_fm[3:].rsplit('---', 1)[0].strip()
            for line in inner.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, val = line.split(':', 1)
                    frontmatter[key.strip()] = val.strip()
            # Body is everything after the closing '---'
            body = text[match.end():].strip()
        else:
            body = text

        # Derive title from the first H1 heading if present
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else frontmatter.get('id', filepath.stem)

        return {
            'id': frontmatter.get('id', filepath.stem),
            'title': title,
            'type': frontmatter.get('type', 'code-implementation'),
            'priority': frontmatter.get('priority', 'medium'),
            'assigned_to': frontmatter.get('assigned_to', 'glm5'),
            'created': frontmatter.get('created', ''),
            'status': frontmatter.get('status', 'pending'),
            'dependencies': frontmatter.get('dependencies', ''),
            'description': body,
            '_raw_text': text,
            '_frontmatter': frontmatter,
        }

    def _update_md_status(self, task_file: Path, status: str) -> None:
        """Rewrite the status field inside the YAML frontmatter.

        Strategy:
        1. Split text by ``'---'``.
        2. Replace (or insert) the ``status:`` line in the frontmatter section.
        3. Reassemble and write back.
        """
        text = task_file.read_text()
        parts = text.split('---')
        if len(parts) >= 3:
            # parts[0] is empty/before first ---
            # parts[1] is frontmatter content
            # parts[2:] is body (joined back with '---')
            fm = parts[1]
            if 'status:' in fm:
                fm = re.sub(
                    r'^(status:\s*)\S+',
                    rf'\g<1>{status}',
                    fm,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                fm = f'\nstatus: {status}' + fm
            text = '---' + fm + '---' + '---'.join(parts[2:])
        elif len(parts) == 2:
            # Only one '---' found – prepend frontmatter
            text = f'---\nstatus: {status}\n---\n' + text
        task_file.write_text(text)

    def _append_result_to_md(
        self,
        task_file: Path,
        task: Dict[str, Any],
        result: Dict[str, Any],
        status: str,
    ) -> None:
        """Append an execution-result section after the task body."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self._update_md_status(task_file, status)

        lines = [
            '',
            '---',
            '',
            '## Execution Result',
            '',
            f'- **Status**: {status}',
            f'- **Completion Time**: {timestamp}',
            f'- **Worker ID**: {self.worker_id}',
        ]

        if 'error' in result:
            lines.append(f'- **Error**: `{result["error"]}`')
        else:
            lines.append(f'- **Return Code**: {result.get("returncode", "N/A")}')
            lines.append('')
            lines.append('### stdout')
            lines.append('```')
            lines.append(result.get('stdout', '')[-2000:])
            lines.append('```')
            if result.get('stderr'):
                lines.append('')
                lines.append('### stderr')
                lines.append('```')
                lines.append(result['stderr'][-1000:])
                lines.append('```')

        section = '\n'.join(lines) + '\n'
        with open(task_file, 'a') as f:
            f.write(section)

    def _execute_md_task(self, task: Dict[str, Any], task_file: Path) -> None:
        """Execute a markdown task: set in_progress, sandbox-run, append result, move to done/."""
        self._update_md_status(task_file, 'in_progress')
        workspace = self.workspace_root / task['id']
        workspace.mkdir(exist_ok=True)
        try:
            result = self._run_in_sandbox(task, workspace)
            self._append_result_to_md(task_file, task, result, 'completed')
            dest = self.output_dir / task_file.name
            shutil.move(str(task_file), str(dest))
            self._git_backup(task)
            self._stats['processed'] += 1
        except Exception as e:
            self._append_result_to_md(task_file, task, {'error': str(e)}, 'failed')
            shutil.move(str(task_file), str(self.failed_dir / task_file.name))
            self._stats['failed'] += 1
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    # ------------------------------------------------------------------
    # JSON task execution
    # ------------------------------------------------------------------

    def _execute_json_task(self, task: Dict[str, Any], task_file: Path) -> None:
        """Execute a JSON task: update status, sandbox-run, write result.json, move to completed/."""
        task['status'] = 'in_progress'
        task['started_at'] = datetime.now(timezone.utc).isoformat()
        task_file.write_text(json.dumps(task, indent=2))

        workspace = self.workspace_root / task['id']
        workspace.mkdir(exist_ok=True)
        try:
            result = self._run_in_sandbox(task, workspace)
            task['status'] = 'completed'
            task['completed_at'] = datetime.now(timezone.utc).isoformat()
            task['result'] = result
            result_path = self.output_dir / f'{task["id"]}.result.json'
            result_path.write_text(json.dumps(task, indent=2))
            task_file.unlink()
            self._git_backup(task)
            self._stats['processed'] += 1
        except Exception as e:
            task['status'] = 'failed'
            task['error'] = str(e)
            task['failed_at'] = datetime.now(timezone.utc).isoformat()
            failed_path = self.failed_dir / f'{task["id"]}.failed.json'
            failed_path.write_text(json.dumps(task, indent=2))
            task_file.unlink()
            self._stats['failed'] += 1
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    # ------------------------------------------------------------------
    # Sandbox execution
    # ------------------------------------------------------------------

    def _run_in_sandbox(
        self,
        task: Dict[str, Any],
        workspace: Path,
    ) -> Dict[str, Any]:
        """Copy PROJECT_ROOT into *workspace/nexus-os* and run the appropriate command.

        Excludes: ``__pycache__``, ``.git``, ``tasks``, ``workspaces``, ``*.db``.
        Sets ``PYTHONPATH`` to ``sandbox/src``.
        """
        sandbox_dir = workspace / 'nexus-os'

        if PROJECT_ROOT.exists():
            shutil.copytree(
                PROJECT_ROOT,
                sandbox_dir,
                ignore=shutil.ignore_patterns(
                    '__pycache__',
                    '*.pyc',
                    '.git',
                    'tasks',
                    'workspaces',
                    '*.db',
                    '*.db-shm',
                    '*.db-wal',
                ),
            )

        # Determine the command based on the task description
        desc = str(task.get('description', '')).lower()
        if 'pytest' in desc or 'test' in desc:
            cmd = ['python3', '-m', 'pytest', 'tests/', '-v', '--tb=short']
        elif 'lint' in desc or 'flake8' in desc:
            cmd = ['python3', '-m', 'flake8', 'src/nexus_os/']
        else:
            cmd = ['echo', 'No specific command; task marked complete.']

        # Build environment with PYTHONPATH pointing at sandbox/src
        env = os.environ.copy()
        env['PYTHONPATH'] = str(sandbox_dir / 'src') + ':' + env.get('PYTHONPATH', '')

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(sandbox_dir),
            env=env,
        )
        return {
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'returncode': proc.returncode,
        }

    # ------------------------------------------------------------------
    # Git backup
    # ------------------------------------------------------------------

    def _git_backup(self, task: Dict[str, Any]) -> None:
        """Stage all changes and commit with a descriptive message."""
        try:
            subprocess.run(['git', 'add', '-A'], cwd=str(PROJECT_ROOT), check=True)
            title = task.get('title', task.get('id', 'unknown'))
            task_id = str(task.get('id', 'unknown'))[:8]
            message = f'auto(glm5): {title} (Task {task_id})'
            subprocess.run(['git', 'commit', '-m', message], cwd=str(PROJECT_ROOT), check=True)
        except subprocess.CalledProcessError:
            pass


# ----------------------------------------------------------------------
# Multi-worker orchestration
# ----------------------------------------------------------------------

def run_all_workers() -> bool:
    """Check OPENCLAW_WORKERS directories + PROJECT_ROOT for pending tasks.

    Returns True if at least one task was processed.
    """
    all_dirs = list(OPENCLAW_WORKERS) + [PROJECT_ROOT]
    any_processed = False
    for wdir in all_dirs:
        if not wdir.exists():
            continue
        pending = wdir / 'tasks' / 'pending'
        if not pending.exists() or not any(pending.iterdir()):
            continue
        worker = GLM5Worker(worker_dir=wdir)
        if worker.poll_and_execute():
            any_processed = True
    return any_processed


if __name__ == '__main__':
    if not run_all_workers():
        print('HEARTBEAT_OK')
