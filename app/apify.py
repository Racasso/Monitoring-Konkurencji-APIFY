from __future__ import annotations

import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from apify_client import ApifyClient

from app.models import CampaignCreate, PostSnapshot, ProfileSnapshot, engagement_count, engagement_rate_pct


def profile_url(username: str) -> str:
    return f"https://www.instagram.com/{username}/"


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if value >= 0 else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _input_username(raw: dict[str, Any]) -> str | None:
    input_url = raw.get("inputUrl")
    if isinstance(input_url, str):
        parts = [part for part in urlparse(input_url).path.split("/") if part]
        if parts and parts[0] not in {"p", "reel", "reels"}:
            return parts[0].lower()
    owner = raw.get("ownerUsername")
    return owner.lower() if isinstance(owner, str) and owner else None


def normalize_post(
    raw: dict[str, Any],
    *,
    campaign_id: str,
    competitor_username: str,
    followers: int | None,
    now: datetime,
) -> PostSnapshot | None:
    """Map the observed Actor fields into the business post document."""
    post_url = raw.get("url")
    if not isinstance(post_url, str) or not post_url.startswith("https://www.instagram.com/"):
        return None

    likes = _nonnegative_int(raw.get("likesCount"))
    comments = _nonnegative_int(raw.get("commentsCount"))
    plays = _nonnegative_int(raw.get("videoPlayCount"))
    if plays is None:
        plays = _nonnegative_int(raw.get("videoViewCount"))

    return PostSnapshot(
        _id=f"{campaign_id}:{post_url}",
        type="post_snapshot",
        schema_version=1,
        created_at=now,
        updated_at=now,
        campaign_id=campaign_id,
        competitor_username=competitor_username,
        source_id=str(raw["id"]) if raw.get("id") is not None else None,
        post_url=post_url,
        post_type=raw.get("type") if isinstance(raw.get("type"), str) else None,
        caption=raw.get("caption") if isinstance(raw.get("caption"), str) else None,
        published_at=_parse_datetime(raw.get("timestamp")),
        likes=likes,
        comments=comments,
        video_plays=plays,
        hashtags=[str(item).removeprefix("#") for item in _list(raw.get("hashtags")) if item],
        mentions=[str(item).removeprefix("@") for item in _list(raw.get("mentions")) if item],
        paid_partnership=(
            raw.get("paidPartnership") if isinstance(raw.get("paidPartnership"), bool) else None
        ),
        sponsors=[item for item in _list(raw.get("sponsors")) if isinstance(item, dict)],
        tagged_users=[item for item in _list(raw.get("taggedUsers")) if isinstance(item, dict)],
        coauthors=[item for item in _list(raw.get("coauthorProducers")) if isinstance(item, dict)],
        engagement_count=engagement_count(likes, comments),
        engagement_rate_pct=engagement_rate_pct(likes, comments, followers),
    )


def _run_actor(client: ApifyClient, actor_id: str, run_input: dict[str, Any], max_items: int):
    run = client.actor(actor_id).call(
        run_input=run_input,
        max_items=max_items,
        max_total_charge_usd=Decimal(
            os.environ.get("APIFY_MAX_TOTAL_CHARGE_USD_PER_RUN", "0.70")
        ),
        run_timeout=timedelta(minutes=10),
    )
    if run is None:
        raise RuntimeError("Apify did not return a run")
    status = getattr(run.status, "value", str(run.status))
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify actor run finished with status {status}")
    items = list(client.dataset(run.default_dataset_id).iterate_items())
    return run, items


def fetch_campaign_data(
    payload: CampaignCreate,
    *,
    campaign_id: str,
    window_start: datetime,
) -> dict[str, Any]:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not configured")
    actor_id = os.environ.get("APIFY_ACTOR_ID", "apify/instagram-scraper")
    client = ApifyClient(token)
    usernames = [competitor.username for competitor in payload.competitors]
    urls = [profile_url(username) for username in usernames]
    now = datetime.now(timezone.utc)

    post_run, raw_posts = _run_actor(
        client,
        actor_id,
        {
            "resultsType": "posts",
            "directUrls": urls,
            "resultsLimit": payload.max_posts_per_competitor,
            "onlyPostsNewerThan": window_start.strftime("%Y-%m-%d"),
            "skipPinnedPosts": True,
        },
        max_items=min(
            payload.max_posts_per_competitor * len(usernames),
            int(os.environ.get("APIFY_MAX_ITEMS_PER_RUN", "250")),
        ),
    )
    profile_run, raw_profiles = _run_actor(
        client,
        actor_id,
        {"resultsType": "details", "directUrls": urls},
        max_items=min(len(usernames), int(os.environ.get("APIFY_MAX_ITEMS_PER_RUN", "250"))),
    )

    profiles: dict[str, ProfileSnapshot] = {}
    profile_errors = 0
    for raw in raw_profiles:
        username = raw.get("username")
        if raw.get("error") or not isinstance(username, str):
            profile_errors += 1
            continue
        profiles[username.lower()] = ProfileSnapshot(
            followers=_nonnegative_int(raw.get("followersCount")), captured_at=now
        )

    posts: list[PostSnapshot] = []
    post_errors = 0
    followers_by_username = {
        username: profiles.get(username).followers if profiles.get(username) else None
        for username in usernames
    }
    for raw in raw_posts:
        username = _input_username(raw)
        if raw.get("error") or not username:
            post_errors += 1
            continue
        post = normalize_post(
            raw,
            campaign_id=campaign_id,
            competitor_username=username,
            followers=followers_by_username.get(username),
            now=now,
        )
        if post is None:
            post_errors += 1
        else:
            posts.append(post)

    run_costs = [
        {
            "run_id": post_run.id,
            "usage_total_usd": post_run.usage_total_usd,
        },
        {
            "run_id": profile_run.id,
            "usage_total_usd": profile_run.usage_total_usd,
        },
    ]
    costs = [entry["usage_total_usd"] for entry in run_costs]
    total_cost = sum(costs) if all(cost is not None for cost in costs) else None
    return {
        "profiles": profiles,
        "posts": posts,
        "apify_runs": run_costs,
        "apify_cost_usd": total_cost,
        "post_errors": post_errors,
        "profile_errors": profile_errors,
    }
