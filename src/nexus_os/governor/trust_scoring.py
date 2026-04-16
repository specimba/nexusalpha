"""governor/trust_scoring.py — Trust Scoring v2.1 Hot-Path Implementation"""
import math, time, uuid, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class AgentStatus(Enum):
    ACTIVE = "active"; BLOCKED = "blocked"
    UNASSIGNED = "unassigned"; NOT_APPLICABLE = "not_applicable"

class Lane(Enum):
    RESEARCH = "research"; REVIEW = "review"
    AUDIT_SECURITY = "audit_security"; COMPLIANCE = "compliance"
    IMPLEMENTATION = "implementation"; ORCHESTRATION = "orchestration"
    SYNTHESIS = "synthesis"

class FindingState(Enum):
    NONE = "none"; SUSPECTED = "suspected"
    PROVISIONAL = "provisional"; CONFIRMED = "confirmed"
    REJECTED = "rejected"; HELD = "held"; ESCALATED = "escalated"

class ReasonCode(Enum):
    LOW_CONFIDENCE = "low_confidence"; STALE_EVIDENCE = "stale_evidence"
    HIGH_VALUE = "high_value_contribution"; REGRESSION_DOMINANT = "regression_dominant"
    UNDER_DELIVERY = "under_delivery"; OVER_DELIVERY = "over_delivery"
    MIXED_SIGNAL = "mixed_signal"; BOUNDARY_VIOLATION = "boundary_violation"
    CRITICAL_HARM = "critical_harm"; EVIDENCE_OVERCLAIM = "evidence_overclaim"
    COVERAGE_GAP = "coverage_gap"; GOVERNANCE_SLIPPAGE = "governance_slippage"
    AVAILABILITY_REFUSAL = "availability_refusal"; NONE = "none"

@dataclass(frozen=True)
class LaneParams:
    qmin: float; n0: float; Rcrit: float
    alpha: float; beta: float; gamma: float; eta: float
    kappa: float; delta: float; epsilon: float

DEFAULT_LANE_PARAMS = {
    Lane.RESEARCH:        LaneParams(0.3, 5, 0.8, 0.4, 0.3, 0.2, 0.1, 1.5, 1.0, 0.05),
    Lane.REVIEW:          LaneParams(0.5, 3, 0.6, 0.3, 0.4, 0.2, 0.1, 1.5, 1.0, 0.05),
    Lane.AUDIT_SECURITY:  LaneParams(0.7, 2, 0.4, 0.2, 0.5, 0.1, 0.2, 2.0, 1.2, 0.03),
    Lane.COMPLIANCE:      LaneParams(0.8, 1, 0.2, 0.1, 0.6, 0.1, 0.2, 2.5, 1.5, 0.02),
    Lane.IMPLEMENTATION:  LaneParams(0.6, 4, 0.5, 0.3, 0.3, 0.3, 0.1, 1.8, 1.0, 0.04),
    Lane.ORCHESTRATION:   LaneParams(0.4, 3, 0.7, 0.3, 0.2, 0.3, 0.2, 1.5, 1.0, 0.05),
    Lane.SYNTHESIS:       LaneParams(0.5, 3, 0.5, 0.3, 0.3, 0.3, 0.1, 1.6, 1.0, 0.04),
}

@dataclass
class ScoringInput:
    status: AgentStatus; lane: Lane; Q: float; n: int
    U: float; R: float; D_plus: float; D_minus: float
    hard_fail: bool = False

@dataclass
class ScoringResult:
    score: Optional[float]; Qeff: float; lane: Lane
    finding_state: FindingState
    reason_primary: ReasonCode; reason_secondary: ReasonCode
    computation_us: int; invariant_flags: dict

@dataclass
class AgentCard:
    agent_id: str
    current_lane: Optional[Lane] = None
    latest_score: Optional[float] = None
    trust: float = 0.5
    availability: str = "available"
    hold_state: bool = False
    evidence_count: int = 0
    capability_profile: dict = field(default_factory=dict)
    failure_patterns: dict = field(default_factory=dict)
    governance_flags: list = field(default_factory=list)
    last_verified_event: Optional[str] = None
    authority_band: str = "standard"
    finding_state: FindingState = FindingState.NONE

def _determine_reasons(inp, score, Qeff):
    contributions = {
        ReasonCode.HIGH_VALUE: inp.U,
        ReasonCode.REGRESSION_DOMINANT: inp.R,
        ReasonCode.UNDER_DELIVERY: inp.D_minus,
        ReasonCode.OVER_DELIVERY: inp.D_plus,
        ReasonCode.LOW_CONFIDENCE: 1.0 - inp.Q,
        ReasonCode.CRITICAL_HARM: 1.0 if inp.hard_fail else 0.0,
    }
    sorted_r = sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True)
    pri = sorted_r[0][0] if sorted_r else ReasonCode.NONE
    sec = sorted_r[1][0] if len(sorted_r) > 1 else ReasonCode.NONE
    if pri == ReasonCode.NONE: pri = ReasonCode.MIXED_SIGNAL
    return pri, sec

def compute_score(inp, lane_params=None):
    start_ns = time.perf_counter_ns()
    params = (lane_params or DEFAULT_LANE_PARAMS)[inp.lane]
    flags = {}
    if inp.status in {AgentStatus.BLOCKED, AgentStatus.UNASSIGNED, AgentStatus.NOT_APPLICABLE}:
        us = (time.perf_counter_ns() - start_ns) // 1000
        return ScoringResult(None, 0.0, inp.lane, FindingState.NONE,
                             ReasonCode.NONE, ReasonCode.NONE, us, {"inv1": True})
    if inp.hard_fail:
        us = (time.perf_counter_ns() - start_ns) // 1000
        return ScoringResult(-1.0, 0.0, inp.lane, FindingState.ESCALATED,
                             ReasonCode.CRITICAL_HARM, ReasonCode.NONE, us, {"inv2": True, "trigger": "hard_fail"})
    if inp.R > params.Rcrit:
        us = (time.perf_counter_ns() - start_ns) // 1000
        if inp.lane in {Lane.AUDIT_SECURITY, Lane.COMPLIANCE}:
            return ScoringResult(None, 0.0, inp.lane, FindingState.HELD,
                                 ReasonCode.REGRESSION_DOMINANT, ReasonCode.BOUNDARY_VIOLATION,
                                 us, {"inv2": True, "trigger": "R>Rcrit", "hold": True})
        return ScoringResult(-1.0, 0.0, inp.lane, FindingState.ESCALATED,
                             ReasonCode.REGRESSION_DOMINANT, ReasonCode.BOUNDARY_VIOLATION,
                             us, {"inv2": True, "trigger": "R>Rcrit"})
    q_gated = max(0.0, min(1.0, (inp.Q - params.qmin) / (1.0 - params.qmin)))
    Qeff = q_gated * (1.0 - math.exp(-inp.n / params.n0))
    P = (params.alpha * inp.U + params.gamma * inp.D_plus
         - params.beta * inp.R - params.eta * inp.D_minus)
    raw_score = math.tanh(params.kappa * (Qeff ** params.delta) * P)
    score = 0.0 if abs(raw_score) < params.epsilon else raw_score
    assert -1.0 <= score <= 1.0, f"INV3 FAIL: {score}"
    us = (time.perf_counter_ns() - start_ns) // 1000
    finding = FindingState.PROVISIONAL if score >= 0 else FindingState.SUSPECTED
    if inp.Q < params.qmin and inp.R > 0.3:
        finding = FindingState.HELD
        flags["v21_hold"] = True
    pri, sec = _determine_reasons(inp, score, Qeff)
    flags["inv3"] = True; flags["us"] = us
    return ScoringResult(score, Qeff, inp.lane, finding, pri, sec, us, flags)

class MemoryTracks:
    def __init__(self):
        self.event_memory = []
        self.trust_memory = {}
        self.capability_memory = {}
        self.failure_pattern_memory = {}
        self.governance_memory = {}
    def append_event(self, event):
        event["event_id"] = str(uuid.uuid4()); event["timestamp"] = time.time()
        self.event_memory.append(event)
    def update_trust(self, agent_id, lane, Qeff, score, hard_fail=False, lambda_hf=0.5):
        if score is None: return
        key = (agent_id, lane)
        if key not in self.trust_memory: self.trust_memory[key] = {"alpha": 1.0, "beta": 1.0}
        self.trust_memory[key]["alpha"] += Qeff * max(score, 0.0)
        self.trust_memory[key]["beta"] += Qeff * (max(-score, 0.0) + lambda_hf * hard_fail)
    def get_trust(self, agent_id, lane):
        key = (agent_id, lane)
        if key not in self.trust_memory: return 0.5
        a = self.trust_memory[key]["alpha"]; b = self.trust_memory[key]["beta"]
        return a / (a + b)
    def update_capability(self, agent_id, lane, score):
        if agent_id not in self.capability_memory: self.capability_memory[agent_id] = {}
        if lane.value not in self.capability_memory[agent_id]:
            self.capability_memory[agent_id][lane.value] = {"tasks": 0, "positive": 0}
        self.capability_memory[agent_id][lane.value]["tasks"] += 1
        if score > 0: self.capability_memory[agent_id][lane.value]["positive"] += 1
    def get_capability(self, agent_id, lane):
        if agent_id not in self.capability_memory: return {"tasks": 0, "positive": 0, "strength": "unknown"}
        d = self.capability_memory[agent_id].get(lane.value, {"tasks": 0, "positive": 0})
        t = d["tasks"]
        if t == 0: s = "unknown"
        elif d["positive"]/t > 0.7: s = "strong"
        elif d["positive"]/t > 0.4: s = "moderate"
        else: s = "weak"
        return {"tasks": t, "positive": d["positive"], "strength": s}
    def record_failure_pattern(self, agent_id, pattern):
        if agent_id not in self.failure_pattern_memory: self.failure_pattern_memory[agent_id] = {}
        self.failure_pattern_memory[agent_id][pattern] = self.failure_pattern_memory[agent_id].get(pattern, 0) + 1
    def get_failure_patterns(self, agent_id):
        return dict(self.failure_pattern_memory.get(agent_id, {}))
    def record_governance_event(self, agent_id, event_type, detail=""):
        if agent_id not in self.governance_memory: self.governance_memory[agent_id] = {"events": [], "flags": set()}
        self.governance_memory[agent_id]["events"].append({"type": event_type, "detail": detail, "timestamp": time.time()})
    def get_governance_summary(self, agent_id):
        if agent_id not in self.governance_memory: return {"events": 0, "flags": []}
        return {"events": len(self.governance_memory[agent_id]["events"]), "flags": list(self.governance_memory[agent_id]["flags"])}

class TrustScoringGate:
    def __init__(self, lane_params=None):
        self.lane_params = lane_params or DEFAULT_LANE_PARAMS
        self.memory = MemoryTracks()
    def score(self, inp, agent_id):
        result = compute_score(inp, self.lane_params)
        self.memory.append_event({
            "agent_id": agent_id, "lane": inp.lane.value,
            "score": result.score, "Qeff": result.Qeff,
            "hard_fail": inp.hard_fail, "finding_state": result.finding_state.value,
            "reason_primary": result.reason_primary.value, "reason_secondary": result.reason_secondary.value,
        })
        if result.score is not None:
            self.memory.update_trust(agent_id, inp.lane, result.Qeff, result.score, inp.hard_fail)
            self.memory.update_capability(agent_id, inp.lane, result.score)
        if result.score < 0:
            self.memory.record_failure_pattern(agent_id, result.reason_primary.value)
        if inp.hard_fail:
            self.memory.record_governance_event(agent_id, "hard_fail", result.reason_primary.value)
        if result.finding_state == FindingState.HELD:
            self.memory.record_governance_event(agent_id, "hold", "low_conf_high_risk")
        if result.finding_state == FindingState.ESCALATED:
            self.memory.record_governance_event(agent_id, "escalated", result.reason_primary.value)
        return result
    def get_trust(self, agent_id, lane): return self.memory.get_trust(agent_id, lane)
    def get_agent_card(self, agent_id, lane):
        trust = self.memory.get_trust(agent_id, lane)
        cap = self.memory.get_capability(agent_id, lane)
        fail = self.memory.get_failure_patterns(agent_id)
        gov = self.memory.get_governance_summary(agent_id)
        if trust > 0.8 and cap.get("strength") == "strong": band = "elevated"
        elif trust < 0.3 or len(fail) > 5: band = "restricted"
        else: band = "standard"
        latest_score = None; finding = FindingState.NONE
        for ev in reversed(self.memory.event_memory):
            if ev.get("agent_id") == agent_id and ev.get("lane") == lane.value:
                latest_score = ev.get("score")
                finding = FindingState(ev.get("finding_state", "none"))
                break
        return AgentCard(agent_id=agent_id, current_lane=lane, latest_score=latest_score, trust=trust,
                         capability_profile=cap, failure_patterns=fail, governance_flags=gov.get("flags", []),
                         authority_band=band, finding_state=finding)
    def record_refusal(self, agent_id, lane, reason="overload"):
        self.memory.append_event({
            "agent_id": agent_id, "lane": lane.value,
            "score": None, "finding_state": FindingState.NONE.value,
            "refusal": True, "refusal_reason": reason,
            "reason_primary": ReasonCode.AVAILABILITY_REFUSAL.value,
        })
    def reset(self): self.memory = MemoryTracks()