"""
Keyword Set Management API

Endpoints (all require admin auth):
  GET    /api/admin/keyword-sets/           list all sets
  POST   /api/admin/keyword-sets/           create new set
  GET    /api/admin/keyword-sets/{id}       get single set
  PUT    /api/admin/keyword-sets/{id}       update name + keywords
  POST   /api/admin/keyword-sets/{id}/activate   make this set active (deactivates others)
  DELETE /api/admin/keyword-sets/{id}       delete a set
"""
import json
import logging
import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.keywords import normalize_keywords
from app.database import get_db
from app.models import KeywordSet

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()


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


# ── Schemas ────────────────────────────────────────────────────────────────────

class KeywordSetCreate(BaseModel):
    name: str
    keywords: List[str] = []
    is_active: bool = False


class KeywordSetUpdate(BaseModel):
    name: Optional[str] = None
    keywords: Optional[List[str]] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/keyword-sets/")
async def list_keyword_sets(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all keyword sets."""
    sets = db.query(KeywordSet).order_by(KeywordSet.is_active.desc(), KeywordSet.created_at.desc()).all()
    return {"keyword_sets": [s.to_dict() for s in sets]}


@router.post("/keyword-sets/", status_code=status.HTTP_201_CREATED)
async def create_keyword_set(
    payload: KeywordSetCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Create a new keyword set. If is_active=True, deactivates all others."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")

    existing = db.query(KeywordSet).filter(KeywordSet.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A keyword set named '{name}' already exists")

    if payload.is_active:
        db.query(KeywordSet).update({"is_active": False})

    normalized_keywords = normalize_keywords(payload.keywords)
    ks = KeywordSet(
        name=name,
        keywords=json.dumps(normalized_keywords),
        is_active=payload.is_active,
    )
    db.add(ks)
    db.commit()
    db.refresh(ks)
    return ks.to_dict()


@router.get("/keyword-sets/{keyword_set_id}")
async def get_keyword_set(
    keyword_set_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    ks = db.query(KeywordSet).filter(KeywordSet.id == keyword_set_id).first()
    if not ks:
        raise HTTPException(status_code=404, detail="Keyword set not found")
    return ks.to_dict()


@router.put("/keyword-sets/{keyword_set_id}")
async def update_keyword_set(
    keyword_set_id: int,
    payload: KeywordSetUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update name and/or keywords of an existing set."""
    ks = db.query(KeywordSet).filter(KeywordSet.id == keyword_set_id).first()
    if not ks:
        raise HTTPException(status_code=404, detail="Keyword set not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        conflict = db.query(KeywordSet).filter(
            KeywordSet.name == name,
            KeywordSet.id != keyword_set_id
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"A keyword set named '{name}' already exists")
        ks.name = name

    if payload.keywords is not None:
        ks.keywords = json.dumps(normalize_keywords(payload.keywords))

    try:
        db.commit()
        db.refresh(ks)
        return ks.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keyword-sets/{keyword_set_id}/activate")
async def activate_keyword_set(
    keyword_set_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Make this keyword set active; deactivates all others."""
    ks = db.query(KeywordSet).filter(KeywordSet.id == keyword_set_id).first()
    if not ks:
        raise HTTPException(status_code=404, detail="Keyword set not found")

    try:
        db.query(KeywordSet).update({"is_active": False})
        ks.is_active = True
        db.commit()
        db.refresh(ks)
        return ks.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/keyword-sets/{keyword_set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword_set(
    keyword_set_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a keyword set."""
    ks = db.query(KeywordSet).filter(KeywordSet.id == keyword_set_id).first()
    if not ks:
        raise HTTPException(status_code=404, detail="Keyword set not found")
    try:
        db.delete(ks)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
