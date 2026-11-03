import json
from pathlib import Path

import pytest

from app.apify import normalize_post
from app.models import engagement_count, engagement_rate_pct
from datetime import datetime, timezone


FIXTURES = Path(__file__).parent / "fixtures"


def test_metrics_from_apify_sample_fixture() -> None:
    post = json.loads((FIXTURES / "apify_instagram_post.json").read_text())
    profile = json.loads((FIXTURES / "apify_instagram_profile.json").read_text())

    interactions = engagement_count(post["likesCount"], post["commentsCount"])
    rate = engagement_rate_pct(
        post["likesCount"], post["commentsCount"], profile["followersCount"]
    )

    assert interactions == 120435
    assert rate == pytest.approx(0.044902, rel=1e-4)


def test_post_normalizer_uses_fields_from_saved_actor_sample() -> None:
    post = json.loads((FIXTURES / "apify_instagram_post.json").read_text())
    normalized = normalize_post(
        post,
        campaign_id="campaign-test",
        competitor_username="natgeo",
        followers=268210066,
        now=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )

    assert normalized is not None
    assert normalized.post_url == post["url"]
    assert normalized.likes == post["likesCount"]
    assert normalized.comments == post["commentsCount"]
    assert normalized.paid_partnership is False


@pytest.mark.parametrize(
    ("likes", "comments", "followers"),
    [(-1, 10, 1000), (10, None, 1000), (10, 5, None), (10, 5, 0)],
)
def test_hidden_or_missing_metrics_stay_unknown(
    likes: int | None, comments: int | None, followers: int | None
) -> None:
    assert engagement_rate_pct(likes, comments, followers) is None
