from __future__ import annotations

import asyncio
import os

from pymongo.errors import OperationFailure, ServerSelectionTimeoutError
from telethon import TelegramClient

from dadri.connectors.telegram import TelegramConnector
from dadri.connectors.x_twitter import XConnector
from dadri.storage.database import create_mongo_client, ensure_indexes, get_database
from dadri.workers.ingestion import run_stream


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Set {name} before starting the combined poller")
    return value


def _items(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _x_query(topics: list[str]) -> str:
    if not topics:
        return "-filter:retweets"
    clauses = [topic if any(char in topic for char in '"():') else f'"{topic}"' for topic in topics]
    return f"({' OR '.join(clauses)}) -filter:retweets"


def _with_x_language(query: str, language: str | None) -> str:
    return f"{query} lang:{language}" if language else query


async def main() -> None:
    database_name = os.environ.get("MONGODB_DATABASE", "apitoprocessing")
    posts_collection = os.environ.get("MONGODB_POSTS_COLLECTION", "realdata1")
    poll_interval = float(os.environ.get("X_POLL_INTERVAL", "5"))
    telegram_interval = float(os.environ.get("TELEGRAM_POLL_INTERVAL", str(poll_interval)))
    max_polls = int(os.environ.get("X_MAX_POLLS", "100"))
    telegram_max_polls = int(os.environ.get("TELEGRAM_MAX_POLLS", str(max_polls)))
    results_per_poll = int(os.environ.get("X_RESULTS_PER_POLL", "1"))
    x_language = os.environ.get("X_LANGUAGE")
    telegram_language = os.environ.get("TELEGRAM_LANGUAGE")
    topics = _items("X_TOPICS")
    x_query = _with_x_language(
        _x_query(topics) if topics else os.environ.get("X_QUERY", "-filter:retweets"),
        x_language,
    )
    telegram_entities = _items("TELEGRAM_ENTITIES")
    if not telegram_entities:
        raise RuntimeError("Set TELEGRAM_ENTITIES to comma-separated channels or groups")

    mongo_client = create_mongo_client(_required("MONGODB_URI"))
    database = get_database(mongo_client, database_name)
    await ensure_indexes(database, posts_collection=posts_collection)

    api_id = int(_required("TELEGRAM_API_ID"))
    api_hash = _required("TELEGRAM_API_HASH")
    telegram_session = os.environ.get("TELEGRAM_SESSION", ".data/telegram")
    telegram_client = TelegramClient(telegram_session, api_id, api_hash)
    await telegram_client.start(bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"))

    x_connector = XConnector(
        username=os.environ.get("X_USERNAME"),
        email=os.environ.get("X_EMAIL"),
        password=os.environ.get("X_PASSWORD"),
        email_password=os.environ.get("X_EMAIL_PASSWORD"),
        poll_interval=poll_interval,
        cookies_file=os.environ.get("X_COOKIES_FILE", ".data/x_cookies.json"),
    )

    async def run_x() -> None:
        print(f"X topics: {x_query}", flush=True)
        await run_stream(
            x_connector,
            database,
            posts_collection=posts_collection,
            query=x_query,
            max_polls=max_polls,
            limit=results_per_poll,
        )

    async def run_telegram_entity(entity: str) -> None:
        connector = TelegramConnector(
            client=telegram_client,
            entity=entity,
            poll_interval=telegram_interval,
            language=telegram_language,
        )
        print(f"Telegram entity: {entity}", flush=True)
        await run_stream(
            connector,
            database,
            posts_collection=posts_collection,
            entity=entity,
            max_polls=telegram_max_polls,
        )

    tasks = [asyncio.create_task(run_x(), name="x-poller")]
    tasks.extend(
        asyncio.create_task(run_telegram_entity(entity), name=f"telegram:{entity}")
        for entity in telegram_entities
    )
    print(
        f"Running {len(tasks)} pollers concurrently; writing to "
        f"{database_name}.{posts_collection}",
        flush=True,
    )
    try:
        await asyncio.gather(*tasks)
    finally:
        await telegram_client.disconnect()
        mongo_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Combined poller stopped")
    except OperationFailure as exc:
        if exc.code == 8000 or "Authentication failed" in str(exc):
            raise SystemExit("MongoDB authentication failed; check MONGODB_URI") from exc
        raise
    except ServerSelectionTimeoutError as exc:
        raise SystemExit("MongoDB connection failed; check Atlas network access") from exc
