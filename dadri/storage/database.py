from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel


def create_mongo_client(uri: str, **kwargs: object) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(uri, **kwargs)


def get_database(client: AsyncIOMotorClient, name: str) -> AsyncIOMotorDatabase:
    return client[name]


async def ensure_indexes(
    database: AsyncIOMotorDatabase,
    *,
    posts_collection: str = "realdata1",
) -> None:
    await database[posts_collection].create_indexes([
        IndexModel([("created_at", ASCENDING), ("post_id", ASCENDING)], name="created_at_post_id"),
        IndexModel([("parent_post_id", ASCENDING)], name="parent_post_id"),
        IndexModel([("root_post_id", ASCENDING), ("created_at", ASCENDING)], name="root_created_at"),
        IndexModel([("author_id", ASCENDING), ("created_at", ASCENDING)], name="author_created_at"),
    ])
    await database.authors.create_index(
        [("platform", ASCENDING), ("username", ASCENDING)], name="platform_username"
    )
    await database.interaction_edges.create_indexes([
        IndexModel([("source_author_id", ASCENDING), ("timestamp", ASCENDING)], name="source_timestamp"),
        IndexModel([("target_author_id", ASCENDING), ("timestamp", ASCENDING)], name="target_timestamp"),
        IndexModel([("timestamp", ASCENDING)], name="timestamp"),
    ])
