"""governor/trust_scoring.py — Trust Scoring v2.1 Hot-Path"""
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

class FindingState(Enum):
    NONE = "none"
    SUSPECTED = "suspected"
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    HELD = "held"
    ESCALATED = "escalated"

# Lane parameters (v2.1)
LANE_PARAMS = {
    "research":       {"qmin": 0.3, "n0": 5, "Rcrit": 0.7, "alpha": 1.0, "beta": 1.0, "gamma": 0.3, "eta": 0.2, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
    "review":         {"qmin": 0.5, "n0": 3, "Rcrit": 0.5, "alpha": 0.8, "beta": 1.5, "gamma": 0.5, "eta": 0.5, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
    "audit_security": {"qmin": 0.6, "n0": 2, "Rcrit": 0.3, "alpha": 0.5, "beta": 2.0, "gamma": 0.3, "eta": 0.3, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
    "compliance":     {"qmin": 0.7, "n0": 2, "Rcrit": 0.2, "alpha": 0.3, "beta": 3.0, "gamma": 0.2, "eta": 0.2, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
    "implementation": {"qmin": 0.4, "n0": 3, "Rcrit": 0.4, "alpha": 1.2, "beta": 1.5, "gamma": 0.8, "eta": 0.6, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
    "orchestration":  {"qmin": 0.5, "n0": 4, "Rcrit": 0.4, "alpha": 0.8, "beta": 1.2, "gamma": 1.0, "eta": 1.0, "kappa": 1.0, "delta": 1.0, "epsilon": 0.05},
}

@dataclass
class ScoringInput:
    status: str
    lane: str
    utility: float = 0.0
    harm: float = 0.0
    coverage: float = 0.0
    omission: float = 0.0
    evidence_confidence: float = 0.0
    evidence_count: int = 1
    hard_fail: bool = False

@dataclass
class ScoringResult:
    score: Optional[float]
    finding_state: FindingState
    qeff: float
    reason_code: str
    computation_us: int

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def compute_score(inp: ScoringInput) -> ScoringResult:
    """Hot-path scoring: ~4-15μs target."""
    start_ns = time.perf_counter_ns()
    
    # INV1: null != 0
    if inp.status in {"blocked", "unassigned", "not_applicable"}:
        us = (time.perf_counter_ns() - start_ns) // 1000
        return ScoringResult(None, FindingState.NONE, 0.0, "null_state", us)
    
    # INV2: non-compensatory harm
    params = LANE_PARAMS.get(inp.lane, LANE_PARAMS["research"])
    if inp.hard_fail or inp.harm > params["Rcrit"]:
        us = (time.perf_counter_ns() - start_ns) // 1000
        state = FindingState.ESCALATED if inp.lane not in {"audit_security", "compliance"} else FindingState.HELD
        return ScoringResult(-1.0, state, 0.0, "critical_harm", us)
    
    # Evidence gating (Qeff)
    q_gated = _clip((inp.evidence_confidence - params["qmin"]) / (1.0 - params["qmin"]), 0, 1)
    Qeff = q_gated * (1.0 - math.exp(-inp.evidence_count / params["n0"]))
    
    # Performance composite
    P =