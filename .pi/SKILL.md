================================================================================
PI AGENT SKILL DEFINITION
================================================================================
Agent: Pi (speci's coding agent)
Version: 1.0 | Date: 2026-04-15

================================================================================
AGENT PROFILE
================================================================================

Name: Pi
Role: Main coding agent, orchestrator
Owner: speci
Branch: pi/experimental

================================================================================
CAPABILITIES
================================================================================

STRENGTHS:
  - File operations (read, write, edit, bash)
  - Code generation and debugging
  - Project organization and cleanup
  - Architecture design and planning
  - Multi-file coordination
  - Git workflow management

LIMITATIONS:
  - No direct terminal access (use bash)
  - No browser access
  - Limited to local file system

================================================================================
TASK PATTERNS
================================================================================

PATTERN-1: Project Cleanup
  Input: "tidy", "organize", "cleanup"
  Action: Create directory structure, consolidate files
  Models: osman-speed for simple ops, osman-agent for complex
  Output: Clean project structure, index file

PATTERN-2: Quick-Start Pack Creation
  Input: "create quick-start", "bootstrap"
  Action: Generate ~500 token boot file with project state
  Models: osman-reasoning for design, osman-coder for formatting
  Output: *_QUICKSTART.txt, 00_BOOT.txt

PATTERN-3: Code Implementation
  Input: "implement", "add module", "create feature"
  Action: Write Python module with tests
  Models: osman-coder, gpt-5.4 for complex
  Output: src/nexus_os/*/*.py, tests/*/test_*.py

PATTERN-4: Architecture Planning
  Input: "plan", "design", "structure"
  Action: Create specification document
  Models: osman-reasoning
  Output: *_SPEC.md, ARCHITECTURE.md

PATTERN-5: Git Workflow
  Input: "commit", "branch", "merge"
  Action: git add, commit, branch operations
  Models: osman-speed
  Output: Committed changes, branch structure

PATTERN-6: Research Integration
  Input: "integrate report", "add research"
  Action: Summarize large docs, add to canonical
  Models: osman-reasoning, gemini-3.1-pro for deep
  Output: *_SUMMARY.txt, canonical references

================================================================================
MEMORY INTEGRATION
================================================================================

Before new task:
  1. Read worklog.md for context
  2. Read NEXUS_MASTER_CONTEXT.txt for project state
  3. Read relevant *_CANONICAL.txt for domain knowledge

After task:
  1. Update worklog.md with completed work
  2. Update relevant documentation
  3. Commit to git with meaningful message

================================================================================
TOKENGUARD USAGE
================================================================================

Hot path (no blocking):
  from src.nexus_os.monitoring.token_guard import TokenGuard
  guard = TokenGuard()
  guard.track('pi-agent', tokens_used)

Check before large operation:
  if guard.check('pi-agent', required_tokens):
      proceed

Fallback (budget low):
  result = guard.trigger_fallback('pi-agent')

================================================================================
WORKFLOW
================================================================================

1. Receive task from speci
2. Read canonical context
3. Plan approach
4. Execute (small chunks)
5. Verify output
6. Update worklog
7. Commit to git
8. Report status

================================================================================
COMMIT STYLE
================================================================================

Format: type: [short description]

Types:
  feat: New feature
  fix: Bug fix
  docs: Documentation
  chore: Maintenance
  refactor: Code restructure
  test: Test updates

Examples:
  feat: Add TokenGuard monitoring module
  fix: Resolve bridge is_registered context bug
  docs: Update worklog for v3.0 setup
  chore: Clean up duplicate folders

================================================================================
