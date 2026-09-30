"""Abstract BaseTool class and shared tool utilities."""
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable
from ..models.tools import ToolCategory, ToolManifest

class BaseTool(ABC):
    """Abstract base for all domain tools."""
    manifest: ToolManifest

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def executor_fn(self) -> Callable[..., Awaitable[Any]]:
        return self.execute

def tool_manifest(*,
                 name: str,
                 description: str,
                 category: ToolCategory,
                 params: dict,
                 supports_cancellation: bool = True,
                 timeout: float = 30.0,
                 idempotency: bool = False) -> ToolManifest:
    return ToolManifest(
        name=name,
        description=description,
        category=category,
        parameters_schema=params,
        supports_cancellation=supports_cancellation,
        timeout_seconds=timeout,
        idempotency_required=idempotency,
    )
