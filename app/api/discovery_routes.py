"""
Lead Discovery API — manage discovery sources and trigger scans
"""
import logging
import json
import secrets
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import DiscoverySource, Signal
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


# ── Schemas ────────────────────────────────────────────────────────────────────

class DiscoverySourceCreate(BaseModel):
    name: str
    url: str
    source_type: str                     # job_board | procurement | news
    scan_interval_hours: int = 24
    keywords: List[str] = []
    is_active: bool = True


class DiscoverySourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    source_type: Optional[str] = None
    scan_interval_hours: Optional[int] = None
    keywords: Optional[List[str]] = None
    is_active: Optional[bool] = None


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


# ── Source CRUD ────────────────────────────────────────────────────────────────

@router.get("/discovery/sources")
async def list_sources(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all configured discovery sources (admin auth required)."""
    sources = db.query(DiscoverySource).order_by(DiscoverySource.created_at.desc()).all()
    return {"total": len(sources), "sources": [s.to_dict() for s in sources]}


@router.post("/discovery/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: DiscoverySourceCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Add a new discovery source (admin auth required)."""
    valid_types = {"job_board", "procurement", "news"}
    if payload.source_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {valid_types}")

    try:
        source = DiscoverySource(
            name=payload.name,
            url=payload.url,
            source_type=payload.source_type,
            scan_interval_hours=payload.scan_interval_hours,
            keywords=json.dumps(payload.keywords),
            is_active=payload.is_active,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info(f"[Discovery] Created source: {source.name}")
        return source.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/discovery/sources/{source_id}")
async def update_source(
    source_id: int,
    payload: DiscoverySourceUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update a discovery source (admin auth required)."""
    source = db.query(DiscoverySource).filter(DiscoverySource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Discovery source not found")

    try:
        if payload.name is not None:
            source.name = payload.name
        if payload.url is not None:
            source.url = payload.url
        if payload.source_type is not None:
            source.source_type = payload.source_type
        if payload.scan_interval_hours is not None:
            source.scan_interval_hours = payload.scan_interval_hours
        if payload.keywords is not None:
            source.keywords = json.dumps(payload.keywords)
        if payload.is_active is not None:
            source.is_active = payload.is_active
        db.commit()
        db.refresh(source)
        return source.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/discovery/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a discovery source (admin auth required)."""
    source = db.query(DiscoverySource).filter(DiscoverySource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Discovery source not found")
    try:
        db.delete(source)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── Scan Trigger ───────────────────────────────────────────────────────────────

@router.post("/discovery/sources/{source_id}/scan-now")
async def scan_source_now(
    source_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Manually trigger a scan for a specific source (runs in background)."""
    source = db.query(DiscoverySource).filter(DiscoverySource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Discovery source not found")

    background_tasks.add_task(_run_scan, source_id)
    return {"message": f"Scan started for '{source.name}'", "source_id": source_id}


def _run_scan(source_id: int):
    """Background task: scan one source."""
    from app.database import SessionLocal
    from app.services.lead_discovery import get_lead_discovery_agent

    db = SessionLocal()
    try:
        from app.models import DiscoverySource
        source = db.query(DiscoverySource).filter(DiscoverySource.id == source_id).first()
        if not source:
            return
        agent = get_lead_discovery_agent()
        count = agent.scan_source(source, db)
        from datetime import datetime
        source.last_scanned_at = datetime.utcnow()
        db.commit()
        logger.info(f"[Discovery] Manual scan of '{source.name}' created {count} signal(s)")
    except Exception as e:
        logger.error(f"[Discovery] Manual scan failed: {e}")
    finally:
        db.close()


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/discovery/stats")
async def discovery_stats(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Stats: sources configured, signals found per source type."""
    total_sources = db.query(DiscoverySource).count()
    active_sources = db.query(DiscoverySource).filter(DiscoverySource.is_active == True).count()
    total_signals = db.query(Signal).count()

    sources = db.query(DiscoverySource).all()
    source_list = [
        {
            "id":             s.id,
            "name":           s.name,
            "source_type":    s.source_type,
            "is_active":      s.is_active,
            "last_scanned_at": s.last_scanned_at.isoformat() if s.last_scanned_at else None,
        }
        for s in sources
    ]

    return {
        "total_sources":  total_sources,
        "active_sources": active_sources,
        "total_signals":  total_signals,
        "sources":        source_list,
    }
