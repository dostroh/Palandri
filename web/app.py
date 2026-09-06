from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import UpdateOne

BASE_DIR = Path(__file__).parent


def _client_options() -> dict[str, Any]:
    return {
        "serverSelectionTimeoutMS": int(os.getenv("MONGODB_SERVER_TIMEOUT_MS", "10000")),
        "connectTimeoutMS": int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "10000")),
        "socketTimeoutMS": int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "20000")),
        "maxPoolSize": int(os.getenv("MONGODB_MAX_POOL_SIZE", "20")),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI must be set")
    client = AsyncIOMotorClient(uri, **_client_options())
    app.state.mongo_client = client
    app.state.database = client[os.getenv("MONGODB_DATABASE", "apitoprocessing")]
    try:
        yield
    finally:
        client.close()


app = FastAPI(title="Palan-dri Intelligence Console", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("DADRI_ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


def database() -> AsyncIOMotorDatabase:
    return app.state.database


def posts_collection():
    return database()[os.getenv("MONGODB_POSTS_COLLECTION", "realdata1")]


def analytics_collection():
    analytics_database = app.state.mongo_client[
        os.getenv("MONGODB_ANALYTICS_DATABASE", "processingtoanalytics")
    ]
    return analytics_database[os.getenv("MONGODB_ANALYTICS_COLLECTION", "fakedata")]


def jsonable(document: dict[str, Any]) -> dict[str, Any]:
    document = dict(document)
    document.pop("_id", None)
    for key, value in list(document.items()):
        if hasattr(value, "isoformat"):
            document[key] = value.isoformat()
    return document


@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        await app.state.mongo_client.admin.command("ping")
        return {"status": "ok", "database": database().name, "collection": posts_collection().name}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB unavailable: {exc}") from exc


@app.get("/api/summary")
async def summary() -> dict[str, Any]:
    collection = posts_collection()
    try:
        total = await collection.count_documents({})
        languages = {
            item["_id"] or "unknown": item["count"]
            async for item in collection.aggregate([
                {"$group": {"_id": "$language", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 8},
            ])
        }
        platforms = {
            item["_id"] or "unknown": item["count"]
            async for item in collection.aggregate([
                {"$group": {"_id": "$platform", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ])
        }
        latest = await collection.find_one({}, sort=[("timestamp", -1)])
        return {
            "total_posts": total,
            "languages": languages,
            "platforms": platforms,
            "latest_timestamp": latest.get("timestamp") if latest else None,
            "database": database().name,
            "collection": collection.name,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Summary unavailable: {exc}") from exc


@app.get("/api/posts")
async def posts(
    limit: int = Query(default=24, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=160),
    language: str | None = Query(default=None, max_length=12),
    platform: str | None = Query(default=None, max_length=30),
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if q:
        filters["text"] = {"$regex": re.escape(q), "$options": "i"}
    if language and language != "all":
        filters["language"] = language
    if platform and platform != "all":
        filters["platform"] = platform
    collection = posts_collection()
    try:
        total = await collection.count_documents(filters)
        cursor = collection.find(filters, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
        items = [jsonable(item) async for item in cursor]
        post_ids = [item.get("post_id") for item in items if item.get("post_id")]
        if post_ids:
            analytics_cursor = analytics_collection().find(
                {"post_id": {"$in": post_ids}}, {"_id": 0, "post_id": 1, "ml_insights": 1}
            )
            analytics = {
                item["post_id"]: item.get("ml_insights", {})
                async for item in analytics_cursor
            }
            for item in items:
                if item.get("post_id") in analytics:
                    item["ml_insights"] = analytics[item["post_id"]]
        return {"items": items, "total": total, "limit": limit, "skip": skip}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Posts unavailable: {exc}") from exc


@app.get("/api/edges")
async def edges(limit: int = Query(default=12, ge=1, le=50)) -> dict[str, Any]:
    try:
        cursor = database().interaction_edges.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        return {"items": [jsonable(item) async for item in cursor]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Edges unavailable: {exc}") from exc


# GoEmotions emits 27 emotions + neutral; it has no "Grievance" or "Anxiety" label.
# The radar's six psychological vectors are therefore explicit composites of the
# labels the model does produce. Surfaced in the API response so the UI can show
# exactly what each axis is made of rather than implying the model emits these names.
EMOTION_VECTORS = {
    "Fear": ["fear"],
    "Anger": ["anger", "annoyance"],
    "Grievance": ["disapproval", "disappointment", "remorse", "grief"],
    "Joy": ["joy", "amusement", "excitement", "gratitude", "love", "pride", "admiration"],
    "Anxiety": ["nervousness", "confusion", "embarrassment"],
    "Neutrality": ["neutral", "realization"],
}

RISK_BANDS = [(15, "HIGH"), (10, "ELEVATED"), (5, "MODERATE"), (0, "LOW")]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _poll_language() -> str:
    """Language polls are restricted to. The NLP stack is English-only, so anything
    else is dropped at ingestion rather than scored badly downstream."""
    return (os.getenv("POLL_LANGUAGE", "en") or "en").strip().lower()


def _post_language(post: Any) -> str | None:
    payload = (getattr(post, "metadata", None) or {}).get("json_payload")
    if isinstance(payload, dict):
        value = payload.get("language")
        return str(value).lower() if value else None
    return None


@app.get("/api/intel")
async def intel(q: str | None = Query(default=None, max_length=160)) -> dict[str, Any]:
    """KPIs, interaction graph and emotion radar, all derived from stored analytics."""
    filters: dict[str, Any] = {}
    if q:
        filters["text"] = {"$regex": re.escape(q), "$options": "i"}

    try:
        documents = [doc async for doc in analytics_collection().find(filters, {"_id": 0})]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Analytics unavailable: {exc}") from exc

    # --- interaction graph -------------------------------------------------
    in_degree: Counter = Counter()
    out_degree: Counter = Counter()
    labels: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    text_authors: dict[str, set] = {}

    for doc in documents:
        author = doc.get("author") or {}
        author_id = author.get("user_id")
        if not author_id:
            continue
        labels.setdefault(author_id, author.get("username") or author.get("display_name") or author_id)
        target = (doc.get("interaction") or {}).get("reply_to_user_id")
        if target:
            edges.append((author_id, target))
            out_degree[author_id] += 1
            in_degree[target] += 1
            labels.setdefault(target, target)
        normalized = _normalize_text(doc.get("text", ""))
        if normalized:
            text_authors.setdefault(normalized, set()).add(author_id)

    # Repeating text that more than one account posted is the coordination signal;
    # one account repeating itself is just a channel reposting.
    synchronized_texts = {text for text, posters in text_authors.items() if len(posters) > 1}
    synchronized_posts = sum(
        1 for doc in documents if _normalize_text(doc.get("text", "")) in synchronized_texts
    )
    amplifiers = {
        (doc.get("author") or {}).get("user_id")
        for doc in documents
        if _normalize_text(doc.get("text", "")) in synchronized_texts
    }
    amplifiers |= {node for node, count in out_degree.items() if count >= 2}
    amplifiers.discard(None)
    # A seed account is one several distinct accounts converge on, not merely one that was replied to.
    patient_zero = {node for node, count in in_degree.items() if count >= 2}

    def role_of(node: str) -> str:
        if node in patient_zero:
            return "patient_zero"
        if node in amplifiers:
            return "amplifier"
        return "organic"

    connected = {node for edge in edges for node in edge}
    nodes = [
        {
            "id": node,
            "label": labels.get(node, node),
            "role": role_of(node),
            "degree": in_degree.get(node, 0) + out_degree.get(node, 0),
        }
        for node in sorted(connected)
    ]
    links = [{"source": source, "target": target} for source, target in edges]

    # --- emotion radar -----------------------------------------------------
    totals: Counter = Counter()
    for doc in documents:
        distribution = ((doc.get("ml_insights") or {}).get("sentiment") or {}).get("emotion_distribution") or {}
        for label, score in distribution.items():
            totals[label] += float(score or 0)
    raw = {
        axis: round(sum(totals.get(label, 0.0) for label in members), 3)
        for axis, members in EMOTION_VECTORS.items()
    }
    peak = max(raw.values()) if raw else 0
    radar = [
        {
            "axis": axis,
            "value": round((value / peak) * 100, 1) if peak else 0.0,
            "raw": value,
            "labels": EMOTION_VECTORS[axis],
        }
        for axis, value in raw.items()
    ]

    # --- KPIs --------------------------------------------------------------
    campaigns = {
        ((doc.get("ml_insights") or {}).get("burst_signal") or {}).get("topic_id")
        for doc in documents
        if ((doc.get("ml_insights") or {}).get("burst_signal") or {}).get("is_burst")
    }
    campaigns.discard(None)
    risks = [float((doc.get("ml_insights") or {}).get("risk_score") or 0) for doc in documents]
    risk_mean = round(sum(risks) / len(risks), 2) if risks else 0.0
    risk_level = next(name for threshold, name in RISK_BANDS if risk_mean >= threshold)
    synchrony = round((synchronized_posts / len(documents)) * 100, 1) if documents else 0.0

    return {
        "query": q or "",
        "post_count": len(documents),
        "kpis": {
            "campaigns": len(campaigns),
            "campaign_topics": sorted(campaigns),
            "patient_zero": len(patient_zero),
            "synchrony": synchrony,
            "synchronized_posts": synchronized_posts,
            "risk_level": risk_level,
            "risk_mean": risk_mean,
        },
        "graph": {
            "nodes": nodes,
            "links": links,
            "isolated": len(labels) - len(connected),
            "roles": {
                "patient_zero": sum(1 for node in nodes if node["role"] == "patient_zero"),
                "amplifier": sum(1 for node in nodes if node["role"] == "amplifier"),
                "organic": sum(1 for node in nodes if node["role"] == "organic"),
            },
        },
        "radar": radar,
    }


async def _poll_x(query: str, limit: int) -> list:
    """One bounded twscrape search round. Raises HTTPException(400) if unconfigured."""
    try:
        from dadri.connectors.x_twitter import XConnector
    except ImportError as exc:
        raise HTTPException(status_code=400, detail="twscrape is not installed (pip install twscrape)") from exc

    username = os.getenv("X_USERNAME")
    cookies_file = os.getenv("X_COOKIES_FILE")
    if not username:
        raise HTTPException(status_code=400, detail="X_USERNAME is not set")
    if cookies_file and not Path(cookies_file).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"X cookie file '{cookies_file}' not found. Save your x.com auth_token and ct0 there.",
        )

    accounts_db = os.getenv("X_ACCOUNTS_DB", ".data/x_accounts.db")
    Path(accounts_db).parent.mkdir(parents=True, exist_ok=True)
    connector = XConnector(
        username=username,
        email=os.getenv("X_EMAIL"),
        password=os.getenv("X_PASSWORD"),
        email_password=os.getenv("X_EMAIL_PASSWORD"),
        cookies_file=cookies_file,
        accounts_db=accounts_db,
    )
    # Ask X itself to filter first: its lang: operator is far cheaper than pulling
    # everything and discarding it. Respect an explicit lang: the caller already typed.
    language = _poll_language()
    effective_query = query if "lang:" in query.lower() else f"{query} lang:{language}"

    batches, skipped = [], 0
    try:
        async for batch in connector.fetch_stream(query=effective_query, limit=limit, max_polls=1):
            # Second pass: lang: is a search hint, so verify what actually came back.
            if batch.posts and _post_language(batch.posts[0]) not in (language, None):
                skipped += len(batch.posts)
                continue
            batches.append(batch)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"X poll failed: {exc}") from exc
    return batches, skipped


async def _poll_telegram(entity: str, limit: int) -> list:
    """Newest `limit` messages from one channel, using an existing Telethon session."""
    try:
        from telethon import TelegramClient
        from dadri.connectors.telegram import TelegramConnector
        from dadri.connectors.base import ConnectorBatch
    except ImportError as exc:
        raise HTTPException(status_code=400, detail="telethon is not installed (pip install telethon)") from exc

    api_id, api_hash = os.getenv("TELEGRAM_API_ID"), os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise HTTPException(status_code=400, detail="TELEGRAM_API_ID / TELEGRAM_API_HASH are not set")

    session = os.getenv("TELEGRAM_SESSION", ".data/telegram")
    try:
        Path(session).parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(session, int(api_id), api_hash)
        await client.connect()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not open Telegram session: {exc}") from exc
    try:
        # Never client.start() here: it prompts for a phone number and login code on stdin,
        # which would hang the server. The session must already exist.
        if not await client.is_user_authorized():
            raise HTTPException(
                status_code=400,
                detail=(
                    "No authorized Telegram session. Run "
                    "'.venv\\Scripts\\python.exe -m dadri.workers.run_telegram' once in a "
                    "terminal to complete the phone + code login, then retry."
                ),
            )
        language = _poll_language()
        connector = TelegramConnector(client=client, entity=entity, language=language)
        resolved = await client.get_entity(entity)
        batches, skipped = [], 0
        # _messages() walks a channel from its first post; for a bounded "latest N" poll we
        # iterate newest-first here and reuse the connector's own normalization.
        async for message in client.iter_messages(resolved, limit=limit):
            if getattr(message, "date", None) is None:
                continue
            # Telegram messages carry no language tag, so the connector runs langdetect.
            # Captionless media fails this too, which is fine: there is nothing to analyse.
            if not connector._matches_language(getattr(message, "raw_text", "") or ""):
                skipped += 1
                continue
            post, author, edges = await connector._normalize(message, resolved)
            batches.append(ConnectorBatch(posts=[post], authors=[author], edges=edges))
        return batches, skipped
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Telegram poll failed: {exc}") from exc
    finally:
        await client.disconnect()


@app.post("/api/poll")
async def poll(payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch fresh posts from X or Telegram, store them, and analyse just those posts."""
    source = str(payload.get("source") or "").strip().lower()
    query = str(payload.get("query") or "").strip()
    limit = max(1, min(int(payload.get("limit") or 5), 25))

    if source not in {"x", "telegram"}:
        raise HTTPException(status_code=400, detail="source must be 'x' or 'telegram'")
    if not query:
        raise HTTPException(status_code=400, detail="Enter keywords (X) or a channel (Telegram)")

    batches, skipped = await (_poll_x(query, limit) if source == "x" else _poll_telegram(query, limit))
    language = _poll_language()

    from dadri.storage.repository import bulk_upsert_batch

    posts_name = os.getenv("MONGODB_POSTS_COLLECTION", "realdata1")
    post_ids: list[str] = []
    for batch in batches:
        await bulk_upsert_batch(database(), batch, posts_collection=posts_name)
        post_ids.extend(post.post_id for post in batch.posts)

    if not post_ids:
        message = (
            f"No {language} posts matched — {skipped} result(s) were dropped as non-{language}."
            if skipped else "No new posts matched."
        )
        return {"fetched": 0, "analyzed": 0, "skipped": skipped, "language": language, "items": [], "message": message}

    # Match on _id, not the body's post_id: the repository keys documents by the Post
    # model's platform-prefixed id (x_123...), while the stored body carries TWT-123...
    stored = [doc async for doc in posts_collection().find({"_id": {"$in": post_ids}}, {"_id": 0})]

    from processing.analyzer import analyze_documents, topic_counts_from

    analytics = analytics_collection()
    existing = [doc async for doc in analytics.find({}, {"_id": 0, "ml_insights.trends.topic_id": 1})]
    baseline = topic_counts_from(existing)

    # Model inference is blocking CPU work; keep it off the event loop.
    analyzed = await asyncio.to_thread(analyze_documents, stored, baseline_topic_counts=baseline)

    if analyzed:
        await analytics.bulk_write(
            # Filter on post_id so a re-poll updates the batch pipeline's existing
            # analytics row instead of inserting a duplicate under a different _id.
            [UpdateOne({"post_id": doc["post_id"]}, {"$set": doc}, upsert=True) for doc in analyzed],
            ordered=False,
        )

    return {
        "fetched": len(post_ids),
        "analyzed": len(analyzed),
        "skipped": skipped,
        "language": language,
        "items": [jsonable(doc) for doc in analyzed],
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/{path:path}", include_in_schema=False)
async def static_files(path: str) -> FileResponse:
    candidate = (BASE_DIR / "static" / path).resolve()
    static_root = (BASE_DIR / "static").resolve()
    if candidate.is_file() and static_root in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(BASE_DIR / "static" / "index.html")
