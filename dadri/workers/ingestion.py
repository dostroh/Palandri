from __future__ import annotations

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from dadri.connectors.base import BaseConnector
from dadri.storage.repository import bulk_upsert_batch


async def run_backfill(
    connector: BaseConnector,
    database: AsyncIOMotorDatabase,
    *,
    start: datetime,
    end: datetime | None = None,
    posts_collection: str = "realdata1",
    **kwargs: object,
) -> int:
    """Consume a connector's historical batches and return posts persisted."""
    persisted = 0
    async for batch in connector.fetch_backfill(start=start, end=end, **kwargs):
        await bulk_upsert_batch(database, batch, posts_collection=posts_collection)
        persisted += len(batch.posts)
    return persisted


async def run_stream(
    connector: BaseConnector,
    database: AsyncIOMotorDatabase,
    *,
    posts_collection: str = "realdata1",
    **kwargs: object,
) -> None:
    """Consume a connector until the task is cancelled."""
    async for batch in connector.fetch_stream(**kwargs):
        await bulk_upsert_batch(database, batch, posts_collection=posts_collection)
        if batch.posts:
            print(
                f"Stored {len(batch.posts)} post(s): "
                f"{', '.join(post.post_id for post in batch.posts)}",
                flush=True,
            )
