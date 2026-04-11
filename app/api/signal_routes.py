"""
Signal Management API — view and manage auto-discovered signals
"""
import logging
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Signal
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


# ── Schemas ────────────────────────────────────────────────────────────────────

class SignalStatusUpdate(BaseModel):
    status: str         # new | processed | ignored


# ── Auth ───────────────────────────────────────────────────────────────────────

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    settings = get_settings()
    ok_user = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/signals/")
async def list_signals(
    skip: int = 0,
    limit: int = 50,
    signal_type: Optional[str] = None,
    signal_status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all auto-discovered signals (admin auth required)."""
    query = db.query(Signal)
    if signal_type:
        query = query.filter(Signal.signal_type == signal_type)
    if signal_status:
        query = query.filter(Signal.status == signal_status)
    total = query.count()
    signals = query.order_by(Signal.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "signals": [s.to_dict() for s in signals]}


@router.put("/signals/{signal_id}/status")
async def update_signal_status(
    signal_id: int,
    payload: SignalStatusUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update signal status (admin auth required)."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    valid_statuses = {"new", "processed", "ignored"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")
    signal.status = payload.status
    db.commit()
    return signal.to_dict()


@router.delete("/signals/{signal_id}", status_code=status.HTTP_200_OK)
async def delete_signal(
    signal_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a signal by ID (admin auth required)."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    db.delete(signal)
    db.commit()
    return {"message": f"Signal {signal_id} deleted"}


@router.get("/signals/stats")
async def signal_stats(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Signal type counts for dashboard."""
    from sqlalchemy import func
    rows = db.query(Signal.signal_type, func.count(Signal.id)).group_by(Signal.signal_type).all()
    counts = {row[0]: row[1] for row in rows}
    return {
        "total":            sum(counts.values()),
        "job_hiring":       counts.get("job_hiring", 0),
        "rfp_opportunity":  counts.get("rfp_opportunity", 0),
        "service_request":  counts.get("service_request", 0),
        "other":            counts.get("other", 0),
    }
