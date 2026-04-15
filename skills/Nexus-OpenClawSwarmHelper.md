# Nexus-OpenClawSwarmHelper – OpenClaw Foreman + Worker Helpers

Role: Spawn and coordinate OpenClaw swarm sub-agents (glm5-foreman, glm5-worker-1/2, glm5-hermes) when task volume or complexity requires parallelization.

Trigger (called by Coordinator only):
- Task volume > 3 pending
- Heartbeat every 15 min (Codex Automation)
- Complex task flagged by Research/Architecture

Steps:
1. Check tasks/pending/ count.
2. If needed, spawn Foreman via file watcher or direct CLI call.
3. Write task files to worker pending queues.
4. Monitor done/failed queues.
5. Return swarm status summary to Coordinator.

Output Format:
**Swarm Status:** active / idle
**Workers Spawned:** glm5-foreman, glm5-worker-1, glm5-worker-2
**Tasks Delegated:** X
**Next Action:** ...
