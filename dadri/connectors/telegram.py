from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from dadri.connectors.base import BaseConnector, ConnectorBatch
from dadri.schemas.events import Author, InteractionEdge, Post

MENTION_PATTERN = re.compile(r"(?<![\w-])@([A-Za-z0-9_]+)")
URL_PATTERN = re.compile(r"https?://[^\s]+")


class TelegramConnector(BaseConnector):
    """Telethon adapter for channel history and cancellable polling."""

    platform = "telegram"

    def __init__(self, client: Any | None = None, *, entity: Any = None,
                 poll_interval: float = 5.0, language: str | None = None) -> None:
        self._client = client
        self._entity = entity
        self._poll_interval = poll_interval
        self._language = language.lower() if language else None

    def _matches_language(self, text: str) -> bool:
        if not self._language:
            return True
        try:
            from langdetect import detect
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'language' extra to filter Telegram messages by language"
            ) from exc
        if not text.strip():
            return False
        try:
            return detect(text) == self._language
        except Exception:
            return False

    def _get_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("TelegramConnector requires an initialized Telethon client")
        return self._client

    async def _resolve_entity(self, entity: Any = None) -> Any:
        target = entity if entity is not None else self._entity
        if target is None:
            raise ValueError("Telegram entity is required")
        return await self._get_client().get_entity(target) if isinstance(target, str) else target

    @staticmethod
    def _user_id(user: Any) -> str:
        return f"telegram_{getattr(user, 'id', user)}"

    async def _author(self, user: Any, seen_at: datetime) -> Author:
        user = user or object()
        return Author(
            author_id=self._user_id(user), platform="telegram",
            username=getattr(user, "username", None),
            bio=getattr(user, "about", None), location_string=getattr(user, "geo_point", None),
            follower_count=0, following_count=0,
            verified=bool(getattr(user, "verified", False)), last_seen_at=seen_at,
        )

    async def _normalize(self, message: Any, entity: Any) -> tuple[Post, Author, list[InteractionEdge]]:
        now = datetime.now(timezone.utc)
        sender = await self._get_client().get_entity(message.sender_id) if message.sender_id else entity
        author = await self._author(sender, now)
        channel_id = str(getattr(entity, "id"))
        post_id = f"telegram_{channel_id}_{message.id}"
        reply_id = getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None)
        forwarded = getattr(message, "fwd_from", None) is not None
        interaction = "forward" if forwarded else ("reply" if reply_id else "original")
        created = message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
        text = getattr(message, "raw_text", "") or ""
        reply_user_id = None
        if reply_id and hasattr(message, "get_reply_message"):
            reply_message = await message.get_reply_message()
            reply_sender = getattr(reply_message, "sender_id", None) if reply_message else None
            if reply_sender is not None:
                reply_user_id = f"U-{reply_sender}"
        forwarded_from = getattr(getattr(message, "fwd_from", None), "from_id", None)
        channel_type = "group" if getattr(entity, "megagroup", False) else "channel"
        author_id = f"U-{getattr(sender, 'id', getattr(message, 'sender_id', 'unknown'))}"
        public_username = getattr(entity, "username", None)
        payload = {
            "post_id": f"TG-{channel_id}-{message.id}",
            "platform": "Telegram",
            "timestamp": created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "text": text,
            "language": getattr(message, "lang", None),
            "channel": {
                "channel_id": f"CH-{channel_id}",
                "channel_name": getattr(entity, "title", public_username),
                "channel_type": channel_type,
                "member_count": getattr(entity, "participants_count", None),
                "is_public": bool(public_username),
            },
            "author": {
                "user_id": author_id,
                "username": getattr(sender, "username", None),
                "display_name": " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])) or None,
                "bio": getattr(sender, "about", None),
                "account_created_at": None,
                "is_bot": bool(getattr(sender, "bot", False)),
            },
            "interaction": {
                "is_reply": reply_id is not None,
                "reply_to_post_id": f"TG-{channel_id}-{reply_id}" if reply_id else None,
                "reply_to_user_id": reply_user_id,
                "is_forwarded": forwarded,
                "forwarded_from_channel": str(forwarded_from) if forwarded_from else None,
                "forwarded_from_message_id": getattr(getattr(message, "fwd_from", None), "channel_post", None),
                "mentions": MENTION_PATTERN.findall(text),
                "urls": URL_PATTERN.findall(text),
            },
            "engagement": {
                "views": int(getattr(message, "views", 0) or 0),
                "forward_count": int(getattr(message, "forwards", 0) or 0),
                "reaction_count": len(getattr(getattr(message, "reactions", None), "results", []) or []),
            },
        }
        metadata = {
            "json_payload": payload,
            "chat_id": channel_id,
            "source_url": getattr(message, "url", None),
            "has_media": getattr(message, "media", None) is not None,
            "forwarded_from": str(getattr(getattr(message, "fwd_from", None), "from_id", "")) or None,
        }
        post = Post(
            post_id=post_id, platform="telegram", author_id=author.author_id,
            created_at=created, content=text,
            parent_post_id=f"telegram_{channel_id}_{reply_id}" if reply_id else None,
            root_post_id=None, interaction_type=interaction,
            engagement={key: int(value) for key, value in {
                "views": getattr(message, "views", 0) or 0,
                "comments": getattr(message, "replies", None).replies if getattr(message, "replies", None) else 0,
            }.items()}, metadata=metadata,
        )
        edges: list[InteractionEdge] = []
        if reply_id and message.sender_id:
            reply_target = getattr(getattr(message, "reply_to", None), "reply_to_top_id", None)
            target_id = f"telegram_{getattr(entity, 'id')}_{reply_target or reply_id}"
            edges.append(InteractionEdge(source_author_id=author.author_id, target_author_id=target_id,
                                         edge_type="reply", timestamp=post.created_at, post_id=post.post_id))
        if forwarded and getattr(getattr(message, "fwd_from", None), "from_id", None):
            target = self._user_id(getattr(message.fwd_from, "from_id"))
            edges.append(InteractionEdge(source_author_id=author.author_id, target_author_id=target,
                                         edge_type="forward", timestamp=post.created_at, post_id=post.post_id))
        return post, author, edges

    async def _messages(self, *, entity: Any, start: datetime | None = None,
                        end: datetime | None = None, min_id: int = 0) -> AsyncIterator[ConnectorBatch]:
        resolved = await self._resolve_entity(entity)
        async for message in self._get_client().iter_messages(resolved, reverse=True, min_id=min_id):
            if getattr(message, "date", None) is None:
                continue
            created = message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
            if start and created < start:
                continue
            if end and created > end:
                break
            if not self._matches_language(getattr(message, "raw_text", "") or ""):
                continue
            post, author, edges = await self._normalize(message, resolved)
            yield ConnectorBatch(posts=[post], authors=[author], edges=edges)

    async def fetch_backfill(self, *, start: datetime, end: datetime | None = None,
                             entity: Any = None, **kwargs: object) -> AsyncIterator[ConnectorBatch]:
        async for batch in self._messages(entity=entity, start=start, end=end, **kwargs):
            yield batch

    async def fetch_stream(
        self,
        *,
        entity: Any = None,
        max_polls: int | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ConnectorBatch]:
        last_id = 0
        poll_count = 0
        while max_polls is None or poll_count < max_polls:
            poll_count += 1
            emitted = False
            async for batch in self._messages(entity=entity, min_id=last_id, **kwargs):
                emitted = True
                last_id = max(last_id, int(batch.posts[0].post_id.rsplit("_", 1)[-1]))
                yield batch
            if not emitted and (max_polls is None or poll_count < max_polls):
                await asyncio.sleep(self._poll_interval)
