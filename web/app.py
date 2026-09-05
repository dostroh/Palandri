from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

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


app = FastAPI(title="Dadri Intelligence Console", version="0.1.0", lifespan=lifespan)
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
