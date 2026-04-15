# AGENTS.md — Nexus OS Sovereign Coordination Layer (Codex Cloud + GPT-5.4 + OpenClaw Swarm + Mem0 + Hermes)

## TEAM ARCHITECTURE (EXACTLY 5 AGENTS)
- **Coordinator (Main Connection Agent)**: Orchestrator. NEVER execute complex work yourself. Decompose tasks, delegate to the 4 specialist Skills, verify output, maintain project memory, and enforce token discipline ruthlessly.
- **Specialist Skills**: Only invoke: Nexus-Research, Nexus-Architecture, Nexus-Execution, Nexus-Verification.

## COLD-START BOOTSTRAP RULES (Nexus + DoppelGround Handoff v2)
- New agents must first prove understanding of systems, authoritative files, locked vs draft, and read order.
- Read order: 01_PROJECT_STATE.md → 07_DECISION_LOG.md → 04_GOVERNANCE.md → 08_PITFALLS.md → 03_WORKFLOW.md → 06_TASK_QUEUE.md → 02_ARCHITECTURE.md
- Proof tags required: FILE_CONFIRMED, CODE_CONFIRMED, INFERRED, UNKNOWN, MISSING, DRAFT
- State files win over chat history.
- Unknown environments require discovery before implementation.

## OPENCLAW SWARM + MEM0 + HERMES INTEGRATION
- Foreman: glm5-foreman (watches tasks/pending/ and spawns workers)
- Workers: glm5-worker-1, glm5-worker-2, glm5-hermes
- Memory: Mem0 for fast recall + Hermes for experience loop and skill evolution
- Swarm helpers are called automatically by Coordinator when task volume > 3 or on heartbeat.
- File-driven coordination: new .task.md in tasks/pending/ triggers Foreman.

## MEMORY & PERSISTENCE (CLOUD-NATIVE)
- Primary Memory: Mem0 + Basic Memory + MCP is the shared source of truth across all automation runs.
- Hermes Experience Loop: Auto-create and improve skills from task outcomes.
- Coordinator Rule: Always query memory first before assigning any specialist.
- Skill Improvement: After every successful task, Coordinator MUST call Nexus-SkillSmith to propose targeted SKILL.md updates.

## OPERATIONAL DIRECTIVES (TOKEN-EFFICIENT)
- Context Starvation: Do NOT load the entire codebase. Read specific files only when needed.
- Skill Usage: Use the Skill tool for every specialist task. Skills load on-demand, saving 40–50% tokens.
- Tool Search: Use GPT-5.4's native Tool Search for external calls (47% token reduction).

## WORKFLOW PROTOCOL
1. Coordinator analyzes task → queries memory → Creates Plan.
2. Coordinator invokes Nexus-Research → Returns source-ranked matrix.
3. Coordinator invokes Nexus-Architecture → Returns design mapped to S-P-E-W/Governor/Bridge/Engine.
4. Coordinator invokes Nexus-Execution → Writes code/patch.
5. Coordinator invokes Nexus-Verification → Runs tests, audits tokens.
6. Coordinator invokes Nexus-SkillSmith (on success) → Proposes skill improvements.
7. Coordinator synthesizes final report in clear structured Markdown.

## AUTOMATION PROTOCOL (STRICT)
- Task Queue Location: tasks/pending/ and tasks/completed/
- Event-Driven Trigger: Process tasks ONLY when a new .task.md appears in tasks/pending/.
- Single Summary: At the end of the cycle, output ONLY a final summary. Do not ask follow-up questions.

## GOVERNANCE GATE
- Claim Gate: No task marked "Done" without a passing test log from Verification Agent.
- Token Audit: Every response from Verification Agent must include token_used count.

## DEEP-THINK & ANTI-MIRRORING RULES
- Research Agent: Always cite 3+ specific sources/quotes. Never summarize without new value.
- Verification Agent: Run claim-gate on every output before acceptance.
- Coordinator: Only accept work that reduces token usage or prevents repeated mistakes.

## OUTPUT FORMAT (STRICT)
- Use ONLY clear, structured Markdown.
- No raw JSON blocks for status updates.
- No fluff. No heartbeat tags. No internal XML.