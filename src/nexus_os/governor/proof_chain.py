"""VAP (Verification and Audit Protocol) proof chain implementation."""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json

@dataclass
class ProofEntry:
    entry_id: str
    timestamp: datetime
    agent_id: str
    action: str
    details: Dict[str, Any]
    level: str = "INFO"
    l1_hash: str = ""
    l2_hash: str = ""

    def compute_l1_hash(self) -> str:
        data = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "action": self.action,
            "details": self.details,
            "level": self.level
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def finalize(self, previous_l2_hash: str = "") -> None:
        self.l1_hash = self.compute_l1_hash()
        chain_data = self.l1_hash + previous_l2_hash
        self.l2_hash = hashlib.sha256(chain_data.encode()).hexdigest()

class ProofChain:
    def __init__(self):
        self._entries: List[ProofEntry] = []
        self._entry_index: Dict[str, ProofEntry] = {}
        self._last_l2_hash: str = ""
        self._counter: int = 0

    def _generate_entry_id(self) -> str:
        self._counter += 1
        return f"proof-{self._counter:08d}"

    def record(self, agent_id: str, action: str, details: Dict[str, Any], level: str = "INFO") -> ProofEntry:
        entry = ProofEntry(
            entry_id=self._generate_entry_id(),
            timestamp=datetime.utcnow(),
            agent_id=agent_id,
            action=action,
            details=details,
            level=level
        )
        entry.finalize(self._last_l2_hash)
        self._entries.append(entry)
        self._entry_index[entry.entry_id] = entry
        self._last_l2_hash = entry.l2_hash
        return entry

    def verify_chain(self) -> bool:
        previous_l2 = ""
        for entry in self._entries:
            expected_l1 = entry.compute_l1_hash()
            if entry.l1_hash != expected_l1: return False
            expected_l2 = hashlib.sha256((entry.l1_hash + previous_l2).encode()).hexdigest()
            if entry.l2_hash != expected_l2: return False
            previous_l2 = entry.l2_hash
        return True

    def get_chain_summary(self) -> Dict[str, Any]:
        return {
            "total_entries": len(self._entries),
            "latest_l2_hash": self._last_l2_hash,
            "chain_valid": self.verify_chain()
        }
