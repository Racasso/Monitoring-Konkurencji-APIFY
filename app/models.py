from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(alias="_id")
    type: str
    schema_version: int = 1
    created_at: datetime
    updated_at: datetime


class CompetitorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=255)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if "instagram.com" in value.lower():
            path_parts = [part for part in urlparse(value).path.split("/") if part]
            if not path_parts:
                raise ValueError("Instagram profile URL must contain a username")
            value = path_parts[0]
        value = value.removeprefix("@").strip().lower()
        if not re.fullmatch(r"[a-z0-9._]{1,30}", value):
            raise ValueError("username must be an Instagram handle or profile URL")
        return value


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_key: str = Field(min_length=1, max_length=120)
    client_ref: str = Field(min_length=1, max_length=120)
    competitors: list[CompetitorInput] = Field(min_length=3, max_length=5)
    window_days: int = Field(
        default_factory=lambda: int(os.environ.get("ANALYSIS_WINDOW_DAYS", "30")),
        ge=1,
        le=365,
        validate_default=True,
    )
    max_posts_per_competitor: int = Field(
        default_factory=lambda: int(os.environ.get("MAX_POSTS_PER_COMPETITOR", "50")),
        ge=1,
        le=50,
        validate_default=True,
    )

    @field_validator("campaign_key", "client_ref")
    @classmethod
    def trim_identifiers(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("competitors")
    @classmethod
    def require_unique_competitors(cls, value: list[CompetitorInput]) -> list[CompetitorInput]:
        usernames = [competitor.username for competitor in value]
        if len(set(usernames)) != len(usernames):
            raise ValueError("competitor usernames must be unique")
        return value


class AnalysisWindow(BaseModel):
    platform: Literal["instagram"] = "instagram"
    start: datetime
    end: datetime
    window_days: int
    max_posts_per_competitor: int
    collaboration_interpretation: str = (
        "Mentions and tags are evidence signals; they do not prove a paid contract."
    )


class ProfileSnapshot(BaseModel):
    followers: int | None = None
    captured_at: datetime


class PostSnapshot(DocumentModel):
    type: Literal["post_snapshot"] = "post_snapshot"
    campaign_id: str
    competitor_username: str
    source_id: str | None = None
    post_url: str
    post_type: str | None = None
    caption: str | None = None
    published_at: datetime | None = None
    likes: int | None = None
    comments: int | None = None
    video_plays: int | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    paid_partnership: bool | None = None
    sponsors: list[dict[str, Any]] = Field(default_factory=list)
    tagged_users: list[dict[str, Any]] = Field(default_factory=list)
    coauthors: list[dict[str, Any]] = Field(default_factory=list)
    engagement_count: int | None = None
    engagement_rate_pct: float | None = None


class CompetitorMetrics(BaseModel):
    posts_in_window: int = 0
    posts_per_week: float = 0.0
    mean_engagement_rate_pct: float | None = None
    paid_collaboration_posts: int = 0
    posts_may_be_truncated: bool = False


class CollaborationEvidence(BaseModel):
    post_url: str
    paid_partnership: bool | None = None
    sponsors: list[dict[str, Any]] = Field(default_factory=list)
    tagged_users: list[dict[str, Any]] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    coauthors: list[dict[str, Any]] = Field(default_factory=list)


class CompetitorDocument(BaseModel):
    username: str
    profile_url: str
    profile_snapshot: ProfileSnapshot | None = None
    metrics: CompetitorMetrics = Field(default_factory=CompetitorMetrics)
    best_posts: list[PostSnapshot] = Field(default_factory=list)
    collaborations: list[CollaborationEvidence] = Field(default_factory=list)
    posts: list[PostSnapshot] = Field(default_factory=list)


class CampaignSummary(BaseModel):
    competitor_count: int = 0
    total_posts: int = 0
    paid_collaboration_posts: int = 0


class CampaignDocument(DocumentModel):
    type: Literal["campaign"] = "campaign"
    business_key: str
    client_ref: str
    status: Literal["queued", "running", "done", "failed"]
    analysis: AnalysisWindow
    competitors: list[CompetitorDocument]
    summary: CampaignSummary = Field(default_factory=CampaignSummary)
    last_completed_at: datetime | None = None


class ApifyRunCost(BaseModel):
    run_id: str
    usage_total_usd: float | None = None


class JobDocument(DocumentModel):
    type: Literal["job"] = "job"
    campaign_id: str
    idempotency_key: str
    status: Literal["queued", "running", "done", "failed"]
    payload: CampaignCreate
    window_start: datetime
    window_end: datetime
    attempts: int = 0
    apify_cost_usd: float | None = None
    apify_runs: list[ApifyRunCost] = Field(default_factory=list)
    result_counts: dict[str, int] = Field(default_factory=dict)
    error_type: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CreateCampaignResponse(BaseModel):
    campaign_id: str
    job_id: str
    status: str


def engagement_count(likes: int | None, comments: int | None) -> int | None:
    if likes is None or comments is None or likes < 0 or comments < 0:
        return None
    return likes + comments


def engagement_rate_pct(
    likes: int | None, comments: int | None, followers: int | None
) -> float | None:
    interactions = engagement_count(likes, comments)
    if interactions is None or followers is None or followers <= 0:
        return None
    return interactions / followers * 100
