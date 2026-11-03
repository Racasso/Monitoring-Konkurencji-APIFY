from datetime import datetime, timezone

from app.db import upsert_posts
from app.models import PostSnapshot


class MemoryPostsCollection:
    """Small fake that applies the UpdateOne upserts produced by upsert_posts."""

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict] = {}

    def bulk_write(self, operations, ordered: bool = False):
        inserted = 0
        modified = 0
        for operation in operations:
            key = (operation._filter["campaign_id"], operation._filter["post_url"])
            update = operation._doc
            assert not (set(update["$set"]) & set(update["$setOnInsert"]))
            if key not in self.documents:
                document = dict(update["$setOnInsert"])
                document.update(update["$set"])
                self.documents[key] = document
                inserted += 1
            else:
                self.documents[key].update(update["$set"])
                modified += 1

        return type("BulkResult", (), {"upserted_count": inserted, "modified_count": modified})()


def make_post(caption: str, updated_at: datetime) -> PostSnapshot:
    created_at = datetime(2026, 11, 3, tzinfo=timezone.utc)
    return PostSnapshot(
        _id="campaign-1:https://www.instagram.com/p/abc/",
        type="post_snapshot",
        schema_version=1,
        created_at=created_at,
        updated_at=updated_at,
        campaign_id="campaign-1",
        competitor_username="natgeo",
        post_url="https://www.instagram.com/p/abc/",
        caption=caption,
        published_at=created_at,
        likes=100,
        comments=10,
        engagement_count=110,
        engagement_rate_pct=0.1,
    )


def test_post_upsert_is_idempotent_by_campaign_and_url() -> None:
    collection = MemoryPostsCollection()
    first_time = datetime(2026, 11, 3, 10, tzinfo=timezone.utc)
    second_time = datetime(2026, 11, 3, 11, tzinfo=timezone.utc)

    upsert_posts(collection, [make_post("first observation", first_time)])
    upsert_posts(collection, [make_post("updated observation", second_time)])

    assert len(collection.documents) == 1
    saved = collection.documents[("campaign-1", "https://www.instagram.com/p/abc/")]
    assert saved["caption"] == "updated observation"
    assert saved["created_at"] == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert saved["updated_at"] == second_time
