from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dadri.connectors.base import BaseConnector, ConnectorBatch
from dadri.schemas.events import Author, InteractionEdge, Post


class XAuthorPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    username: str | None = None
    bio: str | None = None
    location_raw: str | None = None
    follower_count: int = Field(default=0, ge=0)
    following_count: int = Field(default=0, ge=0)
    account_created_at: datetime | None = None
    verified: bool = False


class XInteractionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_reply: bool = False
    is_retweet: bool = False
    is_quote: bool = False
    conversation_id: str | None = None
    reply_to_post_id: str | None = None
    reply_to_user_id: str | None = None
    mentions: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class XPostPayload(BaseModel):
    """Public JSON contract for X events."""

    model_config = ConfigDict(extra="ignore")

    post_id: str
    platform: str = "Twitter"
    timestamp: datetime
    text: str
    language: str | None = None
    author: XAuthorPayload
    interaction: XInteractionPayload
    engagement: dict[str, int] = Field(default_factory=dict)

    def as_json(self) -> str:
        return self.model_dump_json(exclude_none=False).replace("+00:00", "Z")


class XConnector(BaseConnector):
    """Authenticated twscrape adapter for latest-search polling and backfill."""

    platform = "x"

    def __init__(
        self,
        username: str | None = None,
        email: str | None = None,
        password: str | None = None,
        *,
        client: Any | None = None,
        poll_interval: float = 5.0,
        cookies_file: str | None = None,
        accounts_db: str = ".data/x_accounts.db",
        email_password: str | None = None,
    ) -> None:
        self._credentials = (username, email, password, email_password)
        self._client = client
        self._poll_interval = poll_interval
        self._cookies_file = cookies_file
        self._accounts_db = accounts_db

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from twscrape import API, AccountsPool
        except ImportError as exc:
            raise RuntimeError("Install the 'x' extra to use XConnector") from exc

        username, email, password, email_password = self._credentials
        if not username:
            raise RuntimeError("XConnector requires X_USERNAME for twscrape")
        pool = AccountsPool(self._accounts_db)
        cookies_path = Path(self._cookies_file) if self._cookies_file else None
        if cookies_path and cookies_path.is_file():
            cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
            await pool.add_account_cookies(username, json.dumps(cookies))
        elif username and email and password and email_password:
            await pool.add_account(username, password, email, email_password)
            await pool.login_all([username])
        else:
            raise RuntimeError(
                "Set X_COOKIES_FILE with auth_token/ct0 cookies, or set "
                "X_USERNAME, X_EMAIL, X_PASSWORD, and X_EMAIL_PASSWORD for twscrape"
            )
        self._client = API(pool)
        return self._client

    @staticmethod
    def _value(item: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(item, dict) and name in item:
                return item[name]
            value = getattr(item, name, None)
            if value is not None:
                return value
        return default

    @staticmethod
    def _utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).replace(" UTC", "+00:00")
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                parsed = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def to_payload(cls, tweet: Any) -> XPostPayload:
        user = cls._value(tweet, "user", default={}) or {}
        tweet_id = str(cls._value(tweet, "id", "id_str"))
        user_id = str(cls._value(user, "id", "id_str", default=""))
        username = cls._value(user, "screen_name", "username")
        reply_id = cls._value(tweet, "inReplyToTweetId", "in_reply_to_status_id")
        reply_user = cls._value(cls._value(tweet, "inReplyToUser", default={}), "id", "id_str")
        mentions_raw = cls._value(tweet, "mentionedUsers", "mentions", default=[]) or []
        mentions = [
            str(cls._value(mention, "screen_name", "username", default=""))
            for mention in mentions_raw
        ]
        hashtags = [str(value) for value in (cls._value(tweet, "hashtags", default=[]) or [])]
        urls = [
            str(cls._value(link, "expandedUrl", "url", default=""))
            for link in (cls._value(tweet, "links", default=[]) or [])
        ]
        conversation_id = cls._value(tweet, "conversationIdStr", "conversationId")
        is_retweet = cls._value(tweet, "retweetedTweet", default=None) is not None
        is_quote = bool(cls._value(tweet, "isQuoteStatus", default=False)) or (
            cls._value(tweet, "quotedTweet", default=None) is not None
        )
        return XPostPayload(
            post_id=f"TWT-{tweet_id}",
            platform="Twitter",
            timestamp=cls._utc(cls._value(tweet, "date", "created_at")),
            text=cls._value(tweet, "rawContent", "text", default="") or "",
            language=cls._value(tweet, "lang", default=None),
            author=XAuthorPayload(
                user_id=f"U-{user_id}",
                username=username,
                bio=cls._value(user, "rawDescription", "description") or None,
                location_raw=cls._value(user, "location", default=None) or None,
                follower_count=int(cls._value(user, "followersCount", "followers_count", default=0) or 0),
                following_count=int(cls._value(user, "friendsCount", "following_count", default=0) or 0),
                account_created_at=cls._utc(cls._value(user, "created", default=None))
                if cls._value(user, "created", default=None) else None,
                verified=bool(cls._value(user, "verified", default=False)),
            ),
            interaction=XInteractionPayload(
                is_reply=reply_id is not None,
                is_retweet=is_retweet,
                is_quote=is_quote,
                conversation_id=f"TWT-{conversation_id}" if conversation_id else None,
                reply_to_post_id=f"TWT-{reply_id}" if reply_id else None,
                reply_to_user_id=f"U-{reply_user}" if reply_user else None,
                mentions=[mention for mention in mentions if mention],
                hashtags=hashtags,
                urls=[url for url in urls if url],
            ),
            engagement={
                "like_count": int(cls._value(tweet, "likeCount", "favorite_count", default=0) or 0),
                "retweet_count": int(cls._value(tweet, "retweetCount", "retweet_count", default=0) or 0),
                "reply_count": int(cls._value(tweet, "replyCount", "reply_count", default=0) or 0),
                "quote_count": int(cls._value(tweet, "quoteCount", "quote_count", default=0) or 0),
                "impression_count": int(cls._value(tweet, "viewCount", "view_count", default=0) or 0),
            },
        )

    @classmethod
    def to_events(cls, tweet: Any) -> ConnectorBatch:
        payload = cls.to_payload(tweet)
        tweet_id = str(cls._value(tweet, "id", "id_str"))
        author_id = f"x_{payload.author.user_id}"
        post = Post(
            post_id=f"x_{tweet_id}", platform="x", author_id=author_id,
            created_at=payload.timestamp, content=payload.text,
            parent_post_id=payload.interaction.reply_to_post_id,
            root_post_id=None,
            interaction_type=("reply" if payload.interaction.is_reply else
                              "repost" if payload.interaction.is_retweet else
                              "quote" if payload.interaction.is_quote else "original"),
            engagement=payload.engagement,
            metadata={"json_payload": json.loads(payload.as_json()),
                      "source_url": cls._value(tweet, "url", default=f"https://x.com/i/status/{tweet_id}")},
        )
        author = Author(
            author_id=author_id, platform="x", username=payload.author.username,
            bio=payload.author.bio, follower_count=payload.author.follower_count,
            last_seen_at=payload.timestamp,
        )
        edges = [
            InteractionEdge(source_author_id=author_id, target_author_id=f"x_{mention}",
                            edge_type="mention", timestamp=post.created_at, post_id=post.post_id)
            for mention in payload.interaction.mentions
        ]
        if payload.interaction.is_reply and payload.interaction.reply_to_user_id:
            edges.append(InteractionEdge(
                source_author_id=author_id,
                target_author_id=f"x_{payload.interaction.reply_to_user_id.removeprefix('U-')}",
                edge_type="reply", timestamp=post.created_at, post_id=post.post_id,
            ))
        return ConnectorBatch(posts=[post], authors=[author], edges=edges)

    async def _iter_search(self, query: str, *, limit: int = 50) -> AsyncIterator[Any]:
        client = await self._get_client()
        async for tweet in client.search(query, limit=limit):
            yield tweet

    async def fetch_backfill(
        self, *, start: datetime, end: datetime | None = None,
        query: str = "", limit: int = 100, **kwargs: object,
    ) -> AsyncIterator[ConnectorBatch]:
        del kwargs
        async for tweet in self._iter_search(query or "-filter:retweets", limit=limit):
            timestamp = self.to_payload(tweet).timestamp
            if timestamp >= start.astimezone(timezone.utc) and (end is None or timestamp <= end.astimezone(timezone.utc)):
                yield self.to_events(tweet)

    async def fetch_stream(
        self,
        *,
        query: str = "-filter:retweets",
        limit: int = 1,
        max_polls: int | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ConnectorBatch]:
        del kwargs
        seen: set[str] = set()
        poll_count = 0
        while max_polls is None or poll_count < max_polls:
            poll_count += 1
            async for tweet in self._iter_search(query, limit=limit):
                tweet_id = str(self._value(tweet, "id", "id_str"))
                if tweet_id not in seen:
                    seen.add(tweet_id)
                    yield self.to_events(tweet)
            if max_polls is None or poll_count < max_polls:
                await asyncio.sleep(self._poll_interval)


def payload_json(tweet: Any) -> str:
    return XConnector.to_payload(tweet).as_json()
