from __future__ import annotations

import asyncio
import os

from dadri.storage.database import create_mongo_client, get_database


async def main() -> None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("Set MONGODB_URI before checking MongoDB")
    client = create_mongo_client(uri, serverSelectionTimeoutMS=10_000)
    try:
        database = get_database(client, os.environ.get("MONGODB_DATABASE", "apiprocessing"))
        await client.admin.command("ping")
        posts = database[os.environ.get("MONGODB_POSTS_COLLECTION", "realdata1")]
        count = await posts.count_documents({})
        authors = await database.authors.count_documents({})
        edges = await database.interaction_edges.count_documents({})
        latest = await posts.find_one({}, sort=[("created_at", -1)])
        print(f"MongoDB connection: ok")
        print(f"posts={count} authors={authors} interaction_edges={edges}")
        if latest:
            print(f"latest_post_id={latest['post_id']}")
            print(f"latest_created_at={latest['created_at'].isoformat()}")
            print(f"latest_text={latest['content']}")
        else:
            print("No posts stored yet")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
