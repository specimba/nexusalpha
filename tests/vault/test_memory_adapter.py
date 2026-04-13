"""
tests/vault/test_memory_adapter.py — Mem0Adapter Tests

Tests the mem0 memory adapter with local fallback backend:
  - Initialization with forced local mode
  - Store with layer classification and metadata
  - Keyword search (local backend)
  - Get all with agent/layer filtering
  - Delete memory
  - Promotion: session → experience → wisdom
  - Context retrieval for task injection
  - Learning extraction from completed tasks
  - Stats aggregation
  - Error handling (invalid layer, empty content)
  - LocalBackend TTL expiry
  - Persistence across adapter instances
"""

import json
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from nexus_os.vault.memory_adapter import Mem0Adapter, _LocalMemoryBackend, VALID_LAYERS


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_json(tmp_path):
    """Provide a temp file path for local backend storage."""
    return str(tmp_path / "mem0_test.json")


@pytest.fixture
def local_backend(tmp_json):
    """Create a fresh _LocalMemoryBackend for each test."""
    backend = _LocalMemoryBackend(storage_path=tmp_json)
    yield backend


@pytest.fixture
def adapter(tmp_json):
    """Create a Mem0Adapter forced to local mode with temp storage."""
    return Mem0Adapter(config={"force_local": True, "storage_path": tmp_json})


# ── LocalMemoryBackend Tests ───────────────────────────────────────────────────

class TestLocalMemoryBackend:
    """Tests for the _LocalMemoryBackend fallback."""

    def test_add_returns_id(self, local_backend):
        """add() should return a non-empty string ID."""
        mid = local_backend.add(content="Test memory", agent_id="agent_1")
        assert isinstance(mid, str)
        assert len(mid) >= 8

    def test_add_stores_content(self, local_backend):
        """add() should persist the content for later retrieval."""
        mid = local_backend.add(content="Hello world", agent_id="agent_1")
        mem = local_backend.get(mid)
        assert mem is not None
        assert mem["content"] == "Hello world"
        assert mem["agent_id"] == "agent_1"

    def test_add_defaults_to_session_layer(self, local_backend):
        """Default layer should be session."""
        mid = local_backend.add(content="Default layer test")
        mem = local_backend.get(mid)
        assert mem["layer"] == "session"

    def test_add_with_custom_layer(self, local_backend):
        """Custom layer should be stored correctly."""
        mid = local_backend.add(content="Wisdom content", layer="wisdom")
        mem = local_backend.get(mid)
        assert mem["layer"] == "wisdom"

    def test_add_with_metadata(self, local_backend):
        """Metadata should be stored alongside the memory."""
        meta = {"source": "test", "tags": ["unit"]}
        mid = local_backend.add(content="Meta test", metadata=meta)
        mem = local_backend.get(mid)
        assert mem["metadata"]["source"] == "test"
        assert mem["metadata"]["tags"] == ["unit"]

    def test_get_nonexistent_returns_none(self, local_backend):
        """get() with a nonexistent ID should return None."""
        assert local_backend.get("nonexistent_id") is None

    def test_delete_existing(self, local_backend):
        """delete() should remove a memory and return True."""
        mid = local_backend.add(content="Delete me")
        assert local_backend.delete(mid) is True
        assert local_backend.get(mid) is None

    def test_delete_nonexistent(self, local_backend):
        """delete() with a nonexistent ID should return False."""
        assert local_backend.delete("no_such_id") is False

    def test_search_keyword_match(self, local_backend):
        """Search should match memories by keyword overlap."""
        local_backend.add(content="The database uses PostgreSQL", agent_id="agent_1")
        local_backend.add(content="API authentication uses JWT", agent_id="agent_1")
        local_backend.add(content="Frontend built with React", agent_id="agent_2")

        results = local_backend.search("PostgreSQL database")
        assert len(results) >= 1
        assert "PostgreSQL" in results[0]["content"]
        assert "score" in results[0]
        assert results[0]["score"] > 0

    def test_search_no_match(self, local_backend):
        """Search with no matching keywords should return empty list."""
        local_backend.add(content="Completely unrelated content")
        results = local_backend.search("xyzzy plugh")
        assert results == []

    def test_search_empty_query(self, local_backend):
        """Empty query should return empty list."""
        local_backend.add(content="Some content")
        assert local_backend.search("") == []
        assert local_backend.search("   ") == []

    def test_search_agent_filter(self, local_backend):
        """Search with agent_id filter should only return that agent's memories."""
        local_backend.add(content="Agent one memory", agent_id="agent_1")
        local_backend.add(content="Agent two memory", agent_id="agent_2")
        results = local_backend.search("memory", agent_id="agent_1")
        assert len(results) == 1
        assert results[0]["agent_id"] == "agent_1"

    def test_search_layer_filter(self, local_backend):
        """Search with layer filter should only return matching layer."""
        local_backend.add(content="Session stuff", layer="session")
        local_backend.add(content="Wisdom stuff", layer="wisdom")
        results = local_backend.search("stuff", layer="wisdom")
        assert len(results) == 1
        assert results[0]["layer"] == "wisdom"

    def test_search_respects_limit(self, local_backend):
        """Search should respect the limit parameter."""
        for i in range(10):
            local_backend.add(content=f"memory about database number {i}")
        results = local_backend.search("database", limit=3)
        assert len(results) == 3

    def test_get_all_filter_by_agent(self, local_backend):
        """get_all with agent_id filter should only return that agent's memories."""
        local_backend.add(content="A1 memory", agent_id="agent_1")
        local_backend.add(content="A2 memory", agent_id="agent_2")
        local_backend.add(content="A1 another", agent_id="agent_1")
        results = local_backend.get_all(agent_id="agent_1")
        assert len(results) == 2
        assert all(r["agent_id"] == "agent_1" for r in results)

    def test_get_all_filter_by_layer(self, local_backend):
        """get_all with layer filter should only return matching layer."""
        local_backend.add(content="Session", layer="session")
        local_backend.add(content="Project", layer="project")
        local_backend.add(content="Wisdom", layer="wisdom")
        results = local_backend.get_all(layer="project")
        assert len(results) == 1
        assert results[0]["layer"] == "project"

    def test_ttl_expiry(self, local_backend):
        """Session memories should expire after TTL."""
        mid = local_backend.add(content="Short lived", layer="session")
        # Manually set expires_at to the past
        local_backend._memories[mid]["expires_at"] = time.time() - 1
        assert local_backend.get(mid) is None
        # Should also be excluded from get_all and search
        assert local_backend.get_all() == []
        assert local_backend.search("Short") == []

    def test_no_ttl_for_experience(self, local_backend):
        """Experience memories should never expire."""
        mid = local_backend.add(content="Long lived", layer="experience")
        assert local_backend._memories[mid]["expires_at"] is None

    def test_update_changes_fields(self, local_backend):
        """update() should modify memory fields."""
        mid = local_backend.add(content="Original", layer="session")
        assert local_backend.update(mid, {"content": "Updated", "layer": "project"}) is True
        mem = local_backend.get(mid)
        assert mem["content"] == "Updated"
        assert mem["layer"] == "project"

    def test_update_nonexistent(self, local_backend):
        """update() with nonexistent ID should return False."""
        assert local_backend.update("no_id", {"content": "Nope"}) is False

    def test_update_id_is_immutable(self, local_backend):
        """update() should not change the memory ID."""
        mid = local_backend.add(content="Original")
        local_backend.update(mid, {"id": "fake_id"})
        assert local_backend.get("fake_id") is None
        assert local_backend.get(mid) is not None

    def test_stats_counts(self, local_backend):
        """get_stats should return correct counts by layer."""
        local_backend.add(content="S1", agent_id="agent_a", layer="session")
        local_backend.add(content="S2", agent_id="agent_a", layer="session")
        local_backend.add(content="P1", agent_id="agent_a", layer="project")
        local_backend.add(content="E1", agent_id="agent_a", layer="experience")
        local_backend.add(content="W1", agent_id="agent_a", layer="wisdom")
        local_backend.add(content="W2", agent_id="agent_b", layer="wisdom")

        stats = local_backend.get_stats()
        assert stats["total"] == 6
        assert stats["session"] == 2
        assert stats["project"] == 1
        assert stats["experience"] == 1
        assert stats["wisdom"] == 2
        assert stats["agent_count"] == 2
        assert stats["backend"] == "local"

    def test_reset_clears_all(self, local_backend):
        """reset() should clear all memories."""
        local_backend.add(content="Memory 1")
        local_backend.add(content="Memory 2")
        local_backend.reset()
        assert local_backend.get_all() == []

    def test_persistence_across_instances(self, tmp_json):
        """Data should survive creating a new backend instance with same path."""
        backend1 = _LocalMemoryBackend(storage_path=tmp_json)
        mid = backend1.add(content="Persistent memory", agent_id="agent_p")
        del backend1

        backend2 = _LocalMemoryBackend(storage_path=tmp_json)
        mem = backend2.get(mid)
        assert mem is not None
        assert mem["content"] == "Persistent memory"


# ── Mem0Adapter Tests ──────────────────────────────────────────────────────────

class TestMem0AdapterInit:
    """Test Mem0Adapter initialization."""

    def test_init_forces_local_mode(self, tmp_json):
        """With force_local=True, adapter should use local backend."""
        adapter = Mem0Adapter(config={"force_local": True, "storage_path": tmp_json})
        assert adapter._using_local is True
        assert adapter._local is not None
        assert adapter._mem0_client is None

    def test_init_uses_local_when_mem0_unavailable(self, tmp_json):
        """Without an API key, adapter should gracefully fall back to local."""
        adapter = Mem0Adapter(config={"storage_path": tmp_json})
        # In CI/no-key environments, this should fall back
        assert adapter._using_local is True
        assert adapter._local is not None


class TestMem0AdapterStore:
    """Test memory storage through the adapter."""

    def test_store_returns_id(self, adapter):
        """store() should return a non-empty memory ID."""
        mid = adapter.store(agent_id="agent_1", content="Test content")
        assert isinstance(mid, str)
        assert len(mid) >= 1

    def test_store_default_layer(self, adapter):
        """Default layer should be session."""
        mid = adapter.store(agent_id="agent_1", content="Default layer")
        results = adapter.get_all()
        found = [r for r in results if r["id"] == mid]
        assert len(found) == 1
        assert found[0]["layer"] == "session"

    def test_store_with_layer(self, adapter):
        """Explicit layer should be stored in metadata."""
        adapter.store(agent_id="agent_1", content="Wisdom", layer="wisdom")
        results = adapter.get_all(layer="wisdom")
        assert len(results) == 1
        assert results[0]["content"] == "Wisdom"

    def test_store_with_custom_metadata(self, adapter):
        """Custom metadata should be preserved."""
        adapter.store(
            agent_id="agent_1",
            content="Custom meta",
            metadata={"source": "test", "priority": "high"},
            layer="project",
        )
        results = adapter.get_all(layer="project")
        assert len(results) == 1
        assert results[0]["metadata"]["source"] == "test"
        assert results[0]["metadata"]["priority"] == "high"

    def test_store_invalid_layer_raises(self, adapter):
        """Invalid layer should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid layer"):
            adapter.store(agent_id="agent_1", content="test", layer="invalid_layer")

    def test_store_empty_content_raises(self, adapter):
        """Empty content should raise ValueError."""
        with pytest.raises(ValueError, match="Content must not be empty"):
            adapter.store(agent_id="agent_1", content="")

    def test_store_whitespace_content_raises(self, adapter):
        """Whitespace-only content should raise ValueError."""
        with pytest.raises(ValueError, match="Content must not be empty"):
            adapter.store(agent_id="agent_1", content="   \n\t  ")


class TestMem0AdapterSearch:
    """Test semantic/keyword search through the adapter."""

    def test_search_returns_results(self, adapter):
        """Search should return matching memories with expected fields."""
        adapter.store(agent_id="agent_1", content="PostgreSQL database setup guide")
        adapter.store(agent_id="agent_1", content="JWT authentication implementation")
        results = adapter.search("PostgreSQL database")
        assert len(results) >= 1
        assert "id" in results[0]
        assert "content" in results[0]
        assert "score" in results[0]
        assert "metadata" in results[0]
        assert "layer" in results[0]

    def test_search_no_results(self, adapter):
        """Search with no matches should return empty list."""
        adapter.store(agent_id="agent_1", content="Unrelated content about cats")
        results = adapter.search("quantum physics")
        assert results == []

    def test_search_empty_query(self, adapter):
        """Empty query should return empty list."""
        adapter.store(agent_id="agent_1", content="Some content")
        assert adapter.search("") == []
        assert adapter.search(None) == []

    def test_search_with_agent_filter(self, adapter):
        """Search should respect agent_id filter."""
        adapter.store(agent_id="alpha", content="Alpha's secret recipe")
        adapter.store(agent_id="beta", content="Beta's database config")
        results = adapter.search("secret", agent_id="alpha")
        assert len(results) == 1
        assert results[0]["content"] == "Alpha's secret recipe"

    def test_search_with_layer_filter(self, adapter):
        """Search should respect layer filter."""
        adapter.store(agent_id="agent_1", content="Session note", layer="session")
        adapter.store(agent_id="agent_1", content="Wisdom note", layer="wisdom")
        results = adapter.search("note", layer="wisdom")
        assert len(results) == 1
        assert results[0]["layer"] == "wisdom"


class TestMem0AdapterGetAll:
    """Test get_all retrieval through the adapter."""

    def test_get_all_returns_stored_memories(self, adapter):
        """get_all should return all stored memories."""
        adapter.store(agent_id="agent_1", content="Memory A")
        adapter.store(agent_id="agent_1", content="Memory B")
        adapter.store(agent_id="agent_2", content="Memory C")
        results = adapter.get_all()
        assert len(results) == 3

    def test_get_all_filter_agent(self, adapter):
        """get_all with agent_id should only return that agent's memories."""
        adapter.store(agent_id="agent_1", content="A1")
        adapter.store(agent_id="agent_2", content="A2")
        results = adapter.get_all(agent_id="agent_1")
        assert len(results) == 1

    def test_get_all_filter_layer(self, adapter):
        """get_all with layer should only return matching memories."""
        adapter.store(agent_id="agent_1", content="S", layer="session")
        adapter.store(agent_id="agent_1", content="E", layer="experience")
        results = adapter.get_all(layer="experience")
        assert len(results) == 1
        assert results[0]["content"] == "E"

    def test_get_all_empty(self, adapter):
        """get_all with no memories should return empty list."""
        assert adapter.get_all() == []


class TestMem0AdapterDelete:
    """Test memory deletion through the adapter."""

    def test_delete_existing(self, adapter):
        """delete() should remove the memory and return True."""
        mid = adapter.store(agent_id="agent_1", content="Delete me")
        assert adapter.delete(mid) is True
        assert adapter.get_all() == []

    def test_delete_nonexistent(self, adapter):
        """delete() with nonexistent ID should return False."""
        assert adapter.delete("no_such_id") is False

    def test_delete_empty_id(self, adapter):
        """delete() with empty ID should return False."""
        assert adapter.delete("") is False
        assert adapter.delete(None) is False


class TestMem0AdapterPromotion:
    """Test memory layer promotion through the adapter."""

    def test_promote_session_to_experience(self, adapter):
        """A session memory should be promotable to experience."""
        mid = adapter.store(agent_id="agent_1", content="Promote me", layer="session")
        assert adapter.promote_to_experience(mid) is True
        results = adapter.get_all(layer="experience")
        assert len(results) == 1
        assert results[0]["id"] == mid

    def test_promote_project_to_experience(self, adapter):
        """A project memory should be promotable to experience."""
        mid = adapter.store(agent_id="agent_1", content="Project insight", layer="project")
        assert adapter.promote_to_experience(mid) is True
        results = adapter.get_all(layer="experience")
        assert len(results) == 1

    def test_promote_experience_to_wisdom(self, adapter):
        """An experience memory should be promotable to wisdom."""
        mid = adapter.store(agent_id="agent_1", content="Deep insight", layer="experience")
        assert adapter.promote_to_wisdom(mid) is True
        results = adapter.get_all(layer="wisdom")
        assert len(results) == 1

    def test_cannot_promote_session_to_wisdom(self, adapter):
        """Session memory should not be promotable directly to wisdom."""
        mid = adapter.store(agent_id="agent_1", content="Too fast", layer="session")
        with pytest.raises(ValueError, match="Only experience memories"):
            adapter.promote_to_wisdom(mid)

    def test_cannot_promote_wisdom_to_experience(self, adapter):
        """Wisdom memory should not be promotable (already highest)."""
        mid = adapter.store(agent_id="agent_1", content="Already wise", layer="wisdom")
        with pytest.raises(ValueError, match="Already at layer"):
            adapter.promote_to_experience(mid)

    def test_promote_nonexistent_returns_false(self, adapter):
        """Promoting a nonexistent memory should return False."""
        assert adapter.promote_to_experience("no_id") is False
        assert adapter.promote_to_wisdom("no_id") is False


class TestMem0AdapterContext:
    """Test context retrieval for task injection."""

    def test_get_context_for_task(self, adapter):
        """get_context_for_task should return formatted relevant context."""
        adapter.store(agent_id="agent_1", content="Encryption uses AES-256-GCM for data at rest")
        adapter.store(agent_id="agent_1", content="Authentication requires JWT with RS256")

        context = adapter.get_context_for_task("Set up encryption for the database")
        assert isinstance(context, str)
        assert len(context) > 0
        assert "## Relevant Memory Context" in context
        assert "AES-256-GCM" in context

    def test_get_context_empty_task(self, adapter):
        """Empty task description should return empty string."""
        adapter.store(agent_id="agent_1", content="Some memory")
        assert adapter.get_context_for_task("") == ""
        assert adapter.get_context_for_task(None) == ""

    def test_get_context_no_memories(self, adapter):
        """No stored memories should return empty context."""
        context = adapter.get_context_for_task("Do something")
        assert context == ""

    def test_get_context_respects_token_budget(self, adapter):
        """Context should fit within the approximate token budget."""
        # Store many long memories
        for i in range(20):
            adapter.store(
                agent_id="agent_1",
                content=f"Memory number {i}: " + "word " * 200,  # ~800 chars each
            )

        # Request a very small budget
        context = adapter.get_context_for_task("memory", max_tokens=50)
        # 50 tokens ≈ 200 chars, so context should be short
        assert len(context) < 500

    def test_get_context_for_specific_agent(self, adapter):
        """Context should be scoped to the specified agent."""
        adapter.store(agent_id="alpha", content="Alpha's encryption knowledge")
        adapter.store(agent_id="beta", content="Beta's frontend knowledge")

        context = adapter.get_context_for_task("encryption", agent_id="alpha")
        assert "Alpha" in context
        assert "Beta" not in context


class TestMem0AdapterLearnings:
    """Test learning extraction from completed tasks."""

    def test_extract_success_learnings(self, adapter):
        """Successful task should produce SUCCESS and PATTERN learnings."""
        ids = adapter.extract_learnings(
            task_description="Fix encryption fallback",
            outcome="Implemented AES-256-GCM as fallback when primary cipher fails",
            success=True,
            duration_ms=450,
        )
        assert len(ids) >= 2  # At least SUCCESS + PATTERN

        # Verify the learnings were stored as experience memories
        results = adapter.get_all(layer="experience")
        assert len(results) >= 2
        contents = [r["content"] for r in results]
        assert any("SUCCESS" in c for c in contents)
        assert any("PATTERN" in c for c in contents)

    def test_extract_failure_learnings(self, adapter):
        """Failed task should produce FAILURE and LESSON learnings."""
        ids = adapter.extract_learnings(
            task_description="Migrate to new database",
            outcome="Schema incompatibility caused data corruption during migration",
            success=False,
            duration_ms=5000,
        )
        assert len(ids) >= 2

        results = adapter.get_all(layer="experience")
        contents = [r["content"] for r in results]
        assert any("FAILURE" in c for c in contents)
        assert any("LESSON" in c for c in contents)

    def test_extract_empty_task_skips(self, adapter):
        """Empty task description should return empty list."""
        ids = adapter.extract_learnings("", "outcome", True, 100)
        assert ids == []

    def test_learnings_include_metadata(self, adapter):
        """Extracted learnings should include task metadata."""
        adapter.extract_learnings(
            task_description="Fix encryption",
            outcome="Done",
            success=True,
            duration_ms=300,
        )
        results = adapter.get_all(layer="experience")
        assert len(results) >= 1
        meta = results[0]["metadata"]
        assert meta["source_task"] == "Fix encryption"
        assert meta["success"] is True
        assert meta["duration_ms"] == 300


class TestMem0AdapterStats:
    """Test memory statistics through the adapter."""

    def test_stats_layer_counts(self, adapter):
        """Stats should reflect stored memories by layer."""
        adapter.store(agent_id="a", content="S1", layer="session")
        adapter.store(agent_id="a", content="S2", layer="session")
        adapter.store(agent_id="a", content="P1", layer="project")
        adapter.store(agent_id="b", content="E1", layer="experience")
        adapter.store(agent_id="b", content="W1", layer="wisdom")

        stats = adapter.get_stats()
        assert stats["total"] == 5
        assert stats["session"] == 2
        assert stats["project"] == 1
        assert stats["experience"] == 1
        assert stats["wisdom"] == 1
        assert stats["agent_count"] == 2
        assert stats["backend"] == "local"

    def test_stats_empty(self, adapter):
        """Stats with no memories should return all zeros."""
        stats = adapter.get_stats()
        assert stats["total"] == 0
        assert stats["session"] == 0
        assert stats["project"] == 0
        assert stats["experience"] == 0
        assert stats["wisdom"] == 0
