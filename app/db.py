from __future__ import annotations

import os
from typing import Any, Iterable

from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne

from app.models import PostSnapshot


def create_client() -> MongoClient:
    return MongoClient(
        os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=5000,
        tz_aware=True,
    )


def get_database(client: MongoClient):
    return client[os.environ.get("MONGO_DATABASE", "competitor_monitoring")]


def ensure_indexes(database) -> None:
    database.campaigns.create_index("business_key", unique=True, name="campaign_business_key")
    database.jobs.create_index(
        [("campaign_id", ASCENDING), ("idempotency_key", ASCENDING)],
        unique=True,
        name="job_idempotency_key",
    )
    database.jobs.create_index(
        [("status", ASCENDING), ("created_at", ASCENDING)],
        name="job_queue_order",
    )
    database.jobs.create_index(
        [("status", ASCENDING), ("claimed_at", ASCENDING)],
        name="stale_job_claims",
    )
    database.posts.create_index(
        [("campaign_id", ASCENDING), ("post_url", ASCENDING)],
        unique=True,
        name="campaign_post_url",
    )
    database.posts.create_index(
        [("campaign_id", ASCENDING), ("competitor_username", ASCENDING), ("published_at", DESCENDING)],
        name="campaign_competitor_published_at",
    )


def upsert_posts(collection, posts: Iterable[PostSnapshot]) -> int:
    """Bulk-upsert post snapshots by the unique campaign/post URL key."""
    unique_posts: dict[tuple[str, str], PostSnapshot] = {}
    for post in posts:
        unique_posts[(post.campaign_id, post.post_url)] = post
    if not unique_posts:
        return 0

    operations = []
    for post in unique_posts.values():
        record = post.model_dump(by_alias=True, mode="python")
        identity = {"campaign_id": post.campaign_id, "post_url": post.post_url}
        insert_fields = {
            "_id": record["_id"],
            "type": record["type"],
            "schema_version": record["schema_version"],
            "created_at": record["created_at"],
            "campaign_id": record["campaign_id"],
            "post_url": record["post_url"],
        }
        update_fields = {
            key: value
            for key, value in record.items()
            if key
            not in {
                "_id",
                "type",
                "schema_version",
                "created_at",
                "campaign_id",
                "post_url",
            }
        }
        operations.append(
            UpdateOne(
                identity,
                {"$set": update_fields, "$setOnInsert": insert_fields},
                upsert=True,
            )
        )
    result = collection.bulk_write(operations, ordered=False)
    return result.upserted_count + result.modified_count


def campaign_report_pipeline(campaign_id: str) -> list[dict[str, Any]]:
    return [
        {"$match": {"_id": campaign_id}},
        {
            "$lookup": {
                "from": "posts",
                "let": {
                    "campaign_id": "$_id",
                    "window_start": "$analysis.start",
                    "window_end": "$analysis.end",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$campaign_id", "$$campaign_id"]},
                                    {"$gte": ["$published_at", "$$window_start"]},
                                    {"$lte": ["$published_at", "$$window_end"]},
                                ]
                            }
                        }
                    },
                    {"$sort": {"published_at": -1}},
                ],
                "as": "_posts",
            }
        },
        {
            "$set": {
                "competitors": {
                    "$map": {
                        "input": "$competitors",
                        "as": "competitor",
                        "in": {
                            "$let": {
                                "vars": {
                                    "posts": {
                                        "$filter": {
                                            "input": "$_posts",
                                            "as": "post",
                                            "cond": {
                                                "$eq": [
                                                    "$$post.competitor_username",
                                                    "$$competitor.username",
                                                ]
                                            },
                                        }
                                    }
                                },
                                "in": {
                                    "$mergeObjects": [
                                        "$$competitor",
                                        {
                                            "posts": "$$posts",
                                            "metrics": {
                                                "posts_in_window": {"$size": "$$posts"},
                                                "posts_per_week": {
                                                    "$cond": [
                                                        {"$gt": ["$analysis.window_days", 0]},
                                                        {
                                                            "$multiply": [
                                                                {
                                                                    "$divide": [
                                                                        {"$size": "$$posts"},
                                                                        "$analysis.window_days",
                                                                    ]
                                                                },
                                                                7,
                                                            ]
                                                        },
                                                        0,
                                                    ]
                                                },
                                                "mean_engagement_rate_pct": {
                                                    "$avg": {
                                                        "$map": {
                                                            "input": "$$posts",
                                                            "as": "post",
                                                            "in": "$$post.engagement_rate_pct",
                                                        }
                                                    }
                                                },
                                                "paid_collaboration_posts": {
                                                    "$size": {
                                                        "$filter": {
                                                            "input": "$$posts",
                                                            "as": "post",
                                                            "cond": {
                                                                "$eq": [
                                                                    "$$post.paid_partnership",
                                                                    True,
                                                                ]
                                                            },
                                                        }
                                                    }
                                                },
                                                "posts_may_be_truncated": {
                                                    "$gte": [
                                                        {"$size": "$$posts"},
                                                        "$analysis.max_posts_per_competitor",
                                                    ]
                                                },
                                            },
                                            "best_posts": {
                                                "$slice": [
                                                    {
                                                        "$sortArray": {
                                                            "input": "$$posts",
                                                            "sortBy": {
                                                                "engagement_rate_pct": -1,
                                                                "engagement_count": -1,
                                                                "published_at": -1,
                                                            },
                                                        }
                                                    },
                                                    3,
                                                ]
                                            },
                                            "collaborations": {
                                                "$map": {
                                                    "input": {
                                                        "$filter": {
                                                            "input": "$$posts",
                                                            "as": "post",
                                                            "cond": {
                                                                "$or": [
                                                                    {
                                                                        "$eq": [
                                                                            "$$post.paid_partnership",
                                                                            True,
                                                                        ]
                                                                    },
                                                                    {
                                                                        "$gt": [
                                                                            {
                                                                                "$size": {
                                                                                    "$ifNull": [
                                                                                        "$$post.sponsors",
                                                                                        [],
                                                                                    ]
                                                                                }
                                                                            },
                                                                            0,
                                                                        ]
                                                                    },
                                                                    {
                                                                        "$gt": [
                                                                            {
                                                                                "$size": {
                                                                                    "$ifNull": [
                                                                                        "$$post.tagged_users",
                                                                                        [],
                                                                                    ]
                                                                                }
                                                                            },
                                                                            0,
                                                                        ]
                                                                    },
                                                                    {
                                                                        "$gt": [
                                                                            {
                                                                                "$size": {
                                                                                    "$ifNull": [
                                                                                        "$$post.coauthors",
                                                                                        [],
                                                                                    ]
                                                                                }
                                                                            },
                                                                            0,
                                                                        ]
                                                                    },
                                                                    {
                                                                        "$gt": [
                                                                            {
                                                                                "$size": {
                                                                                    "$ifNull": [
                                                                                        "$$post.mentions",
                                                                                        [],
                                                                                    ]
                                                                                }
                                                                            },
                                                                            0,
                                                                        ]
                                                                    },
                                                                ]
                                                            },
                                                        }
                                                    },
                                                    "as": "post",
                                                    "in": {
                                                        "post_url": "$$post.post_url",
                                                        "paid_partnership": "$$post.paid_partnership",
                                                        "sponsors": "$$post.sponsors",
                                                        "tagged_users": "$$post.tagged_users",
                                                        "mentions": "$$post.mentions",
                                                        "coauthors": "$$post.coauthors",
                                                    },
                                                }
                                            },
                                        },
                                    ]
                                },
                            }
                        },
                    }
                }
            }
        },
        {
            "$set": {
                "summary": {
                    "competitor_count": {"$size": "$competitors"},
                    "total_posts": {
                        "$sum": {
                            "$map": {
                                "input": "$competitors",
                                "as": "competitor",
                                "in": "$$competitor.metrics.posts_in_window",
                            }
                        }
                    },
                    "paid_collaboration_posts": {
                        "$sum": {
                            "$map": {
                                "input": "$competitors",
                                "as": "competitor",
                                "in": "$$competitor.metrics.paid_collaboration_posts",
                            }
                        }
                    },
                }
            }
        },
        {"$unset": "_posts"},
    ]


def get_campaign_document(database, campaign_id: str) -> dict[str, Any] | None:
    return next(database.campaigns.aggregate(campaign_report_pipeline(campaign_id)), None)
