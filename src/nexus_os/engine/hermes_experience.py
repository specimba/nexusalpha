"""
Hermes Experience Router - Intelligent Task Routing with mem0 Memory
Router that queries mem0 before making routing decisions
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import hashlib
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from nexus_os.vault.mem0_adapter import Mem0Adapter, get_adapter


class Domain(Enum):
    """Task domains for classification"""
    CODE = "code"
    OPS = "ops"
    RESEARCH = "research"
    SECURITY = "security"
    UNKNOWN = "unknown"


class Skill(Enum):
    """29 registered skills for matching"""
    # Code skills
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    GO = "go"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    TESTING = "testing"
    
    # Ops skills
    DEPLOYMENT = "deployment"
    MONITORING = "monitoring"
    LOGGING = "logging"
    CI_CD = "ci_cd"
    INFRASTRUCTURE = "infrastructure"
    
    # Research skills
    ANALYSIS = "analysis"
    SUMMARIZATION = "summarization"
    EVIDENCE_RANKING = "evidence_ranking"
    DOSSIER_CREATION = "dossier_creation"
    
    # Security skills
    AUDIT = "audit"
    VULNERABILITY_SCAN = "vulnerability_scan"
    THREAT_MODELING = "threat_modeling"
    COMPLIANCE_CHECK = "compliance_check"
    
    # General skills
    DOCUMENTATION = "documentation"
    REVIEW = "review"
    PLANNING = "planning"
    COORDINATION = "coordination"
    VERIFICATION = "verification"
    ARCHITECTURE = "architecture"
    INTEGRATION = "integration"
    OPTIMIZATION = "optimization"


@dataclass
class Task:
    """Task envelope for routing"""
    task_id: str
    project_id: str
    description: str
    lane: str
    trust_min: float = 0.5
    timeout: int = 300
    checkpoint: bool = True
    evidence_required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def domain(self) -> str:
        """Infer domain from lane"""
        domain_map = {
            "code": Domain.CODE.value,
            "ops": Domain.OPS.value,
            "research": Domain.RESEARCH.value,
            "security": Domain.SECURITY.value
        }
        return domain_map.get(self.lane, Domain.UNKNOWN.value)
    
    @property
    def signature(self) -> str:
        """Generate task signature for pattern matching"""
        content = f"{self.lane}:{self.description[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]


@dataclass
class RouteDecision:
    """Routing decision with confidence and evidence"""
    agent_id: str
    agent_type: str
    confidence: float
    evidence_refs: List[str]
    reasoning: str
    estimated_time: int
    risk_level: str
    skills_matched: List[str]


@dataclass
class AgentCard:
    """A2A Agent Card format"""
    agent_id: str
    lane: str
    trust_band: str
    availability: str
    hold_state: Optional[str]
    capabilities: List[str]
    failure_patterns: List[str]
    last_verified_event: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "lane": self.lane,
            "trust_band": self.trust_band,
            "availability": self.availability,
            "hold_state": self.hold_state,
            "capabilities": self.capabilities,
            "failure_patterns": self.failure_patterns,
            "last_verified_event": self.last_verified_event
        }


class HermesExperienceRouter:
    """
    Router that queries mem0 before making routing decisions
    - Domain classification (code/ops/research/security)
    - Skill matching for 29 registered skills
    - Route decision with confidence score using experience-informed confidence
    """
    
    # Domain keywords for classification
    DOMAIN_KEYWORDS = {
        Domain.CODE: ["python", "javascript", "code", "function", "class", "bug", "debug", "refactor", "test", "import", "module"],
        Domain.OPS: ["deploy", "server", "docker", "kubernetes", "monitor", "log", "pipeline", "infra", "scale"],
        Domain.RESEARCH: ["analyze", "research", "study", "paper", "evidence", "source", "summarize", "investigate"],
        Domain.SECURITY: ["security", "vulnerability", "threat", "audit", "compliance", "risk", "attack", "protect"]
    }
    
    # Skill patterns for matching
    SKILL_PATTERNS = {
        Skill.PYTHON: ["python", "py", "pip", "django", "flask", "pandas"],
        Skill.JAVASCRIPT: ["javascript", "js", "node", "react", "vue", "angular"],
        Skill.TYPESCRIPT: ["typescript", "ts", "type"],
        Skill.RUST: ["rust", "cargo", "rs"],
        Skill.GO: ["go", "golang"],
        Skill.DEBUGGING: ["debug", "bug", "error", "trace", "breakpoint"],
        Skill.REFACTORING: ["refactor", "clean", "restructure", "improve"],
        Skill.TESTING: ["test", "pytest", "unittest", "coverage"],
        Skill.DEPLOYMENT: ["deploy", "release", "ship", "publish"],
        Skill.MONITORING: ["monitor", "metric", "alert", "observe"],
        Skill.LOGGING: ["log", "trace", "audit trail"],
        Skill.CI_CD: ["ci", "cd", "pipeline", "github actions", "jenkins"],
        Skill.INFRASTRUCTURE: ["infra", "infrastructure", "terraform", "ansible"],
        Skill.ANALYSIS: ["analyze", "analysis", "examine", "evaluate"],
        Skill.SUMMARIZATION: ["summarize", "summary", "digest", "overview"],
        Skill.EVIDENCE_RANKING: ["evidence", "rank", "source", "cite"],
        Skill.DOSSIER_CREATION: ["dossier", "report", "document"],
        Skill.AUDIT: ["audit", "review", "inspect"],
        Skill.VULNERABILITY_SCAN: ["vulnerability", "scan", "cve", "exploit"],
        Skill.THREAT_MODELING: ["threat", "model", "attack vector"],
        Skill.COMPLIANCE_CHECK: ["compliance", "regulation", "gdpr", "hipaa"],
        Skill.DOCUMENTATION: ["doc", "document", "readme", "wiki"],
        Skill.REVIEW: ["review", "check", "validate"],
        Skill.PLANNING: ["plan", "roadmap", "milestone", "sprint"],
        Skill.COORDINATION: ["coordinate", "sync", "align", "schedule"],
        Skill.VERIFICATION: ["verify", "confirm", "prove", "test"],
        Skill.ARCHITECTURE: ["architecture", "design", "pattern", "structure"],
        Skill.INTEGRATION: ["integrate", "connect", "bridge", "api"],
        Skill.OPTIMIZATION: ["optimize", "performance", "speed", "efficiency"]
    }
    
    def __init__(self, mem0_adapter: Optional[Mem0Adapter] = None):
        self.mem0 = mem0_adapter or get_adapter()
        self._agents: Dict[str, AgentCard] = {}
        self._register_default_agents()
    
    def _register_default_agents(self):
        """Register default agent pool"""
        default_agents = [
            AgentCard("glm5-executor", "code", "COMMUNITY_VERIFIED", "ready", None, 
                     ["python", "debugging", "refactoring", "testing"], [], "init"),
            AgentCard("glm5-ops", "ops", "COMMUNITY_VERIFIED", "ready", None,
                     ["deployment", "monitoring", "ci_cd"], [], "init"),
            AgentCard("glm5-research", "research", "COMMUNITY_VERIFIED", "ready", None,
                     ["analysis", "summarization", "evidence_ranking"], [], "init"),
            AgentCard("glm5-security", "security", "COMMUNITY_VERIFIED", "ready", None,
                     ["audit", "vulnerability_scan", "compliance_check"], [], "init"),
            AgentCard("glm5-coordinator", "coordination", "COMMUNITY_VERIFIED", "ready", None,
                     ["coordination", "planning", "review"], [], "init")
        ]
        for agent in default_agents:
            self._agents[agent.agent_id] = agent
    
    def classify_domain(self, task: Task) -> Domain:
        """Classify task domain based on description and lane"""
        text = f"{task.description} {task.lane}".lower()
        
        scores = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            scores[domain] = score
        
        # Return domain with highest score, default to lane mapping
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        
        # Fallback to lane-based classification
        domain_map = {
            "code": Domain.CODE,
            "ops": Domain.OPS,
            "research": Domain.RESEARCH,
            "security": Domain.SECURITY
        }
        return domain_map.get(task.lane, Domain.UNKNOWN)
    
    def match_skills(self, task: Task) -> List[Skill]:
        """Match task to skills from 29 registered skills"""
        text = task.description.lower()
        matched = []
        
        for skill, patterns in self.SKILL_PATTERNS.items():
            if any(pattern in text for pattern in patterns):
                matched.append(skill)
        
        # Always return at least one skill
        if not matched:
            matched = [Skill.ANALYSIS]
        
        return matched
    
    def route(self, task: Task) -> RouteDecision:
        """
        Main routing method with mem0 experience query
        1. Query mem0 for similar past tasks
        2. Check if pattern exists in Wisdom layer
        3. Route with experience-informed confidence
        """
        # Step 1: Classify domain
        domain = self.classify_domain(task)
        
        # Step 2: Match skills
        skills = self.match_skills(task)
        skill_names = [s.value for s in skills]
        
        # Step 3: Query mem0 for similar past tasks
        similar_tasks = []
        try:
            similar_tasks = self.mem0.search_experience(
                query=task.description,
                domain=domain.value,
                outcome="success",
                limit=5
            )
        except Exception as e:
            # mem0 query failed, continue with rule-based routing
            pass
        
        # Step 4: Check Wisdom layer for patterns
        pattern = None
        try:
            pattern = self.mem0.get_wisdom_pattern(task.signature)
        except Exception:
            pass
        
        # Step 5: Select best agent based on skills and availability
        agent_id, agent_type = self._select_agent(task.lane, skill_names)
        
        # Step 6: Calculate confidence using experience
        confidence = self._calc_confidence(similar_tasks, pattern, skills)
        
        # Step 7: Determine risk level
        risk_level = self._assess_risk(task, similar_tasks)
        
        # Step 8: Estimate time based on similar tasks
        estimated_time = self._estimate_time(similar_tasks, pattern)
        
        # Build evidence references
        evidence_refs = [r.id for r in similar_tasks]
        if pattern:
            evidence_refs.append(f"pattern:{task.signature}")
        
        # Build reasoning
        reasoning = self._build_reasoning(domain, skills, similar_tasks, pattern, agent_id)
        
        return RouteDecision(
            agent_id=agent_id,
            agent_type=agent_type,
            confidence=confidence,
            evidence_refs=evidence_refs,
            reasoning=reasoning,
            estimated_time=estimated_time,
            risk_level=risk_level,
            skills_matched=skill_names
        )
    
    def _select_agent(self, lane: str, required_skills: List[str]) -> tuple:
        """Select best agent for lane and skills"""
        # Filter agents by lane compatibility
        lane_agents = [
            agent for agent in self._agents.values()
            if agent.lane == lane or lane in agent.capabilities
        ]
        
        if not lane_agents:
            # Fallback to coordinator
            return "glm5-coordinator", "coordination"
        
        # Score agents by skill match
        best_agent = None
        best_score = -1
        
        for agent in lane_agents:
            score = sum(1 for skill in required_skills if skill in agent.capabilities)
            if agent.availability == "ready":
                score += 10  # Boost available agents
            if score > best_score:
                best_score = score
                best_agent = agent
        
        return best_agent.agent_id, best_agent.lane
    
    def _calc_confidence(self, similar_tasks: List[Any], pattern: Optional[Dict], skills: List[Skill]) -> float:
        """Calculate confidence score using experience-informed method"""
        base_confidence = 0.5
        
        # Boost from similar successful tasks
        if similar_tasks:
            avg_trust = sum(r.trust_score for r in similar_tasks) / len(similar_tasks)
            base_confidence += avg_trust * 0.3
        
        # Boost from wisdom pattern
        if pattern:
            base_confidence += pattern.get("success_rate", 0) * 0.2
        
        # Skill diversity bonus
        if len(skills) > 2:
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)
    
    def _assess_risk(self, task: Task, similar_tasks: List[Any]) -> str:
        """Assess risk level based on task and history"""
        # Check for high-risk keywords
        high_risk_keywords = ["delete", "remove", "production", "deploy", "secret", "credential"]
        text = task.description.lower()
        
        if any(kw in text for kw in high_risk_keywords):
            return "HIGH"
        
        # Check similar task failure rate
        if similar_tasks:
            failures = sum(1 for r in similar_tasks if r.outcome == "failure")
            failure_rate = failures / len(similar_tasks)
            if failure_rate > 0.5:
                return "HIGH"
            elif failure_rate > 0.2:
                return "MEDIUM"
        
        return "LOW"
    
    def _estimate_time(self, similar_tasks: List[Any], pattern: Optional[Dict]) -> int:
        """Estimate task completion time based on experience"""
        if pattern and "avg_time" in pattern:
            return pattern["avg_time"]
        
        # Default estimates by task count
        if len(similar_tasks) > 3:
            return 180  # 3 minutes with experience
        return 300  # 5 minutes default
    
    def _build_reasoning(self, domain: Domain, skills: List[Skill], 
                         similar_tasks: List[Any], pattern: Optional[Dict],
                         agent_id: str) -> str:
        """Build human-readable reasoning for routing decision"""
        parts = [
            f"Domain classified as {domain.value}",
            f"Skills matched: {[s.value for s in skills]}",
            f"Selected agent: {agent_id}"
        ]
        
        if similar_tasks:
            parts.append(f"Found {len(similar_tasks)} similar successful tasks in memory")
        
        if pattern:
            parts.append(f"Pattern success rate: {pattern.get('success_rate', 0):.2%}")
        
        return "; ".join(parts)
    
    def register_agent(self, agent_card: AgentCard):
        """Register a new agent"""
        self._agents[agent_card.agent_id] = agent_card
    
    def get_agent(self, agent_id: str) -> Optional[AgentCard]:
        """Get agent by ID"""
        return self._agents.get(agent_id)
    
    def list_agents(self, lane: Optional[str] = None) -> List[AgentCard]:
        """List all agents, optionally filtered by lane"""
        if lane:
            return [a for a in self._agents.values() if a.lane == lane]
        return list(self._agents.values())


# Convenience function for quick routing
def route_task(task_id: str, description: str, lane: str, 
               project_id: str = "default") -> RouteDecision:
    """Quick route a task without creating Task object"""
    router = HermesExperienceRouter()
    task = Task(
        task_id=task_id,
        project_id=project_id,
        description=description,
        lane=lane
    )
    return router.route(task)
