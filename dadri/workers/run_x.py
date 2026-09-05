from __future__ import annotations

import asyncio
import os

from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from dadri.connectors.x_twitter import XConnector
from dadri.storage.database import create_mongo_client, ensure_indexes, get_database
from dadri.workers.ingestion import run_stream


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Set {name} before starting the X poller")
    return value


async def main() -> None:
    client = create_mongo_client(_required("MONGODB_URI"))
    posts_collection = os.environ.get("MONGODB_POSTS_COLLECTION", "realdata1")
    database = get_database(client, os.environ.get("MONGODB_DATABASE", "apiprocessing"))
    await ensure_indexes(database, posts_collection=posts_collection)
    cookies_file = os.environ.get("X_COOKIES_FILE", ".data/x_cookies.json")
    connector = XConnector(
        username=os.environ.get("X_USERNAME"),
        email=os.environ.get("X_EMAIL"),
        password=os.environ.get("X_PASSWORD"),
        email_password=os.environ.get("X_EMAIL_PASSWORD"),
        poll_interval=float(os.environ.get("X_POLL_INTERVAL", "5")),
        cookies_file=cookies_file,
    )
    query = os.environ.get("X_QUERY", "-filter:retweets")
    if os.environ.get("X_LANGUAGE"):
        query = f"{query} lang:{os.environ['X_LANGUAGE']}"
    max_polls = int(os.environ.get("X_MAX_POLLS", "100"))
    results_per_poll = int(os.environ.get("X_RESULTS_PER_POLL", "1"))
    try:
        print(
            f"Polling X every {connector._poll_interval:g}s for: {query} "
            f"({max_polls} polls, up to {results_per_poll} post per poll)",
            flush=True,
        )
        await run_stream(database=database, connector=connector, query=query,
                 posts_collection=posts_collection, max_polls=max_polls,
                 limit=results_per_poll)
        print(f"Completed {max_polls} poll(s)", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("X poller stopped")
    except OperationFailure as exc:
        if exc.code == 8000 or "Authentication failed" in str(exc):
            raise SystemExit(
                "MongoDB authentication failed. Check MONGODB_URI username/password "
                "and URL-encode special password characters."
            ) from exc
        raise
    except ServerSelectionTimeoutError as exc:
        raise SystemExit(
            "MongoDB server selection failed. Check the Atlas URI and Network Access IP allowlist."
        ) from exc
    except RuntimeError as exc:
        if "Twikit cannot query X" in str(exc):
            raise SystemExit(str(exc)) from exc
        raise