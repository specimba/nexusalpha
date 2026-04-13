"""
team/ — Agentic Team Coordinator

Central nervous system that wires together:
  - Hermes experience-based routing (who handles this task?)
  - mem0 persistent memory (what do we know about similar tasks?)
  - Skill registry (which platform skill can help?)
  - OpenClaw file-driven task dispatch (how do we assign work?)
  - Outcome recording (what did we learn?)
"""

from nexus_os.team.coordinator import (
    TeamCoordinator,
    WorkerProfile,
)

__all__ = [
    "TeamCoordinator",
    "WorkerProfile",
]
