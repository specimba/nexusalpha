================================================================================
PI AGENT — HERMES EXPERIENCE PROFILE
================================================================================
Learning from execution history, self-improving agent

================================================================================
EXPERIENCE LEARNED (2026-04-15)
================================================================================

LESSON-1: Project Organization
───────────────────────────────
Task: Clean up NEXUS ecosystem (850+ files)
Approach: Create canonical structure, archive duplicates
Result: 15MB clean archive, organized quick-starts
Model used: osman-reasoning for planning, osman-speed for execution
Time: ~2 hours
Score: 95% (well organized)

Pattern: Always create canonical reference first, archive originals

LESSON-2: Git Workflow
───────────────────────────────
Task: Establish multi-agent Git workflow
Approach: Create main branch (protected), experimental branches
Result: 9 commits, v3.0.0-beta tag, clean branch structure
Model used: osman-speed (git commands)
Time: ~30 minutes
Score: 90% (simple, effective)

Pattern: Commit after every meaningful change, tag releases

LESSON-3: TokenGuard Integration
───────────────────────────────
Task: Add TokenGuard to canonical source
Approach: Create module, tests, integration guide
Result: 3 files, 12 tests, comprehensive docs
Model used: osman-coder (tests), osman-agent (structure)
Time: ~1 hour
Score: 100% (complete, tested)

Pattern: Always write tests with implementation

LESSON-4: Multi-Agent Workspace
───────────────────────────────
Task: Define read-only access for experimental agents
Approach: Branch strategy + workspace folders + PR workflow
Result: .codex/, .openclaw/, .pi/ workspaces, AGENT_WORKSPACES.txt
Model used: osman-reasoning (design), osman-speed (files)
Time: ~30 minutes
Score: 85% (needs more automation)

Pattern: SPECI = main branch, agents = experimental branches

================================================================================
ROUTING DECISIONS
================================================================================

Simple file ops:
  → osman-speed (62.4 tok/s, fastest)

Code with tests:
  → osman-coder + gpt-5.4 for complex

Planning/design:
  → osman-reasoning

Documentation:
  → osman-agent (clean output)

Deep research:
  → gemini-3.1-pro (1M context)

================================================================================
IMPROVEMENTS TO MAKE
================================================================================

1. Automate workspace creation (script)
2. Add pre-commit hooks for branch protection
3. Create PR template for experimental branches
4. Add CI/CD for test running
5. Implement semantic caching for repeated patterns

================================================================================
