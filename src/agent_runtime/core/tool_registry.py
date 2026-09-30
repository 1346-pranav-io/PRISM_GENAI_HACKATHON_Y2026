"""In-memory tool registry."""

from typing import Any, Awaitable, Callable, Dict, List, Optional
from ..interfaces.tool_registry import IToolRegistry
from ..models.tools import ToolManifest


class ToolRegistry(IToolRegistry):
    """Stores and resolves tools and their schema manifests."""

    def __init__(self) -> None:
        self._manifests: Dict[str, ToolManifest] = {}
        self._executors: Dict[str, Callable[..., Awaitable[Any]]] = {}

    def register_tool(
        self,
        manifest: ToolManifest,
        executor_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        """Register a tool with manifest and async callable handler."""
        self._manifests[manifest.name] = manifest
        self._executors[manifest.name] = executor_fn

    def get_manifest(self, name: str) -> Optional[ToolManifest]:
        """Retrieve manifest by tool name."""
        return self._manifests.get(name)

    def get_manifests(self) -> List[ToolManifest]:
        """List all registered tool manifests."""
        return list(self._manifests.values())

    def get_executor(self, name: str) -> Optional[Callable[..., Awaitable[Any]]]:
        """Retrieve executor function by tool name."""
        return self._executors.get(name)
