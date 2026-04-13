from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nexus_os.bridge.mem0_adapter as mem0_adapter
from nexus_os.bridge import (
    Mem0BridgeAdapter,
    Mem0MCPTransport,
    Mem0SDKTransport,
    MissingMem0DependencyError,
    add_after_response,
    search_before_generation,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "query": query,
            "limit": limit,
            "metadata": dict(metadata) if metadata is not None else None,
        }
        self.calls.append(("search", payload))
        return {"kind": "search", "payload": payload}

    def add(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "messages": messages,
            "metadata": dict(metadata) if metadata is not None else None,
        }
        self.calls.append(("add", payload))
        return {"kind": "add", "payload": payload}


def test_module_imports_without_mem0_sdk() -> None:
    module = importlib.import_module("nexus_os.bridge.mem0_adapter")
    assert hasattr(module, "Mem0BridgeAdapter")


def test_search_before_generation_requires_user_id_and_passes_metadata() -> None:
    transport = RecordingTransport()
    adapter = Mem0BridgeAdapter(transport)

    result = adapter.search_before_generation(
        user_id="user-123",
        query="project context",
        limit=3,
        metadata={"workspace": "nexus"},
    )

    assert result["kind"] == "search"
    assert transport.calls == [
        (
            "search",
            {
                "user_id": "user-123",
                "query": "project context",
                "limit": 3,
                "metadata": {"workspace": "nexus"},
            },
        )
    ]

    with pytest.raises(ValueError, match="user_id is required"):
        adapter.search_before_generation(user_id="", query="missing scope")


def test_add_after_response_requires_user_id_and_passes_metadata() -> None:
    transport = RecordingTransport()
    adapter = Mem0BridgeAdapter(transport)
    messages = [{"role": "assistant", "content": "Final answer"}]

    result = add_after_response(
        adapter,
        user_id="user-456",
        messages=messages,
        metadata={"channel": "cli"},
    )

    assert result["kind"] == "add"
    assert transport.calls == [
        (
            "add",
            {
                "user_id": "user-456",
                "messages": messages,
                "metadata": {"channel": "cli"},
            },
        )
    ]

    with pytest.raises(ValueError, match="user_id is required"):
        adapter.add_after_response(user_id="  ", messages="missing scope")


def test_adapter_remains_stateless_across_operations() -> None:
    transport = RecordingTransport()
    adapter = Mem0BridgeAdapter(transport)
    initial_state = dict(adapter.__dict__)

    search_before_generation(adapter, user_id="user-1", query="history")
    adapter.add(user_id="user-1", messages="response", metadata={"kind": "summary"})

    assert adapter.__dict__ == initial_state
    assert list(adapter.__dict__) == ["_transport"]


def test_mcp_transport_uses_injected_tool_boundary() -> None:
    recorded_calls: list[tuple[str, dict[str, Any]]] = []

    def tool_call(tool_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        recorded_calls.append((tool_name, dict(payload)))
        return {"tool_name": tool_name, "payload": dict(payload)}

    transport = Mem0MCPTransport(tool_call)

    search_result = transport.search(
        user_id="user-77",
        query="governor policy",
        limit=5,
        metadata={"tenant": "alpha"},
    )
    add_result = transport.add(
        user_id="user-77",
        messages="assistant response",
        metadata={"tenant": "alpha"},
    )

    assert search_result["tool_name"] == "search_memories"
    assert add_result["tool_name"] == "add_memories"
    assert recorded_calls == [
        (
            "search_memories",
            {
                "user_id": "user-77",
                "query": "governor policy",
                "limit": 5,
                "filters": {"tenant": "alpha"},
            },
        ),
        (
            "add_memories",
            {
                "user_id": "user-77",
                "messages": "assistant response",
                "metadata": {"tenant": "alpha"},
            },
        ),
    ]


def test_sdk_transport_raises_clear_error_only_when_instantiated(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing() -> type[Any]:
        raise MissingMem0DependencyError("Mem0 SDK is not installed for tests")

    monkeypatch.setattr(mem0_adapter, "_load_mem0_memory_class", raise_missing)

    with pytest.raises(MissingMem0DependencyError, match="not installed"):
        Mem0SDKTransport()


def test_public_surface_has_no_policy_or_auth_parameters() -> None:
    forbidden_fragments = ("auth", "policy", "token", "secret", "credential")
    callables = [
        Mem0BridgeAdapter.__init__,
        Mem0BridgeAdapter.from_mcp,
        Mem0BridgeAdapter.from_sdk,
        Mem0BridgeAdapter.search,
        Mem0BridgeAdapter.add,
        Mem0BridgeAdapter.search_before_generation,
        Mem0BridgeAdapter.add_after_response,
        search_before_generation,
        add_after_response,
    ]

    for callable_obj in callables:
        for parameter_name in inspect.signature(callable_obj).parameters:
            lowered = parameter_name.lower()
            assert not any(fragment in lowered for fragment in forbidden_fragments)
