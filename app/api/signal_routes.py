"""
Signal Classification API — classify internet signals and route to email or proposal workflow
"""
import logging
import json
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Signal, Opportunity, Notification
from app.services.signal_classifier import get_signal_classifier
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


# ── Schemas ────────────────────────────────────────────────────────────────────

class SignalClassifyRequest(BaseModel):
    input: str          # URL or free text
    source_url: Optional[str] = None


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

@router.post("/signals/classify", status_code=status.HTTP_201_CREATED)
async def classify_signal(
    request: SignalClassifyRequest,
    db: Session = Depends(get_db),
):
    """
    Classify a signal (URL or text) and save to DB.

    - job_hiring       → suggests generating a cold outreach email
    - rfp_opportunity  → triggers marketing notification + creates Opportunity
    - service_request  → triggers marketing notification + creates Opportunity
    - other            → saved but no action taken
    """
    try:
        classifier = get_signal_classifier()
        result = classifier.classify(request.input, source_url=request.source_url)

        # Persist Signal
        signal = Signal(
            source_url=result.source_url,
            raw_text=result.raw_text,
            signal_type=result.signal_type,
            company_name=result.company_name,
            detected_skills=json.dumps(result.detected_skills),
            confidence_score=result.confidence_score,
            status="new",
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)

        opportunity = None
        notification = None

        # For non-trivial signals, create an Opportunity
        if result.signal_type != "other" and result.confidence_score >= 0.4:
            opp_type = (
                "email_outreach" if result.signal_type == "job_hiring" else "proposal"
            )

            # Score the opportunity
            skill_match_score = 0.0
            if result.detected_skills:
                try:
                    from app.services.opportunity_scorer import get_opportunity_scorer
                    scorer = get_opportunity_scorer()
                    scores = scorer.score_from_skills(result.detected_skills)
                    skill_match_score = scores["skill_match_score"]
                except Exception as score_err:
                    logger.warning(f"Scoring failed, defaulting to 0: {score_err}")

            signal_strength = result.confidence_score
            overall_score = round(0.6 * skill_match_score + 0.4 * signal_strength, 3)
            priority = (
                "high" if overall_score >= 0.7
                else "medium" if overall_score >= 0.4
                else "low"
            )

            opportunity = Opportunity(
                signal_id=signal.id,
                company_name=result.company_name,
                source_url=result.source_url,
                opportunity_type=opp_type,
                skill_match_score=skill_match_score,
                signal_strength=signal_strength,
                overall_score=overall_score,
                priority=priority,
                status="new",
            )
            db.add(opportunity)
            db.commit()
            db.refresh(opportunity)

            # For proposal-type signals, send marketing notification
            if result.signal_type in ("rfp_opportunity", "service_request"):
                try:
                    from app.services.notification_service import get_notification_service
                    notif_service = get_notification_service()
                    notification = notif_service.notify_opportunity(opportunity, result, db)
                except Exception as notif_err:
                    logger.warning(f"Notification failed (non-critical): {notif_err}")

        # Update signal status
        signal.status = "processed" if opportunity else "new"
        db.commit()

        return {
            "signal":      signal.to_dict(),
            "opportunity": opportunity.to_dict() if opportunity else None,
            "notification_sent": notification is not None,
            "suggested_action": _suggest_action(result.signal_type, result.confidence_score),
        }

    except Exception as e:
        logger.error(f"Signal classification endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/")
async def list_signals(
    skip: int = 0,
    limit: int = 50,
    signal_type: Optional[str] = None,
    signal_status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all classified signals (admin auth required)."""
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _suggest_action(signal_type: str, confidence: float) -> str:
    if confidence < 0.4:
        return "low_confidence_review_manually"
    mapping = {
        "job_hiring":      "generate_cold_email",
        "rfp_opportunity": "request_rfp_document",
        "service_request": "contact_client_directly",
        "other":           "no_action",
    }
    return mapping.get(signal_type, "no_action")
