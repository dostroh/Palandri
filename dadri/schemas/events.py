from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Platform = Literal["x", "telegram", "youtube"]
InteractionType = Literal["original", "reply", "quote", "repost", "forward"]
EdgeType = Literal["reply", "mention", "retweet", "forward"]
UTCDateTime = Annotated[datetime, Field(description="Timezone-aware UTC timestamp")]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware and in UTC")
    return value.astimezone(timezone.utc)


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Post(EventModel):
    post_id: str = Field(min_length=3)
    platform: Platform
    author_id: str = Field(min_length=3)
    created_at: UTCDateTime
    content: str
    parent_post_id: str | None = None
    root_post_id: str | None = None
    interaction_type: InteractionType = "original"
    engagement: dict[str, int | float] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    inferred_attributes: dict[str, object] | None = None

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _as_utc(value)


class Author(EventModel):
    author_id: str = Field(min_length=3)
    platform: Platform
    username: str | None = None
    bio: str | None = None
    location_string: str | None = None
    follower_count: int = Field(default=0, ge=0)
    following_count: int = Field(default=0, ge=0)
    verified: bool = False
    last_seen_at: UTCDateTime

    @field_validator("last_seen_at")
    @classmethod
    def validate_last_seen_at(cls, value: datetime) -> datetime:
        return _as_utc(value)


class InteractionEdge(EventModel):
    source_author_id: str = Field(min_length=3)
    target_author_id: str = Field(min_length=3)
    edge_type: EdgeType
    timestamp: UTCDateTime
    post_id: str = Field(min_length=3)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _as_utc(value)
