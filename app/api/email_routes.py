"""
Email tracking routes for managing generated emails
"""
import logging
import json
import csv
import io
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from pydantic import BaseModel
import secrets

from app.database import get_db
from app.models import Email
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()
settings = get_settings()


# ── Schemas ────────────────────────────────────────────────────────────────

class EmailCreate(BaseModel):
    job_url: str
    company_name: Optional[str] = None
    job_role: str
    email_subject: str
    email_body: str
    skills: List[str] = []
    matched_portfolios: List[dict] = []


class EmailUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    sent_at: Optional[str] = None
    responded_at: Optional[str] = None


# ── Auth ───────────────────────────────────────────────────────────────────

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials (same as portfolio manager)"""
    ok_user = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── Utilities ──────────────────────────────────────────────────────────────

def extract_company_from_url(url: str) -> str:
    """Extract company name from job URL"""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        # Remove common prefixes/suffixes
        domain = domain.replace('www.', '').replace('jobs.', '').replace('careers.', '')
        # Get the main domain name
        parts = domain.split('.')
        if len(parts) >= 2:
            company = parts[0] if parts[0] not in ['com', 'co', 'org'] else parts[1]
            return company.capitalize()
        return domain.capitalize()
    except:
        return "Unknown"


# ── CRUD Endpoints ─────────────────────────────────────────────────────────

@router.get("/emails")
async def list_emails(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    company: Optional[str] = None,
    search: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """
    List all emails with optional filters
    
    Filters:
    - status: draft/sent/responded/interested/not_interested
    - company: company name (partial match)
    - search: search in job_role, email_subject, company_name
    - from/to: date range filter (YYYY-MM-DD)
    """
    query = db.query(Email)
    
    # Apply filters
    if status:
        query = query.filter(Email.status == status)
    
    if company:
        query = query.filter(Email.company_name.ilike(f"%{company}%"))
    
    if search:
        query = query.filter(
            or_(
                Email.job_role.ilike(f"%{search}%"),
                Email.email_subject.ilike(f"%{search}%"),
                Email.company_name.ilike(f"%{search}%")
            )
        )
    
    if from_date:
        query = query.filter(Email.generated_at >= from_date)
    
    if to_date:
        # Add 1 day to include the entire to_date
        query = query.filter(Email.generated_at < to_date + " 23:59:59")
    
    # Order by most recent first
    query = query.order_by(Email.generated_at.desc())
    
    # Paginate
    total = query.count()
    emails = query.offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "emails": [email.to_dict() for email in emails]
    }


@router.get("/emails/{email_id}")
async def get_email(
    email_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """Get a single email by ID"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email.to_dict()


@router.post("/emails", status_code=status.HTTP_201_CREATED)
async def create_email(
    payload: EmailCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new email record (called automatically after email generation)
    No auth required - this is called by the public email generator
    """
    try:
        # Extract company name if not provided
        company = payload.company_name
        if not company or company == "Unknown":
            company = extract_company_from_url(payload.job_url)
        
        # Create email record
        email = Email(
            job_url=payload.job_url,
            company_name=company,
            job_role=payload.job_role,
            email_subject=payload.email_subject,
            email_body=payload.email_body,
            skills=json.dumps(payload.skills),
            matched_portfolios=json.dumps(payload.matched_portfolios),
            status="draft"
        )
        
        db.add(email)
        db.commit()
        db.refresh(email)
        
        logger.info(f"Created email record: {email.id} - {company} - {payload.job_role}")
        return email.to_dict()
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/emails/{email_id}")
async def update_email(
    email_id: int,
    payload: EmailUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """Update email status, notes, or timestamps"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    try:
        # Update fields if provided
        if payload.status is not None:
            email.status = payload.status
            
            # Auto-set timestamps based on status
            if payload.status == "sent" and not email.sent_at:
                email.sent_at = datetime.utcnow()
            elif payload.status == "responded" and not email.responded_at:
                email.responded_at = datetime.utcnow()
        
        if payload.notes is not None:
            email.notes = payload.notes
        
        if payload.sent_at:
            email.sent_at = datetime.fromisoformat(payload.sent_at.replace('Z', '+00:00'))
        
        if payload.responded_at:
            email.responded_at = datetime.fromisoformat(payload.responded_at.replace('Z', '+00:00'))
        
        db.commit()
        db.refresh(email)
        
        logger.info(f"Updated email {email_id}: status={payload.status}")
        return email.to_dict()
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/emails/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email(
    email_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """Delete an email record"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    try:
        db.delete(email)
        db.commit()
        logger.info(f"Deleted email {email_id}")
        return None
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Stats Endpoint ─────────────────────────────────────────────────────────

@router.get("/emails/stats/dashboard")
async def get_email_stats(
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """Get statistics for the dashboard"""
    total = db.query(Email).count()
    sent = db.query(Email).filter(Email.status == "sent").count()
    responded = db.query(Email).filter(Email.status == "responded").count()
    interested = db.query(Email).filter(Email.status == "interested").count()
    
    # Calculate response rate
    response_rate = round((responded / sent * 100) if sent > 0 else 0, 1)
    
    # Get recent activity (last 7 days)
    from datetime import timedelta
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent = db.query(Email).filter(Email.generated_at >= week_ago).count()
    
    return {
        "total_generated": total,
        "total_sent": sent,
        "total_responded": responded,
        "total_interested": interested,
        "response_rate": response_rate,
        "recent_week": recent
    }


# ── Export Endpoint ────────────────────────────────────────────────────────

@router.get("/emails/export/csv")
async def export_emails_csv(
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """Export emails to CSV with optional filters"""
    query = db.query(Email)
    
    # Apply same filters as list endpoint
    if status:
        query = query.filter(Email.status == status)
    if from_date:
        query = query.filter(Email.generated_at >= from_date)
    if to_date:
        query = query.filter(Email.generated_at < to_date + " 23:59:59")
    
    emails = query.order_by(Email.generated_at.desc()).all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'generated_at', 'company', 'job_role', 'job_url', 'status',
        'email_subject', 'sent_at', 'responded_at', 'notes'
    ])
    
    # Write data
    for email in emails:
        writer.writerow([
            email.generated_at.strftime('%Y-%m-%d %H:%M') if email.generated_at else '',
            email.company_name or '',
            email.job_role or '',
            email.job_url or '',
            email.status or '',
            email.email_subject or '',
            email.sent_at.strftime('%Y-%m-%d %H:%M') if email.sent_at else '',
            email.responded_at.strftime('%Y-%m-%d %H:%M') if email.responded_at else '',
            email.notes or ''
        ])
    
    # Prepare response
    output.seek(0)
    filename = f"email_history_{datetime.now().strftime('%Y-%m-%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )