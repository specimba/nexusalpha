"""
engine/forge.py — Qualixar-Style Declarative Team Design (Nexus Forge)

Source: Qualixar OS (arXiv:2604.06392) — Forge component
Priority: Phase 2

Qualixar's "Forge" allows defining agent teams in YAML. Nexus Forge provides
the same capability: declarative team composition with workflow orchestration.

Example team.yaml:
------------------
team: code_review_team
agents:
  - role: reviewer
    model: osman-coder
    traits: [authority, trusted_contributor]
    clearance: maintainer
  - role: verifier
    model: groq/gpt-oss-20b
    traits: [analyst]
    clearance: reader
  - role: judge
    model: osman-reasoning
    traits: [judge, authority]
    clearance: admin
workflow:
  - step: 1
    agent: reviewer
    action: analyze code quality and identify issues
    output_to: next
  - step: 2
    agent: verifier
    action: cross-reference analysis against coding standards
    output_to: next
  - step: 3
    agent: judge
    action: decide final outcome based on reviewer and verifier inputs
    output_to: result

Usage:
------
from nexus_os.engine.forge import ForgeLoader, TeamSpec, WorkflowStep

loader = ForgeLoader()
team = loader.load_file("team.yaml")

for step in team.workflow:
    result = engine.execute(
        agent_id=team.get_agent(step.agent_role).agent_id,
        description=step.action,
        context=step.output_context,
    )
    step.set_result(result)

final_result = team.get_final_result()
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    """Specification for a single agent in a team."""
    role: str                    # e.g., "reviewer", "coder", "judge"
    model: str                   # e.g., "osman-coder", "groq/gpt-oss-20b"
    traits: List[str] = field(default_factory=list)
    clearance: str = "contributor"
    agent_id: Optional[str] = None  # Resolved at runtime


@dataclass
class WorkflowStep:
    """A single step in the team workflow."""
    step_number: int
    agent_role: str              # References an AgentSpec.role
    action: str                  # What this agent should do
    output_to: str = "next"      # "next" (pass to next step) or "result" (final)
    input_from: str = "previous" # "previous" or specific step number
    _result: Optional[Any] = field(default=None, repr=False)
    _context: Dict[str, Any] = field(default_factory=dict, repr=False)

    def set_result(self, result: Any):
        self._result = result

    def get_result(self) -> Optional[Any]:
        return self._result

    def build_context(self, previous_results: Dict[int, Any]) -> Dict[str, Any]:
        """Build execution context from previous step results."""
        if self.input_from == "previous" and self.step_number > 1:
            prev = self.step_number - 1
            if prev in previous_results:
                self._context = {
                    "previous_output": previous_results[prev],
                    "step": self.step_number,
                    "role": self.agent_role,
                }
        return self._context


@dataclass
class TeamSpec:
    """Complete team specification parsed from YAML."""
    team_name: str
    agents: List[AgentSpec]
    workflow: List[WorkflowStep]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_agent(self, role: str) -> Optional[AgentSpec]:
        """Look up an agent spec by role name."""
        for agent in self.agents:
            if agent.role == role:
                return agent
        return None

    def get_step(self, step_number: int) -> Optional[WorkflowStep]:
        """Look up a workflow step by number."""
        for step in self.workflow:
            if step.step_number == step_number:
                return step
        return None

    def validate(self) -> List[str]:
        """Validate the team spec. Returns list of error messages (empty = valid)."""
        errors = []
        roles = {a.role for a in self.agents}

        # Check all workflow steps reference valid roles
        for step in self.workflow:
            if step.agent_role not in roles:
                errors.append(f"Step {step.step_number}: unknown role '{step.agent_role}'")

        # Check step numbering is sequential
        step_nums = [s.step_number for s in self.workflow]
        if step_nums != list(range(1, len(step_nums) + 1)):
            errors.append(f"Workflow steps are not sequential: {step_nums}")

        # Check at least one agent exists
        if not self.agents:
            errors.append("Team has no agents")

        # Check at least one workflow step exists
        if not self.workflow:
            errors.append("Team has no workflow steps")

        return errors

    def get_final_result(self) -> Optional[Any]:
        """Get the result of the last workflow step."""
        if self.workflow:
            last_step = self.workflow[-1]
            return last_step.get_result()
        return None


class ForgeLoader:
    """
    Loads and parses Nexus Forge team specifications from YAML files.
    """

    def load_file(self, path: str) -> TeamSpec:
        """Load a team spec from a YAML file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Forge spec not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return self._parse(data)

    def load_string(self, yaml_content: str) -> TeamSpec:
        """Load a team spec from a YAML string."""
        data = yaml.safe_load(yaml_content)
        return self._parse(data)

    def _parse(self, data: Dict[str, Any]) -> TeamSpec:
        """Parse raw YAML dict into TeamSpec."""
        team_name = data.get("team", "unnamed_team")

        agents = []
        for agent_data in data.get("agents", []):
            agents.append(AgentSpec(
                role=agent_data["role"],
                model=agent_data.get("model", "default"),
                traits=agent_data.get("traits", []),
                clearance=agent_data.get("clearance", "contributor"),
            ))

        workflow = []
        for step_data in data.get("workflow", []):
            workflow.append(WorkflowStep(
                step_number=step_data.get("step", len(workflow) + 1),
                agent_role=step_data["agent"],
                action=step_data["action"],
                output_to=step_data.get("output_to", "next"),
                input_from=step_data.get("input_from", "previous"),
            ))

        metadata = {
            k: v for k, v in data.items()
            if k not in ("team", "agents", "workflow")
        }

        team = TeamSpec(
            team_name=team_name,
            agents=agents,
            workflow=workflow,
            metadata=metadata,
        )

        errors = team.validate()
        if errors:
            error_str = "; ".join(errors)
            logger.warning("Forge spec validation warnings: %s", error_str)

        return team
