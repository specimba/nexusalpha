"""
vault/poisoning.py — MINJA Poisoning Detector v2

Replaces the naive negation-word heuristic with a multi-layer approach:
  Layer 1: Write velocity (unchanged — works well)
  Layer 2: Semantic contradiction via TF-IDF cosine similarity
  Layer 3: Statistical anomaly on write patterns

No external ML dependencies — uses a lightweight TF-IDF + cosine similarity
built on stdlib + SQLite. Drop-in replacement for v1.
"""

import time
import re
import math
from collections import deque, Counter
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field


class PoisoningError(Exception):
    """Raised when a memory write is flagged as a poisoning attempt."""
    pass


@dataclass
class WriteRecord:
    """Single write event for pattern analysis."""
    timestamp: float
    content: str
    agent_id: str
    project_id: str


class _TfidfIndex:
    """
    Lightweight in-memory TF-IDF index.
    No numpy, no sklearn — pure Python + math.
    Used for semantic similarity without external ML deps.
    """

    def __init__(self):
        self._doc_freq: Counter = Counter()
        self._doc_vectors: List[Dict[str, float]] = []
        self._doc_contents: List[str] = []
        self._doc_count: int = 0
        self._idf_cache: Dict[str, float] = {}

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Extract lowercase alpha tokens, 3+ chars."""
        tokens = re.findall(r'[a-z]{3,}', text.lower())
        stops = {
            'the', 'and', 'for', 'that', 'this', 'with', 'from', 'but',
            'not', 'are', 'was', 'were', 'been', 'have', 'has', 'had',
            'will', 'would', 'could', 'should', 'can', 'may', 'might',
        }
        return [t for t in tokens if t not in stops]

    def _compute_idf(self, term: str) -> float:
        """IDF = log(N / (1 + df)) — smoothed to avoid division by zero."""
        if term in self._idf_cache:
            return self._idf_cache[term]
        df = self._doc_freq.get(term, 0)
        idf = math.log((self._doc_count + 1) / (1 + df)) + 1
        self._idf_cache[term] = idf
        return idf

    def add_document(self, text: str) -> int:
        """Add a document and return its index."""
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1

        vector: Dict[str, float] = {}
        unique_tokens = set(tokens)
        for term in unique_tokens:
            vector[term] = (tf[term] / total) * self._compute_idf(term)

        self._doc_vectors.append(vector)
        self._doc_contents.append(text)
        self._doc_count += 1

        for term in unique_tokens:
            self._doc_freq[term] += 1
            self._idf_cache.pop(term, None)

        return self._doc_count - 1

    @staticmethod
    def _cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        if not v1 or not v2:
            return 0.0
        common = set(v1.keys()) & set(v2.keys())
        if not common:
            return 0.0
        dot = sum(v1[t] * v2[t] for t in common)
        mag1 = math.sqrt(sum(v ** 2 for v in v1.values()))
        mag2 = math.sqrt(sum(v ** 2 for v in v2.values()))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def find_similar(
        self, text: str, threshold: float = 0.3
    ) -> List[Tuple[int, float, str]]:
        """Find documents similar to the query text."""
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1

        query_vector: Dict[str, float] = {}
        unique_tokens = set(tokens)
        for term in unique_tokens:
            query_vector[term] = (tf[term] / total) * self._compute_idf(term)

        results = []
        for i, doc_vector in enumerate(self._doc_vectors):
            sim = self._cosine_similarity(query_vector, doc_vector)
            if sim >= threshold:
                results.append((i, sim, self._doc_contents[i]))

        return sorted(results, key=lambda x: x[1], reverse=True)


class MinjaDetector:
    """
    MINJA v2 — Multi-layer poisoning detector.

    Layer 1: Velocity guard (same as v1, works well)
    Layer 2: Semantic contradiction via TF-IDF cosine similarity
    Layer 3: Write pattern anomaly detection
    """

    def __init__(
        self,
        velocity_threshold: int = 10,
        window_seconds: int = 60,
        similarity_threshold: float = 0.4,
        contradiction_negation_boost: float = 0.15,
        pattern_window: int = 50,
        pattern_anomaly_ratio: float = 0.6,
    ):
        self.velocity_threshold = velocity_threshold
        self.window_seconds = window_seconds
        self._write_history: Dict[str, deque] = {}

        self.similarity_threshold = similarity_threshold
        self.negation_boost = contradiction_negation_boost
        self._project_indexes: Dict[str, _TfidfIndex] = {}
        self._project_doc_meta: Dict[str, List[Dict]] = {}

        self.pattern_window = pattern_window
        self.pattern_anomaly_ratio = pattern_anomaly_ratio
        self._agent_writes: Dict[str, deque] = {}

        self._negation_signals: Set[str] = {
            "not", "no", "never", "incorrect", "wrong", "false",
            "instead", "contradict", "deny", "reject", "dispute",
            "actually", "retract", "undo", "revoke", "overwrite",
        }

        self._negation_patterns = [
            re.compile(r'\bis not\b', re.I),
            re.compile(r'\bisn\'t\b', re.I),
            re.compile(r'\bwas not\b', re.I),
            re.compile(r'\bdoes not\b', re.I),
            re.compile(r'\bshould not\b', re.I),
            re.compile(r'\breplace .+ with\b', re.I),
            re.compile(r'\bchange .+ to\b', re.I),
            re.compile(r'\bcorrection\b', re.I),
        ]

    def check_velocity(self, agent_id: str) -> bool:
        now = time.time()
        if agent_id not in self._write_history:
            self._write_history[agent_id] = deque()
        history = self._write_history[agent_id]
        while history and history[0] < now - self.window_seconds:
            history.popleft()
        if len(history) >= self.velocity_threshold:
            return False
        history.append(now)
        return True

    def _get_project_index(self, project_id: str) -> _TfidfIndex:
        if project_id not in self._project_indexes:
            self._project_indexes[project_id] = _TfidfIndex()
            self._project_doc_meta[project_id] = []
        return self._project_indexes[project_id]

    def register_write(
        self, project_id: str, agent_id: str, content: str, trust_score: float
    ):
        """Register a successful write into the semantic index."""
        index = self._get_project_index(project_id)
        doc_idx = index.add_document(content)
        self._project_doc_meta[project_id].append(
            {"agent_id": agent_id, "trust": trust_score, "doc_idx": doc_idx}
        )
        if agent_id not in self._agent_writes:
            self._agent_writes[agent_id] = deque(maxlen=self.pattern_window)
        self._agent_writes[agent_id].append(
            WriteRecord(
                timestamp=time.time(), content=content,
                agent_id=agent_id, project_id=project_id,
            )
        )

    def _has_negation_signal(self, content: str) -> bool:
        words = set(re.findall(r'[a-z]+', content.lower()))
        if words & self._negation_signals:
            return True
        for pattern in self._negation_patterns:
            if pattern.search(content):
                return True
        return False

    def check_contradiction(
        self, project_id: str, agent_id: str, content: str, agent_trust: float,
    ) -> bool:
        if project_id not in self._project_indexes:
            return True
        index = self._get_project_index(project_id)

        has_negation = self._has_negation_signal(content)

        # Short bare negation from low-trust agent: direct block
        if len(content.strip()) < 20 and has_negation and agent_trust < 0.5:
            return False

        # Use lowered threshold when negation is present to catch more candidates
        search_threshold = (self.similarity_threshold - self.negation_boost
                            if has_negation else self.similarity_threshold)
        similar = index.find_similar(content, threshold=search_threshold)
        if not similar:
            return True

        meta = self._project_doc_meta.get(project_id, [])

        for doc_idx, sim_score, doc_content in similar:
            if doc_idx >= len(meta):
                continue
            doc_meta = meta[doc_idx]
            doc_trust = doc_meta["trust"]
            doc_agent = doc_meta["agent_id"]

            if has_negation and agent_trust < doc_trust:
                effective_threshold = self.similarity_threshold - self.negation_boost
                if sim_score >= effective_threshold:
                    return False

            if sim_score > 0.7 and doc_agent != agent_id:
                len_ratio = len(content) / max(len(doc_content), 1)
                if len_ratio < 0.3 or len_ratio > 3.0:
                    if agent_trust < 0.7:
                        return False

        return True

    def check_pattern_anomaly(self, agent_id: str) -> bool:
        if agent_id not in self._agent_writes:
            return True
        writes = list(self._agent_writes[agent_id])
        if len(writes) < 5:
            return True
        contents = [w.content for w in writes]
        content_counts = Counter(contents)
        most_common_ratio = content_counts.most_common(1)[0][1] / len(contents)
        if most_common_ratio > self.pattern_anomaly_ratio:
            return False
        return True

    def validate_write(
        self, project_id: str, agent_id: str, content: str, agent_trust: float
    ) -> Tuple[bool, str]:
        if not self.check_velocity(agent_id):
            return False, f"Velocity exceeded: agent {agent_id} wrote {self.velocity_threshold}+ entries in {self.window_seconds}s"
        if not self.check_contradiction(project_id, agent_id, content, agent_trust):
            return False, f"Contradiction detected: low-trust agent {agent_id} (trust={agent_trust:.2f}) contradicts high-trust memory"
        if not self.check_pattern_anomaly(agent_id):
            return False, f"Pattern anomaly: agent {agent_id} shows duplicate injection behavior"
        return True, "OK"
