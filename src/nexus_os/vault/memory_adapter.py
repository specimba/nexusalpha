"""
vault/memory_adapter.py — Mem0Adapter: Persistent Semantic Memory for Nexus OS

Bridges the Nexus OS S-P-E-W vault hierarchy with mem0's semantic memory layer,
enabling cross-session context retention with semantic search.

Layer Mapping:
  Session   → mem0 short-term (TTL 1 hour, metadata: layer=session)
  Project   → mem0 working    (TTL 7 days, metadata: layer=project)
  Experience → mem0 long-term (no TTL,     metadata: layer=experience)
  Wisdom    → mem0 core       (no TTL, highest relevance, metadata: layer=wisdom)

Fallback:
  When mem0 cloud is unavailable (no API key / init failure), falls back to
  _LocalMemoryBackend — a JSON-file-based store with keyword search at
  ~/.nexus_os/mem0_local.json.
"""

import json
import os
import time
import uuid
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

VALID_LAYERS = {"session", "project", "experience", "wisdom"}

LAYER_TTL_SECONDS = {
    "session": 3600,       # 1 hour
    "project": 604800,     # 7 days
    "experience": None,    # no expiry
    "wisdom": None,        # no expiry
}

LAYER_RELEVANCE_BOOST = {
    "session": 0.0,
    "project": 0.1,
    "experience": 0.25,
    "wisdom": 0.5,
}

LOCAL_BACKEND_PATH = os.path.expanduser("~/.nexus_os/mem0_local.json")

# ~4 chars per token is a safe heuristic
CHARS_PER_TOKEN_ESTIMATE = 4


# ── Local Fallback Backend ─────────────────────────────────────────────────────

class _LocalMemoryBackend:
    """JSON-file-based memory backend used when mem0 cloud is unavailable.

    Provides CRUD operations and keyword-based search (no semantic search).
    Persists to ~/.nexus_os/mem0_local.json.

    All methods are resilient to I/O errors (disk full, permission denied, etc.)
    and log warnings rather than raising.
    """

    def __init__(self, storage_path: Optional[str] = None):
        self._path = storage_path or LOCAL_BACKEND_PATH
        self._memories: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        """Load memories from JSON file."""
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._memories = json.load(f)
                logger.debug("Loaded %d memories from %s", len(self._memories), self._path)
            else:
                self._memories = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load local memory store at %s: %s. Starting empty.", self._path, e)
            self._memories = {}

    def _save(self) -> None:
        """Persist memories to JSON file."""
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._memories, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning("Failed to save local memory store to %s: %s", self._path, e)

    # ── CRUD ──────────────────────────────────────────────────────

    def add(
        self,
        content: str,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        layer: str = "session",
    ) -> str:
        """Store a new memory. Returns the memory ID."""
        memory_id = uuid.uuid4().hex[:16]
        now = time.time()
        ttl = LAYER_TTL_SECONDS.get(layer)
        self._memories[memory_id] = {
            "id": memory_id,
            "content": content,
            "agent_id": agent_id,
            "metadata": metadata or {},
            "layer": layer,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + ttl if ttl else None,
        }
        self._save()
        logger.debug("Local store: added memory %s (layer=%s, agent=%s)", memory_id, layer, agent_id)
        return memory_id

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single memory by ID, respecting TTL."""
        mem = self._memories.get(memory_id)
        if mem is None:
            return None
        if self._is_expired(mem):
            logger.debug("Local store: memory %s expired, removing", memory_id)
            del self._memories[memory_id]
            self._save()
            return None
        return dict(mem)

    def get_all(
        self,
        agent_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all non-expired memories, optionally filtered."""
        results = []
        expired_ids = []
        for mid, mem in self._memories.items():
            if self._is_expired(mem):
                expired_ids.append(mid)
                continue
            if agent_id and mem.get("agent_id") != agent_id:
                continue
            if layer and mem.get("layer") != layer:
                continue
            results.append(dict(mem))

        if expired_ids:
            for mid in expired_ids:
                del self._memories[mid]
            self._save()

        return results

    def search(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 5,
        layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword-based search across memory content.

        Splits query into words and counts matches. Returns results sorted
        by match count descending. Each result includes a ``score`` field
        (float 0.0–1.0 proportional to match ratio).
        """
        if not query or not query.strip():
            return []

        query_words = set(re.findall(r"\w+", query.lower()))
        if not query_words:
            return []

        candidates = self.get_all(agent_id=agent_id, layer=layer)
        scored = []
        for mem in candidates:
            content_words = set(re.findall(r"\w+", mem.get("content", "").lower()))
            matches = len(query_words & content_words)
            if matches > 0:
                score = matches / len(query_words)
                # Apply layer relevance boost
                boost = LAYER_RELEVANCE_BOOST.get(mem.get("layer", "session"), 0.0)
                score = min(score + boost, 1.0)
                result = dict(mem)
                result["score"] = round(score, 4)
                scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if found and deleted."""
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._save()
            return True
        return False

    def update(self, memory_id: str, data: Dict[str, Any]) -> bool:
        """Update memory fields. Returns True if the memory exists."""
        mem = self._memories.get(memory_id)
        if mem is None:
            return False
        for key, val in data.items():
            if key == "id":
                continue  # immutable
            mem[key] = val
        mem["updated_at"] = time.time()
        self._save()
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Return memory counts by layer and total."""
        counts: Dict[str, int] = {layer: 0 for layer in VALID_LAYERS}
        agents = set()
        expired_ids = []
        for mid, mem in self._memories.items():
            if self._is_expired(mem):
                expired_ids.append(mid)
                continue
            layer = mem.get("layer", "session")
            if layer in counts:
                counts[layer] += 1
            aid = mem.get("agent_id")
            if aid:
                agents.add(aid)

        if expired_ids:
            for mid in expired_ids:
                del self._memories[mid]
            self._save()

        return {
            "total": sum(counts.values()),
            "session": counts["session"],
            "project": counts["project"],
            "experience": counts["experience"],
            "wisdom": counts["wisdom"],
            "agent_count": len(agents),
            "backend": "local",
        }

    def reset(self) -> None:
        """Clear all memories."""
        self._memories.clear()
        self._save()

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def _is_expired(mem: Dict[str, Any]) -> bool:
        """Check if a memory has passed its TTL."""
        expires_at = mem.get("expires_at")
        if expires_at is None:
            return False
        return time.time() > expires_at


# ── Mem0 Adapter ──────────────────────────────────────────────────────────────

class Mem0Adapter:
    """Persistent memory adapter using mem0 for cross-session context retention.

    Bridges the Nexus OS S-P-E-W vault layers with mem0's semantic memory:

      - Session memory  → mem0 short-term (TTL 1 hour)
      - Project memory  → mem0 working    (TTL 7 days)
      - Experience memory → mem0 long-term (no TTL)
      - Wisdom memory   → mem0 core       (no TTL, highest relevance boost)

    mem0 provides semantic search over past interactions, enabling agents to
    recall relevant context without loading full conversation history.

    When mem0 cloud is unavailable, gracefully degrades to a local JSON-based
    backend with keyword search.

    Usage::

        adapter = Mem0Adapter()
        context = adapter.get_context_for_task("Fix encryption fallback")
        adapter.extract_learnings("Fix encryption fallback", result, True, 450)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the memory adapter.

        Args:
            config: Optional dict with the following keys:
                - ``mem0_config``: A mem0 MemoryConfig instance. If provided,
                  will be used to create the mem0 Memory client.
                - ``force_local``: If True, skip mem0 and use local backend.
                - ``storage_path``: Path for local JSON backend (default:
                  ~/.nexus_os/mem0_local.json).
        """
        cfg = config or {}
        self._force_local = cfg.get("force_local", False)
        self._storage_path = cfg.get("storage_path", LOCAL_BACKEND_PATH)

        self._mem0_client = None
        self._local: Optional[_LocalMemoryBackend] = None
        self._using_local = False

        if not self._force_local:
            self._try_init_mem0(cfg.get("mem0_config"))

        if self._mem0_client is None:
            logger.info("mem0 cloud unavailable — using local JSON backend at %s", self._storage_path)
            self._local = _LocalMemoryBackend(self._storage_path)
            self._using_local = True

    # ── Initialization ────────────────────────────────────────────

    def _try_init_mem0(self, mem0_config: Any) -> None:
        """Attempt to initialize the mem0 Memory client.

        Catches any exception (missing API key, network error, etc.) and
        logs a warning, leaving ``self._mem0_client`` as None.
        """
        try:
            from mem0 import Memory

            if mem0_config is not None:
                self._mem0_client = Memory(config=mem0_config)
            else:
                self._mem0_client = Memory()

            logger.info("mem0 client initialized successfully")
        except Exception as e:
            logger.warning("mem0 initialization failed, falling back to local backend: %s", e)
            self._mem0_client = None

    # ── Store ─────────────────────────────────────────────────────

    def store(
        self,
        agent_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        layer: str = "session",
    ) -> str:
        """Store a memory with layer classification.

        Maps Nexus OS S-P-E-W layers to mem0 metadata and TTL policies.

        Args:
            agent_id: Identifier of the agent creating the memory.
            content: The memory text content.
            metadata: Optional additional metadata dict.
            layer: One of ``session``, ``project``, ``experience``, ``wisdom``.

        Returns:
            The memory ID string.

        Raises:
            ValueError: If layer is invalid or content is empty.
        """
        if layer not in VALID_LAYERS:
            raise ValueError(f"Invalid layer: {layer!r}. Must be one of {VALID_LAYERS}")
        if not content or not content.strip():
            raise ValueError("Content must not be empty")

        enriched_meta = {
            "layer": layer,
            "created_at": time.time(),
            "ttl_seconds": LAYER_TTL_SECONDS.get(layer),
        }
        if metadata:
            enriched_meta.update(metadata)

        try:
            if self._using_local:
                return self._local.add(
                    content=content,
                    agent_id=agent_id,
                    metadata=enriched_meta,
                    layer=layer,
                )
            else:
                result = self._mem0_client.add(
                    messages=content,
                    agent_id=agent_id,
                    metadata=enriched_meta,
                )
                # mem0 add() returns a dict with "results" list of {id, ...}
                if isinstance(result, dict) and "results" in result:
                    ids = result["results"]
                    if ids and isinstance(ids, list) and len(ids) > 0:
                        mid = ids[0].get("id", uuid.uuid4().hex[:16]) if isinstance(ids[0], dict) else str(ids[0])
                        logger.info(
                            "Stored mem0 memory: id=%s layer=%s agent=%s",
                            mid, layer, agent_id,
                        )
                        return str(mid)
                # Fallback ID
                fallback_id = uuid.uuid4().hex[:16]
                logger.info("Stored mem0 memory (fallback id=%s): layer=%s agent=%s", fallback_id, layer, agent_id)
                return fallback_id
        except Exception as e:
            logger.error("Failed to store memory (layer=%s, agent=%s): %s", layer, agent_id, e)
            raise RuntimeError(f"Memory store failed: {e}") from e

    # ── Search ────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 5,
        layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search across stored memories.

        Args:
            query: The search query text.
            agent_id: Optional agent filter.
            limit: Maximum number of results.
            layer: Optional layer filter (session/project/experience/wisdom).

        Returns:
            List of dicts with keys: ``id``, ``content``, ``score``, ``metadata``, ``layer``.
        """
        if not query or not query.strip():
            return []

        try:
            if self._using_local:
                logger.debug("Local search: query=%r agent=%s limit=%d", query, agent_id, limit)
                return self._local.search(query=query, agent_id=agent_id, limit=limit, layer=layer)
            else:
                filters = {}
                if layer:
                    filters["layer"] = layer

                results = self._mem0_client.search(
                    query=query,
                    agent_id=agent_id,
                    limit=limit,
                    filters=filters or None,
                )

                mapped = []
                if isinstance(results, dict) and "results" in results:
                    items = results["results"]
                elif isinstance(results, list):
                    items = results
                else:
                    items = []

                for item in items:
                    if isinstance(item, dict):
                        mem_meta = item.get("metadata", {})
                        mapped.append({
                            "id": item.get("id", ""),
                            "content": item.get("memory", item.get("content", "")),
                            "score": item.get("score", 0.0),
                            "metadata": mem_meta,
                            "layer": mem_meta.get("layer", "session"),
                        })

                logger.debug("mem0 search returned %d results for query=%r", len(mapped), query)
                return mapped

        except Exception as e:
            logger.error("Memory search failed (query=%r): %s", query, e)
            return []

    # ── Get All ───────────────────────────────────────────────────

    def get_all(
        self,
        agent_id: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all memories for an agent/layer.

        Useful for wisdom extraction and bulk operations.

        Args:
            agent_id: Optional agent filter.
            layer: Optional layer filter.

        Returns:
            List of memory dicts.
        """
        try:
            if self._using_local:
                return self._local.get_all(agent_id=agent_id, layer=layer)
            else:
                filters = {}
                if layer:
                    filters["layer"] = layer

                results = self._mem0_client.get_all(
                    agent_id=agent_id,
                    filters=filters or None,
                )

                if isinstance(results, dict) and "results" in results:
                    items = results["results"]
                elif isinstance(results, list):
                    items = results
                else:
                    items = []

                mapped = []
                for item in items:
                    if isinstance(item, dict):
                        mem_meta = item.get("metadata", {})
                        mapped.append({
                            "id": item.get("id", ""),
                            "content": item.get("memory", item.get("content", "")),
                            "score": item.get("score", 1.0),
                            "metadata": mem_meta,
                            "layer": mem_meta.get("layer", "session"),
                        })

                return mapped

        except Exception as e:
            logger.error("Failed to get_all memories (agent=%s, layer=%s): %s", agent_id, layer, e)
            return []

    # ── Delete ────────────────────────────────────────────────────

    def delete(self, memory_id: str) -> bool:
        """Remove a specific memory by ID.

        Args:
            memory_id: The ID of the memory to delete.

        Returns:
            True if the memory was found and deleted, False otherwise.
        """
        if not memory_id:
            return False

        try:
            if self._using_local:
                result = self._local.delete(memory_id)
                if result:
                    logger.info("Deleted local memory: %s", memory_id)
                return result
            else:
                self._mem0_client.delete(memory_id)
                logger.info("Deleted mem0 memory: %s", memory_id)
                return True
        except Exception as e:
            logger.error("Failed to delete memory %s: %s", memory_id, e)
            return False

    # ── Promotion ─────────────────────────────────────────────────

    def promote_to_experience(self, memory_id: str) -> bool:
        """Promote a session or project memory to the experience layer.

        Analogous to S-P-E-W promotion: promotes valuable short/medium-term
        memories into long-term experience patterns.

        Args:
            memory_id: The ID of the memory to promote.

        Returns:
            True if promotion succeeded, False otherwise.

        Raises:
            ValueError: If the memory is already at experience or wisdom layer.
        """
        mem = self._get_memory(memory_id)
        if mem is None:
            logger.warning("Cannot promote: memory %s not found", memory_id)
            return False

        current_layer = mem.get("layer", "session")
        if current_layer in ("experience", "wisdom"):
            raise ValueError(
                f"Cannot promote {current_layer!r} memory to experience. "
                f"Already at layer '{current_layer}'."
            )

        return self._set_layer(memory_id, "experience")

    def promote_to_wisdom(self, memory_id: str) -> bool:
        """Promote an experience memory to the wisdom layer.

        Wisdom is the highest-value layer — only experience memories can be
        promoted to wisdom.

        Args:
            memory_id: The ID of the memory to promote.

        Returns:
            True if promotion succeeded, False otherwise.

        Raises:
            ValueError: If the memory is not at the experience layer.
        """
        mem = self._get_memory(memory_id)
        if mem is None:
            logger.warning("Cannot promote: memory %s not found", memory_id)
            return False

        current_layer = mem.get("layer", "session")
        if current_layer != "experience":
            raise ValueError(
                f"Cannot promote {current_layer!r} memory to wisdom. "
                f"Only experience memories can be promoted to wisdom."
            )

        return self._set_layer(memory_id, "wisdom")

    def _get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a single memory by ID from whichever backend is active."""
        try:
            if self._using_local:
                return self._local.get(memory_id)
            else:
                result = self._mem0_client.get(memory_id)
                if isinstance(result, dict) and "results" in result:
                    items = result["results"]
                    if items and isinstance(items, list) and len(items) > 0:
                        item = items[0]
                        mem_meta = item.get("metadata", {})
                        return {
                            "id": item.get("id", ""),
                            "content": item.get("memory", item.get("content", "")),
                            "metadata": mem_meta,
                            "layer": mem_meta.get("layer", "session"),
                        }
                return None
        except Exception as e:
            logger.error("Failed to get memory %s: %s", memory_id, e)
            return None

    def _set_layer(self, memory_id: str, new_layer: str) -> bool:
        """Update a memory's layer classification."""
        try:
            if self._using_local:
                return self._local.update(memory_id, {"layer": new_layer})
            else:
                self._mem0_client.update(
                    memory_id,
                    data=self._get_memory(memory_id).get("content", ""),
                    metadata={"layer": new_layer},
                )
                logger.info("Promoted memory %s to layer=%s", memory_id, new_layer)
                return True
        except Exception as e:
            logger.error("Failed to set layer for memory %s to %s: %s", memory_id, new_layer, e)
            return False

    # ── Context Retrieval ─────────────────────────────────────────

    def get_context_for_task(
        self,
        task_description: str,
        agent_id: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        """Get relevant context for a task, formatted for prompt injection.

        Uses semantic search to find the most relevant memories, then
        packs them into a string that fits within the token budget.

        Args:
            task_description: The task description to search against.
            agent_id: Optional agent filter.
            max_tokens: Approximate token budget for the output string.

        Returns:
            A formatted string of relevant memories, suitable for injection
            into a system prompt. Returns an empty string if no context found.
        """
        if not task_description or not task_description.strip():
            return ""

        max_chars = max_tokens * CHARS_PER_TOKEN_ESTIMATE
        results = self.search(task_description, agent_id=agent_id, limit=10)

        if not results:
            return ""

        sections = []
        current_length = 0
        header = "## Relevant Memory Context\n\n"

        for mem in results:
            layer_tag = mem.get("layer", "session").upper()
            content = mem.get("content", "")
            score = mem.get("score", 0.0)
            mem_id = mem.get("id", "?")

            entry = f"[{layer_tag}] (relevance: {score:.2f}, id: {mem_id})\n{content}\n\n"

            # Check if adding this entry would exceed the budget
            entry_len = len(entry.encode("utf-8"))
            if current_length + entry_len > max_chars:
                remaining = max_chars - current_length
                if remaining > 100:  # Only include if we can fit a meaningful chunk
                    truncated = content[: remaining - len(f"[{layer_tag}] (relevance: {score:.2f}, id: {mem_id})\n\n")]
                    sections.append(f"[{layer_tag}] (relevance: {score:.2f})\n{truncated}...\n")
                break

            sections.append(entry)
            current_length += entry_len

        if not sections:
            return ""

        return header + "".join(sections)

    # ── Learning Extraction ───────────────────────────────────────

    def extract_learnings(
        self,
        task_description: str,
        outcome: str,
        success: bool,
        duration_ms: int,
    ) -> List[str]:
        """Extract key learnings from a completed task and store as experience memories.

        Automatically generates learning entries from the task outcome and
        stores them at the experience layer for future retrieval.

        Args:
            task_description: What the task was.
            outcome: The result or output of the task.
            success: Whether the task succeeded.
            duration_ms: How long the task took in milliseconds.

        Returns:
            List of memory IDs for the stored learnings.
        """
        if not task_description or not task_description.strip():
            logger.warning("extract_learnings called with empty task_description, skipping")
            return []

        learnings = []
        metadata_base = {
            "source_task": task_description[:200],
            "success": success,
            "duration_ms": duration_ms,
            "extracted_at": time.time(),
        }

        # Generate structured learning entries
        if success:
            learnings.append(
                f"[SUCCESS] Task: {task_description}\n"
                f"Outcome: {outcome[:300]}\n"
                f"Duration: {duration_ms}ms"
            )
            # Extract a concise pattern if outcome is substantial
            if len(outcome) > 50:
                learnings.append(
                    f"[PATTERN] When performing '{task_description[:100]}', "
                    f"a successful approach is: {outcome[:200]}"
                )
        else:
            learnings.append(
                f"[FAILURE] Task: {task_description}\n"
                f"Outcome: {outcome[:300]}\n"
                f"Duration: {duration_ms}ms"
            )
            learnings.append(
                f"[LESSON] Avoid when performing '{task_description[:100]}': "
                f"{outcome[:200]}"
            )

        stored_ids = []
        for learning in learnings:
            try:
                mem_id = self.store(
                    agent_id="system",
                    content=learning,
                    metadata=metadata_base,
                    layer="experience",
                )
                stored_ids.append(mem_id)
            except Exception as e:
                logger.error("Failed to store extracted learning: %s", e)

        logger.info(
            "Extracted %d learnings from task (success=%s): %s",
            len(stored_ids), success, task_description[:80],
        )
        return stored_ids

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics.

        Returns:
            Dict with keys: ``total``, ``session``, ``project``,
            ``experience``, ``wisdom``, ``agent_count``, ``backend``.
        """
        try:
            if self._using_local:
                return self._local.get_stats()
            else:
                all_mems = self.get_all()
                layer_counts = {"session": 0, "project": 0, "experience": 0, "wisdom": 0}
                agents = set()
                for mem in all_mems:
                    layer = mem.get("layer", "session")
                    if layer in layer_counts:
                        layer_counts[layer] += 1
                    agent_id = mem.get("metadata", {}).get("agent_id")
                    if agent_id:
                        agents.add(agent_id)

                return {
                    "total": sum(layer_counts.values()),
                    **layer_counts,
                    "agent_count": len(agents),
                    "backend": "mem0",
                }
        except Exception as e:
            logger.error("Failed to get stats: %s", e)
            return {
                "total": 0,
                "session": 0,
                "project": 0,
                "experience": 0,
                "wisdom": 0,
                "agent_count": 0,
                "backend": "unknown",
                "error": str(e),
            }
