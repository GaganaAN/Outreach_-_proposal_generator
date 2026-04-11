"""
Opportunity Management API — view, score, and update sales opportunities
"""
import logging
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Opportunity, Notification
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


# ── Schemas ────────────────────────────────────────────────────────────────────

class OpportunityUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


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


# ── Opportunity Endpoints ──────────────────────────────────────────────────────

@router.get("/opportunities/")
async def list_opportunities(
    skip: int = 0,
    limit: int = 50,
    opp_status: Optional[str] = None,
    priority: Optional[str] = None,
    opportunity_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all opportunities with optional filters (admin auth required)."""
    query = db.query(Opportunity)
    if opp_status:
        query = query.filter(Opportunity.status == opp_status)
    if priority:
        query = query.filter(Opportunity.priority == priority)
    if opportunity_type:
        query = query.filter(Opportunity.opportunity_type == opportunity_type)
    total = query.count()
    opps = query.order_by(Opportunity.overall_score.desc(), Opportunity.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "opportunities": [o.to_dict() for o in opps]}


@router.get("/opportunities/stats/dashboard")
async def opportunity_stats(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Dashboard stats for the opportunities pipeline."""
    total        = db.query(Opportunity).count()
    high_prio    = db.query(Opportunity).filter(Opportunity.priority == "high").count()
    email_sent   = db.query(Opportunity).filter(Opportunity.status == "email_sent").count()
    proposals    = db.query(Opportunity).filter(Opportunity.opportunity_type == "proposal").count()
    closed       = db.query(Opportunity).filter(Opportunity.status == "closed").count()

    return {
        "total":          total,
        "high_priority":  high_prio,
        "email_sent":     email_sent,
        "proposals":      proposals,
        "closed":         closed,
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Get a single opportunity by ID (admin auth required)."""
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp.to_dict()


@router.put("/opportunities/{opportunity_id}")
async def update_opportunity(
    opportunity_id: int,
    payload: OpportunityUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update opportunity status or notes (admin auth required)."""
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    valid_statuses = {
        "new", "email_sent", "rfp_requested", "rfp_received", "proposal_sent", "closed"
    }
    if payload.status and payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")

    try:
        if payload.status is not None:
            opp.status = payload.status
        if payload.notes is not None:
            opp.notes = payload.notes
        db.commit()
        db.refresh(opp)
        return opp.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/opportunities/{opportunity_id}", status_code=status.HTTP_200_OK)
async def delete_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete an opportunity by ID (admin auth required)."""
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    db.delete(opp)
    db.commit()
    return {"message": f"Opportunity {opportunity_id} deleted"}


# ── Email Test ─────────────────────────────────────────────────────────────────

@router.post("/admin/test-email")
async def test_email_config(
    _: str = Depends(verify_admin),
):
    """Send a test email to MARKETING_EMAIL to verify SMTP configuration."""
    from app.services.notification_service import get_notification_service
    result = get_notification_service().test_email()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Notification Endpoints ─────────────────────────────────────────────────────

@router.get("/notifications/")
async def list_notifications(
    unread_only: bool = False,
    skip: int = 0,
    limit: int = 30,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List in-app notifications (admin auth required)."""
    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    total = query.count()
    unread_count = db.query(Notification).filter(Notification.is_read == False).count()
    notifs = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total":         total,
        "unread_count":  unread_count,
        "notifications": [n.to_dict() for n in notifs],
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Mark a notification as read (admin auth required)."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    return notif.to_dict()


@router.put("/notifications/read-all")
async def mark_all_notifications_read(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Mark all notifications as read (admin auth required)."""
    db.query(Notification).filter(Notification.is_read == False).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


# ── Daily Report ───────────────────────────────────────────────────────────────

@router.get("/admin/reports/daily-opportunities")
async def download_daily_report(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Generate and download the daily opportunity report as PDF (admin auth required)."""
    from datetime import datetime
    from app.services.report_generator import generate_daily_report

    try:
        pdf_bytes = generate_daily_report(db)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report")

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    filename = f"daily_opportunity_report_{date_str}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
