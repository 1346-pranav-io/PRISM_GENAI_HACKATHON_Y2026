"""Tool registry abstract interface."""

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, List, Optional
from ..models.tools import ToolManifest


class IToolRegistry(ABC):
    @abstractmethod
    def register_tool(
        self,
        manifest: ToolManifest,
        executor_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        """Register a tool with manifest and async callable handler."""
        pass

    @abstractmethod
    def get_manifest(self, name: str) -> Optional[ToolManifest]:
        """Retrieve manifest by tool name."""
        pass

    @abstractmethod
    def get_manifests(self) -> List[ToolManifest]:
        """List all registered tool manifests."""
        pass

    @abstractmethod
    def get_executor(self, name: str) -> Optional[Callable[..., Awaitable[Any]]]:
        """Retrieve executor function by tool name."""
        pass
