from __future__ import annotations

from collections.abc import Sequence

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from dadri.connectors.base import ConnectorBatch
from dadri.schemas.events import Author, InteractionEdge, Post


def _document(event: Post | Author | InteractionEdge) -> dict:
    if isinstance(event, Post):
        payload = event.metadata.get("json_payload")
        if isinstance(payload, dict):
            return payload
    return event.model_dump(mode="python")


def _event_id(event: Post | Author | InteractionEdge) -> str:
    if isinstance(event, Post):
        return event.post_id
    if isinstance(event, Author):
        return event.author_id
    return f"{event.post_id}:{event.edge_type}:{event.source_author_id}:{event.target_author_id}"


async def _upsert_collection(
    database: AsyncIOMotorDatabase,
    collection: str,
    events: Sequence[Post | Author | InteractionEdge],
) -> None:
    if not events:
        return
    operations = [
        UpdateOne({"_id": _event_id(event)}, {"$set": _document(event)}, upsert=True)
        for event in events
    ]
    await database[collection].bulk_write(operations, ordered=False)


async def bulk_upsert(
    database: AsyncIOMotorDatabase,
    *,
    posts: Sequence[Post] = (),
    authors: Sequence[Author] = (),
    edges: Sequence[InteractionEdge] = (),
    posts_collection: str = "realdata1",
) -> None:
    """Bulk upsert one normalized batch into MongoDB."""
    await _upsert_collection(database, posts_collection, posts)
    await _upsert_collection(database, "authors", authors)
    await _upsert_collection(database, "interaction_edges", edges)


async def bulk_upsert_batch(
    database: AsyncIOMotorDatabase,
    batch: ConnectorBatch,
    *,
    posts_collection: str = "realdata1",
) -> None:
    await bulk_upsert(
        database,
        posts=batch.posts,
        authors=batch.authors,
        edges=batch.edges,
        posts_collection=posts_collection,
    )
