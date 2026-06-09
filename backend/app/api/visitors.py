"""
NexusIQ — api/visitors.py

Visitor tracking and onboarding API.

Endpoints:
  POST /api/visitors/register   — save visitor name + email
  GET  /api/visitors/stats      — aggregate visitor counts (admin view)
  POST /api/visitors/event      — track a UI interaction event

Data is stored in data/visitors.jsonl (one JSON record per line).
No external analytics service required — fully self-hosted.

For production: these endpoints can be augmented with
Google Analytics server-side events or a proper DB later.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger("nexusiq.visitors")
router = APIRouter()

VISITORS_FILE = Path("./data/visitors.jsonl")
EVENTS_FILE   = Path("./data/visitor_events.jsonl")


# ── Schemas ────────────────────────────────────────────────────────

class VisitorRegister(BaseModel):
    name:  str           = Field(..., min_length=1, max_length=120)
    email: Optional[str] = Field(default=None, max_length=254)


class VisitorEvent(BaseModel):
    event:      str            = Field(..., min_length=1, max_length=80)
    properties: dict           = Field(default_factory=dict)
    visitor_id: Optional[str]  = Field(default=None)


class RegisterResponse(BaseModel):
    success:    bool
    message:    str
    visitor_id: str


class StatsResponse(BaseModel):
    total_visitors:   int
    total_events:     int
    recent_visitors:  list


# ── Helpers ────────────────────────────────────────────────────────

def _append_jsonl(filepath: Path, record: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _read_jsonl(filepath: Path) -> list:
    if not filepath.exists():
        return []
    records = []
    try:
        for line in filepath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as exc:
        logger.error("Failed to read %s: %s", filepath, exc)
    return records


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Endpoints ─────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a visitor — saves name and optional email",
)
async def register_visitor(
    body:    VisitorRegister,
    request: Request,
) -> RegisterResponse:
    """
    Called when the frontend onboarding modal is submitted.
    Saves visitor info to data/visitors.jsonl.
    Returns a visitor_id for subsequent event tracking.
    """
    import hashlib

    ts         = datetime.now(timezone.utc).isoformat()
    ip         = _client_ip(request)
    visitor_id = hashlib.sha256(f"{body.email or body.name}{ts}".encode()).hexdigest()[:16]

    record = {
        "visitor_id": visitor_id,
        "name":       body.name,
        "email":      body.email,
        "ip":         ip,
        "user_agent": request.headers.get("user-agent", "")[:200],
        "timestamp":  ts,
    }

    _append_jsonl(VISITORS_FILE, record)
    logger.info("Visitor registered: name='%s' id=%s", body.name, visitor_id)

    return RegisterResponse(
        success=    True,
        message=    f"Welcome, {body.name}!",
        visitor_id= visitor_id,
    )


@router.post(
    "/event",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Track a visitor interaction event",
)
async def track_event(
    body:    VisitorEvent,
    request: Request,
) -> None:
    """
    Track UI events: pdf_uploaded, query_asked, evaluation_run, etc.
    Appended to data/visitor_events.jsonl.
    """
    record = {
        "event":      body.event,
        "properties": body.properties,
        "visitor_id": body.visitor_id,
        "ip":         _client_ip(request),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
    _append_jsonl(EVENTS_FILE, record)
    logger.debug("Event tracked: %s | visitor=%s", body.event, body.visitor_id)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Visitor statistics — total counts and recent visitors",
)
async def visitor_stats() -> StatsResponse:
    """
    Returns aggregate visitor stats.
    Intended for the project author / admin — not exposed to end users.
    """
    visitors = _read_jsonl(VISITORS_FILE)
    events   = _read_jsonl(EVENTS_FILE)

    recent = [
        {
            "name":      v.get("name"),
            "email":     v.get("email"),
            "timestamp": v.get("timestamp"),
        }
        for v in sorted(visitors, key=lambda x: x.get("timestamp", ""), reverse=True)[:20]
    ]

    return StatsResponse(
        total_visitors=  len(visitors),
        total_events=    len(events),
        recent_visitors= recent,
    )