from __future__ import annotations

import asyncio
import os

from telethon import TelegramClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from dadri.connectors.telegram import TelegramConnector
from dadri.storage.database import create_mongo_client, ensure_indexes, get_database
from dadri.workers.ingestion import run_stream


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Set {name} before starting the Telegram poller")
    return value


async def main() -> None:
    telegram_api_id = int(_required("TELEGRAM_API_ID"))
    telegram_api_hash = _required("TELEGRAM_API_HASH")
    entity = _required("TELEGRAM_ENTITY")
    session = os.environ.get("TELEGRAM_SESSION", ".data/telegram")
    poll_interval = float(os.environ.get("TELEGRAM_POLL_INTERVAL", "5"))
    max_polls = int(os.environ.get("TELEGRAM_MAX_POLLS", "100"))
    database_name = os.environ.get("MONGODB_DATABASE", "apitoprocessing")
    posts_collection = os.environ.get("MONGODB_POSTS_COLLECTION", "realdata1")

    mongo_client = create_mongo_client(_required("MONGODB_URI"))
    database = get_database(mongo_client, database_name)
    await ensure_indexes(database, posts_collection=posts_collection)
    telegram_client = TelegramClient(session, telegram_api_id, telegram_api_hash)
    await telegram_client.start(bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"))
    connector = TelegramConnector(
        client=telegram_client,
        entity=entity,
        poll_interval=poll_interval,
        language=os.environ.get("TELEGRAM_LANGUAGE"),
    )
    try:
        print(
            f"Polling Telegram entity {entity} every {poll_interval:g}s "
            f"({max_polls} polls), writing to {database_name}.{posts_collection}",
            flush=True,
        )
        await run_stream(
            connector,
            database,
            posts_collection=posts_collection,
            entity=entity,
            max_polls=max_polls,
        )
        print(f"Completed {max_polls} Telegram poll(s)", flush=True)
    finally:
        await telegram_client.disconnect()
        mongo_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Telegram poller stopped")
    except OperationFailure as exc:
        if exc.code == 8000 or "Authentication failed" in str(exc):
            raise SystemExit("MongoDB authentication failed; check MONGODB_URI") from exc
        raise
    except ServerSelectionTimeoutError as exc:
        raise SystemExit("MongoDB connection failed; check Atlas network access") from exc
