from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

from dadri.schemas.events import Author, InteractionEdge, Post


@dataclass(slots=True)
class ConnectorBatch:
    posts: list[Post] = field(default_factory=list)
    authors: list[Author] = field(default_factory=list)
    edges: list[InteractionEdge] = field(default_factory=list)


class BaseConnector(ABC):
    """Provider adapter contract; ingestion and persistence stay provider-agnostic."""

    platform: str

    @abstractmethod
    async def fetch_stream(self, **kwargs: object) -> AsyncIterator[ConnectorBatch]:
        """Yield batches as the provider produces new events."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_backfill(
        self, *, start: datetime, end: datetime | None = None, **kwargs: object
    ) -> AsyncIterator[ConnectorBatch]:
        """Yield historical batches in chronological provider order."""
        raise NotImplementedError
