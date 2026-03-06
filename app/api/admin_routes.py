"""
Admin routes for Portfolio Management Dashboard
All endpoints require HTTP Basic Auth (ADMIN_USERNAME / ADMIN_PASSWORD from .env)
"""
import logging
import secrets
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Portfolio
from app.config import get_settings
from app.core.vector_store import get_vector_store

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


# ── Pydantic Schemas ───────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    skill: str
    portfolio_link: str
    projects: List[str]
    description: Optional[str] = ""
    image_url: Optional[str] = None


class PortfolioUpdate(BaseModel):
    skill: Optional[str] = None
    portfolio_link: Optional[str] = None
    projects: Optional[List[str]] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


# ── Auth helper ────────────────────────────────────────────────────────────────

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Constant-time compare to prevent timing attacks"""
    settings = get_settings()
    ok_user = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.get("/portfolios")
async def list_portfolios(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all portfolio entries"""
    rows = db.query(Portfolio).order_by(Portfolio.created_at.desc()).offset(skip).limit(limit).all()
    return [r.to_dict() for r in rows]


@router.get("/portfolios/{portfolio_id}")
async def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Get a single portfolio entry by ID"""
    row = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return row.to_dict()


@router.post("/portfolios", status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    payload: PortfolioCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Create a new portfolio entry and sync to vector store"""
    try:
        row = Portfolio(
            skill=payload.skill,
            portfolio_link=payload.portfolio_link,
            projects="|".join(payload.projects),
            description=payload.description or "",
            image_url=payload.image_url,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Also add to vector store for immediate use
        vs = get_vector_store()
        vs.add_portfolio(
            skill=payload.skill,
            portfolio_link=payload.portfolio_link,
            projects=payload.projects,
            description=payload.description or "",
        )

        logger.info(f"[Admin] Created portfolio: {payload.skill}")
        return row.to_dict()

    except Exception as e:
        db.rollback()
        logger.error(f"[Admin] Create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/portfolios/{portfolio_id}")
async def update_portfolio(
    portfolio_id: int,
    payload: PortfolioUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update portfolio entry — partial update supported"""
    row = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    try:
        if payload.skill is not None:
            row.skill = payload.skill
        if payload.portfolio_link is not None:
            row.portfolio_link = payload.portfolio_link
        if payload.projects is not None:
            row.projects = "|".join(payload.projects)
        if payload.description is not None:
            row.description = payload.description
        if payload.image_url is not None:
            row.image_url = payload.image_url

        db.commit()
        db.refresh(row)
        logger.info(f"[Admin] Updated portfolio id={portfolio_id}")
        return row.to_dict()

    except Exception as e:
        db.rollback()
        logger.error(f"[Admin] Update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/portfolios/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a portfolio entry from DB (sync separately to reflect in vector store)"""
    row = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    try:
        db.delete(row)
        db.commit()
        logger.info(f"[Admin] Deleted portfolio id={portfolio_id}")
        return None

    except Exception as e:
        db.rollback()
        logger.error(f"[Admin] Delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Vector Store Sync ──────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_vector_store(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    Rebuild vector store from database.
    Call this after bulk edits/deletes to keep ChromaDB in sync.
    """
    try:
        vs = get_vector_store()
        vs.reset_collection()

        rows = db.query(Portfolio).all()
        for row in rows:
            vs.add_portfolio(
                skill=row.skill,
                portfolio_link=row.portfolio_link,
                projects=row.projects.split("|"),
                description=row.description or "",
            )

        logger.info(f"[Admin] Synced {len(rows)} portfolios to vector store")
        return {"message": "Vector store rebuilt successfully", "synced_count": len(rows)}

    except Exception as e:
        logger.error(f"[Admin] Sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_admin_stats(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Dashboard stats card data"""
    db_count = db.query(Portfolio).count()
    vs = get_vector_store()
    vs_count = vs.count_documents()

    skills = [r.skill for r in db.query(Portfolio.skill).all()]

    return {
        "db_portfolio_count":     db_count,
        "vector_store_count":     vs_count,
        "in_sync":                db_count == vs_count,
        "skills":                 skills,
    }