"""
Past Performance API — CRUD for PastProject records (admin auth required)
"""
import json
import logging
import secrets
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import PastProject
from app.config import get_settings

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

class PastProjectCreate(BaseModel):
    title: str
    client_name: Optional[str] = None
    industry: Optional[str] = None
    project_type: Optional[str] = None
    problem_statement: Optional[str] = None
    our_solution: Optional[str] = None
    technologies: Optional[List[str]] = []
    outcome: Optional[str] = None
    team_size: Optional[int] = None
    duration_months: Optional[int] = None
    start_year: Optional[int] = None
    is_active: bool = True


class PastProjectUpdate(BaseModel):
    title: Optional[str] = None
    client_name: Optional[str] = None
    industry: Optional[str] = None
    project_type: Optional[str] = None
    problem_statement: Optional[str] = None
    our_solution: Optional[str] = None
    technologies: Optional[List[str]] = None
    outcome: Optional[str] = None
    team_size: Optional[int] = None
    duration_months: Optional[int] = None
    start_year: Optional[int] = None
    is_active: Optional[bool] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/past-projects/")
async def list_past_projects(
    skip: int = 0,
    limit: int = 50,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all past performance projects."""
    query = db.query(PastProject)
    if active_only:
        query = query.filter(PastProject.is_active == True)
    total = query.count()
    projects = query.order_by(PastProject.start_year.desc()).offset(skip).limit(limit).all()
    return {"total": total, "projects": [p.to_dict() for p in projects]}


@router.post("/past-projects/", status_code=status.HTTP_201_CREATED)
async def create_past_project(
    payload: PastProjectCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Create a new past performance record."""
    project = PastProject(
        title=payload.title,
        client_name=payload.client_name,
        industry=payload.industry,
        project_type=payload.project_type,
        problem_statement=payload.problem_statement,
        our_solution=payload.our_solution,
        technologies=json.dumps(payload.technologies or []),
        outcome=payload.outcome,
        team_size=payload.team_size,
        duration_months=payload.duration_months,
        start_year=payload.start_year,
        is_active=payload.is_active,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.to_dict()


@router.get("/past-projects/{project_id}")
async def get_past_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Get a single past performance record."""
    project = db.query(PastProject).filter(PastProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.put("/past-projects/{project_id}")
async def update_past_project(
    project_id: int,
    payload: PastProjectUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update a past performance record."""
    project = db.query(PastProject).filter(PastProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "technologies":
            setattr(project, field, json.dumps(value or []))
        else:
            setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project.to_dict()


@router.delete("/past-projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_past_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a past performance record."""
    project = db.query(PastProject).filter(PastProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return None
