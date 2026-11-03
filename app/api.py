from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db import create_client, ensure_indexes, get_campaign_document, get_database
from app.models import (
    AnalysisWindow,
    CampaignCreate,
    CampaignDocument,
    CreateCampaignResponse,
    JobDocument,
)


client = create_client()
database = get_database(client)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_indexes(database)
    database.command("ping")
    yield
    client.close()


app = FastAPI(title="Competitor Monitoring Document API", lifespan=lifespan)


def _competitor_documents(request: CampaignCreate) -> list[dict]:
    return [
        {
            "username": competitor.username,
            "profile_url": f"https://www.instagram.com/{competitor.username}/",
            "profile_snapshot": None,
            "metrics": {},
            "best_posts": [],
            "collaborations": [],
        }
        for competitor in request.competitors
    ]


@app.get("/health")
def health() -> dict[str, str]:
    database.command("ping")
    return {"status": "ok"}


@app.post(
    "/campaigns",
    response_model=CreateCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_campaign(
    request: CampaignCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
) -> CreateCampaignResponse:
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be blank")
    max_posts = int(os.environ.get("MAX_POSTS_PER_COMPETITOR", "50"))
    if request.max_posts_per_competitor > max_posts:
        raise HTTPException(
            status_code=422,
            detail=f"max_posts_per_competitor cannot exceed the configured limit ({max_posts})",
        )

    existing_campaign = database.campaigns.find_one({"business_key": request.campaign_key})
    if existing_campaign:
        existing_job = database.jobs.find_one(
            {"campaign_id": existing_campaign["_id"], "idempotency_key": idempotency_key}
        )
        if existing_job:
            return CreateCampaignResponse(
                campaign_id=existing_campaign["_id"],
                job_id=existing_job["_id"],
                status=existing_job["status"],
            )

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=request.window_days)
    analysis = AnalysisWindow(
        start=window_start,
        end=now,
        window_days=request.window_days,
        max_posts_per_competitor=request.max_posts_per_competitor,
    )
    campaign = database.campaigns.find_one_and_update(
        {"business_key": request.campaign_key},
        {
            "$set": {
                "client_ref": request.client_ref,
                "analysis": analysis.model_dump(mode="python"),
                "competitors": _competitor_documents(request),
                "updated_at": now,
            },
            "$setOnInsert": {
                "_id": uuid.uuid4().hex,
                "type": "campaign",
                "schema_version": 1,
                "created_at": now,
                "status": "queued",
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    campaign_id = campaign["_id"]
    job_id = uuid.uuid4().hex
    job = {
        "_id": job_id,
        "type": "job",
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
        "campaign_id": campaign_id,
        "idempotency_key": idempotency_key,
        "status": "queued",
        "payload": request.model_dump(mode="python"),
        "window_start": window_start,
        "window_end": now,
        "attempts": 0,
        "apify_cost_usd": None,
        "apify_runs": [],
        "result_counts": {},
    }
    try:
        database.jobs.insert_one(job)
    except DuplicateKeyError:
        existing_job = database.jobs.find_one(
            {"campaign_id": campaign_id, "idempotency_key": idempotency_key}
        )
        if existing_job is None:
            raise
        return CreateCampaignResponse(
            campaign_id=campaign_id,
            job_id=existing_job["_id"],
            status=existing_job["status"],
        )

    database.campaigns.update_one(
        {"_id": campaign_id}, {"$set": {"status": "queued", "updated_at": now}}
    )
    return CreateCampaignResponse(campaign_id=campaign_id, job_id=job_id, status="queued")


@app.get("/campaigns/{campaign_id}", response_model=CampaignDocument)
def get_campaign(campaign_id: str) -> CampaignDocument:
    document = get_campaign_document(database, campaign_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignDocument.model_validate(document)


@app.get("/jobs/{job_id}", response_model=JobDocument)
def get_job(job_id: str) -> JobDocument:
    document = database.jobs.find_one({"_id": job_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDocument.model_validate(document)
