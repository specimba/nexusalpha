"""Stateless Mem0 bridge adapter for Nexus OS."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


class MissingMem0DependencyError(RuntimeError):
    """Raised when the optional Mem0 SDK is required but unavailable."""


def _require_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required for all memory operations")
    return user_id


def _copy_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    return dict(metadata)


@runtime_checkable
class Mem0Transport(Protocol):
    """Transport boundary for external memory operations."""

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Search for memories scoped to a single user."""

    def add(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Add memories scoped to a single user."""


class Mem0MCPTransport:
    """Generic MCP transport backed by an injected tool caller."""

    def __init__(
        self,
        tool_call: Callable[[str, Mapping[str, Any]], Any],
        *,
        search_tool: str = "search_memories",
        add_tool: str = "add_memories",
    ) -> None:
        self._tool_call = tool_call
        self._search_tool = search_tool
        self._add_tool = add_tool

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "user_id": _require_user_id(user_id),
            "query": query,
        }
        if limit is not None:
            payload["limit"] = limit
        if metadata is not None:
            payload["filters"] = _copy_metadata(metadata)
        return self._tool_call(self._search_tool, payload)

    def add(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "user_id": _require_user_id(user_id),
            "messages": messages,
        }
        if metadata is not None:
            payload["metadata"] = _copy_metadata(metadata)
        return self._tool_call(self._add_tool, payload)


def _load_mem0_memory_class() -> type[Any]:
    try:
        from mem0 import Memory
    except ModuleNotFoundError as exc:
        raise MissingMem0DependencyError(
            "Mem0 SDK is not installed. Inject a transport or install `mem0ai` "
            "before using the SDK fallback."
        ) from exc
    return Memory


class Mem0SDKTransport:
    """Thin wrapper around the optional Mem0 SDK."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        config: Mapping[str, Any] | None = None,
        memory_class: type[Any] | None = None,
    ) -> None:
        self._client = client if client is not None else self._build_client(config, memory_class)

    @staticmethod
    def _build_client(
        config: Mapping[str, Any] | None,
        memory_class: type[Any] | None,
    ) -> Any:
        memory_factory = memory_class or _load_mem0_memory_class()
        if config is None:
            return memory_factory()

        config_copy = dict(config)
        from_config = getattr(memory_factory, "from_config", None)
        if callable(from_config):
            return from_config(config_copy)

        try:
            return memory_factory(config=config_copy)
        except TypeError:
            return memory_factory(**config_copy)

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "user_id": _require_user_id(user_id),
            "query": query,
        }
        if limit is not None:
            kwargs["limit"] = limit
        if metadata is not None:
            kwargs["filters"] = _copy_metadata(metadata)
        return self._invoke("search", "search_memories", **kwargs)

    def add(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "user_id": _require_user_id(user_id),
            "messages": messages,
        }
        if metadata is not None:
            kwargs["metadata"] = _copy_metadata(metadata)
        return self._invoke("add", "add_memories", **kwargs)

    def _invoke(self, *method_names: str, **kwargs: Any) -> Any:
        for method_name in method_names:
            method = getattr(self._client, method_name, None)
            if callable(method):
                return method(**kwargs)
        raise AttributeError(
            "Mem0 client does not expose a supported method. "
            f"Tried: {', '.join(method_names)}"
        )


class Mem0BridgeAdapter:
    """Framework-agnostic bridge adapter for Mem0-style memory operations."""

    def __init__(self, transport: Mem0Transport) -> None:
        self._transport = transport

    @classmethod
    def from_mcp(
        cls,
        tool_call: Callable[[str, Mapping[str, Any]], Any],
        *,
        search_tool: str = "search_memories",
        add_tool: str = "add_memories",
    ) -> Mem0BridgeAdapter:
        return cls(
            Mem0MCPTransport(
                tool_call,
                search_tool=search_tool,
                add_tool=add_tool,
            )
        )

    @classmethod
    def from_sdk(
        cls,
        client: Any | None = None,
        *,
        config: Mapping[str, Any] | None = None,
        memory_class: type[Any] | None = None,
    ) -> Mem0BridgeAdapter:
        return cls(
            Mem0SDKTransport(
                client=client,
                config=config,
                memory_class=memory_class,
            )
        )

    def search(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._transport.search(
            user_id=_require_user_id(user_id),
            query=query,
            limit=limit,
            metadata=metadata,
        )

    def add(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._transport.add(
            user_id=_require_user_id(user_id),
            messages=messages,
            metadata=metadata,
        )

    def search_before_generation(
        self,
        *,
        user_id: str,
        query: str,
        limit: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.search(
            user_id=user_id,
            query=query,
            limit=limit,
            metadata=metadata,
        )

    def add_after_response(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, Any]] | str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.add(
            user_id=user_id,
            messages=messages,
            metadata=metadata,
        )


def search_before_generation(
    adapter: Mem0BridgeAdapter,
    *,
    user_id: str,
    query: str,
    limit: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    return adapter.search_before_generation(
        user_id=user_id,
        query=query,
        limit=limit,
        metadata=metadata,
    )


def add_after_response(
    adapter: Mem0BridgeAdapter,
    *,
    user_id: str,
    messages: Sequence[Mapping[str, Any]] | str,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    return adapter.add_after_response(
        user_id=user_id,
        messages=messages,
        metadata=metadata,
    )
