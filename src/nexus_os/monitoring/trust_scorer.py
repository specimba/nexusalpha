"""Trust scoring system."""
from typing import Dict, Optional
import math

class TrustScorer:
    def __init__(self):
        self._hot_path_cache: Dict[str, float] = {}

    def get_score_hotpath(
        self, agent_id: str,
        Q: float, qmin: float = 0.1, n: int = 0, n0: float = 5.0,
        U: float = 1.0, D_plus: float = 0.0, R: float = 0.0, D_minus: float = 0.0,
        alpha: float = 0.4, gamma: float = 0.3, beta: float = 0.2, eta: float = 0.1,
        kappa: float = 2.5, delta: float = 0.5, epsilon: float = 1e-4
    ) -> Optional[float]:
        status = "active"
        if status in {"blocked", "unassigned", "not_applicable"}:
            return None
        Qeff = max(0.0, min(1.0, (Q - qmin) / (1 - qmin))) * (1 - math.exp(-n / n0))
        P = (alpha * U) + (gamma * D_plus) - (beta * R) - (eta * D_minus)
        raw_score = math.tanh(kappa * (Qeff ** delta) * P)
        return 0.0 if abs(raw_score) < epsilon else round(raw_score, 4)
