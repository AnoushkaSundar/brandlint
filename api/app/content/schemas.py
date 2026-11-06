from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.contracts import ContentState, DataClass

Channel = Literal["blog", "linkedin", "email", "ad", "banner", "document"]


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_id: str
    version: int
    text: str
    file_name: str | None
    fixes_applied: bool
    created_by: str
    created_at: datetime


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_version_id: str
    engine_review_id: str
    channel: str
    rulebook_version: int
    created_at: datetime


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    channel: Channel
    source: str
    data_class: DataClass
    state: ContentState
    creator_id: str
    created_at: datetime


class ContentDetail(ContentOut):
    # Newest first.
    versions: list[VersionOut]
    latest_review: ReviewOut | None
