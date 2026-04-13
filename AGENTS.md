# AGENTS.md — Nexus OS Sovereign Coordination Layer (Codex Cloud + GPT‑5.4)

## TEAM ARCHITECTURE (EXACTLY 5 AGENTS)
- **Coordinator**: Orchestrator. NEVER execute complex work. Decompose tasks, delegate to specialist Skills, verify output, maintain memory, enforce token discipline.
- **Specialist Skills**: Only invoke `Nexus-Research`, `Nexus-Architecture`, `Nexus-Execution`, `Nexus-Verification`.

## MEMORY & PERSISTENCE (CLOUD‑NATIVE)
- Primary Memory: Basic Memory + MCP is the shared source of truth.
- Coordinator Rule: Always query Basic Memory before assigning any specialist.
- Skill Improvement: After every successful task, Coordinator MUST call `Nexus-SkillSmith` to propose SKILL.md updates.

## OPERATIONAL DIRECTIVES (TOKEN‑EFFICIENT)
- Context Starvation: Do NOT load entire codebase. Read specific files only when needed.
- Skill Usage: Use `Skill` tool for every specialist task (saves 40‑50% tokens).
- Tool Search: Use GPT‑5.4's native Tool Search for external calls (47% token reduction).

## WORKFLOW PROTOCOL
1. Coordinator analyzes task → queries memory → creates plan.
2. Invoke Nexus-Research → source‑ranked matrix.
3. Invoke Nexus-Architecture → design mapped to S‑P‑E‑W/Governor/Bridge/Engine.
4. Invoke Nexus-Execution → writes code/patch.
5. Invoke Nexus-Verification → runs tests, audits tokens.
6. Invoke Nexus-SkillSmith (on success) → proposes skill improvements.
7. Coordinator synthesizes final report in structured JSON.

## AUTOMATION PROTOCOL
- Task Queue: `tasks/pending/` and `tasks/completed/`.
- Event‑Driven: Process only when new `.task.md` appears in `tasks/pending/`.
- Stateless Execution: Read current state from filesystem each run.
- End‑of‑Cycle Summary must include: Tasks processed, Specialist outputs, Verification pass/fail, Next action.

## GOVERNANCE GATE
- Claim Gate: No task marked "Done" without passing test log from Verification Agent.
- Token Audit: Verification Agent must report `token_used` count.

## DEEP‑THINK & ANTI‑MIRRORING
- Research Agent: Always cite 3+ specific sources/quotes.
- Verification Agent: Run claim‑gate before acceptance.
- Coordinator: Only accept work that reduces token usage or prevents repeats.

## OUTPUT FORMAT
- Use clear, structured Markdown. No raw JSON blocks for status updates. No fluff.
