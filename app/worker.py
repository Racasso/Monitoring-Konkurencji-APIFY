from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, ReturnDocument

from app.apify import fetch_campaign_data, profile_url
from app.db import create_client, ensure_indexes, get_database, upsert_posts
from app.models import CampaignCreate


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("competitor_monitoring.worker")


def recover_stale_jobs(database) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    database.jobs.update_many(
        {"status": "running", "claimed_at": {"$lt": cutoff}, "attempts": {"$lt": 3}},
        {
            "$set": {"status": "queued", "updated_at": now},
            "$unset": {"claimed_at": ""},
        },
    )
    database.jobs.update_many(
        {"status": "running", "claimed_at": {"$lt": cutoff}, "attempts": {"$gte": 3}},
        {
            "$set": {
                "status": "failed",
                "error_type": "WorkerLeaseExpired",
                "completed_at": now,
                "updated_at": now,
            }
        },
    )


def claim_job(database) -> dict | None:
    now = datetime.now(timezone.utc)
    return database.jobs.find_one_and_update(
        {"status": "queued"},
        {
            "$set": {"status": "running", "claimed_at": now, "started_at": now, "updated_at": now},
            "$inc": {"attempts": 1},
        },
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


def process_job(database, job: dict) -> None:
    now = datetime.now(timezone.utc)
    campaign_id = job["campaign_id"]
    payload = CampaignCreate.model_validate(job["payload"])
    campaign = database.campaigns.find_one({"_id": campaign_id})
    if campaign is None:
        raise RuntimeError("Campaign document is missing")

    result = fetch_campaign_data(
        payload,
        campaign_id=campaign_id,
        window_start=job["window_start"],
    )
    result_counts = {
        "posts": len(result["posts"]),
        "profiles": len(result["profiles"]),
        "post_errors": result["post_errors"],
        "profile_errors": result["profile_errors"],
    }
    database.jobs.update_one(
        {"_id": job["_id"], "status": "running"},
        {
            "$set": {
                "apify_cost_usd": result["apify_cost_usd"],
                "apify_runs": result["apify_runs"],
                "result_counts": result_counts,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    upsert_posts(database.posts, result["posts"])

    updated_competitors = []
    for competitor in payload.competitors:
        username = competitor.username
        snapshot = result["profiles"].get(username)
        updated_competitors.append(
            {
                "username": username,
                "profile_url": profile_url(username),
                "profile_snapshot": snapshot.model_dump(mode="python") if snapshot else None,
                "metrics": {},
                "best_posts": [],
                "collaborations": [],
            }
        )

    database.campaigns.update_one(
        {"_id": campaign_id, "updated_at": {"$lte": job["created_at"]}},
        {
            "$set": {
                "competitors": updated_competitors,
                "analysis.start": job["window_start"],
                "analysis.end": job["window_end"],
                "status": "done",
                "last_completed_at": now,
                "updated_at": now,
            }
        },
    )

    database.jobs.update_one(
        {"_id": job["_id"], "status": "running"},
        {
            "$set": {
                "status": "done",
                "apify_cost_usd": result["apify_cost_usd"],
                "apify_runs": result["apify_runs"],
                "result_counts": result_counts,
                "completed_at": now,
                "updated_at": now,
            },
            "$unset": {"claimed_at": ""},
        },
    )


def run_once(database) -> bool:
    recover_stale_jobs(database)
    job = claim_job(database)
    if job is None:
        return False
    try:
        process_job(database, job)
        logger.info("job_done job_id=%s", job["_id"])
    except Exception as error:  # The exception text may contain remote request details.
        now = datetime.now(timezone.utc)
        database.jobs.update_one(
            {"_id": job["_id"], "status": "running"},
            {
                "$set": {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "completed_at": now,
                    "updated_at": now,
                },
                "$unset": {"claimed_at": ""},
            },
        )
        database.campaigns.update_one(
            {"_id": job["campaign_id"], "updated_at": {"$lte": job["created_at"]}},
            {"$set": {"status": "failed", "updated_at": now}},
        )
        logger.error("job_failed job_id=%s error_type=%s", job["_id"], type(error).__name__)
    return True


def main() -> None:
    client = create_client()
    database = get_database(client)
    ensure_indexes(database)
    database.command("ping")
    poll_seconds = float(os.environ.get("WORKER_POLL_SECONDS", "2"))
    logger.info("worker_started")
    try:
        while True:
            if not run_once(database):
                time.sleep(poll_seconds)
    finally:
        client.close()


if __name__ == "__main__":
    main()
