"""
Proposal Generation API — upload RFP documents and generate structured proposals
"""
import logging
import json
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Proposal
from app.services.rfp_parser import get_rfp_parser
from app.services.proposal_generator import get_proposal_generator
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProposalUpdate(BaseModel):
    status: Optional[str] = None
    proposal_content: Optional[dict] = None


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

@router.post("/proposals/upload", status_code=status.HTTP_201_CREATED)
async def upload_rfp_and_generate(
    file: UploadFile = File(..., description="RFP document (PDF, DOCX, or TXT)"),
    opportunity_id: Optional[int] = Form(None),
    llm_provider: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    Upload an RFP document and auto-generate a technical proposal.

    Supported formats: PDF, DOCX, TXT
    """
    # Validate file size
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # Validate file extension
    allowed_exts = {".pdf", ".docx", ".txt", ".eml", ".md"}
    filename = file.filename or "upload.txt"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(allowed_exts)}"
        )

    try:
        # Parse document
        parser = get_rfp_parser()
        rfp_text = parser.parse(file_bytes, filename)

        if not rfp_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from the document")

        # Generate proposal (pass db for past performance lookup)
        generator = get_proposal_generator()
        result = generator.generate(
            rfp_text,
            opportunity_id=opportunity_id,
            llm_provider=llm_provider,
            db=db,
        )

        # Return early if no matching past performance found
        if result.get("no_match"):
            return {
                "no_match": True,
                "message": result["message"],
                "extraction_metadata": result.get("extraction", {}),
            }

        # Save to DB
        proposal = Proposal(
            opportunity_id=opportunity_id,
            rfp_filename=filename,
            rfp_text=rfp_text[:10000],  # store truncated raw text
            requirements=json.dumps(result["requirements"]),
            proposal_content=json.dumps(result["proposal_content"]),
            status="draft",
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)

        logger.info(f"Proposal generated and saved (id={proposal.id}, file={filename})")
        return {
            **proposal.to_dict(),
            "extraction_metadata": result.get("extraction", {}),
            "past_projects": result.get("past_projects", []),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Proposal generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals/")
async def list_proposals(
    skip: int = 0,
    limit: int = 20,
    proposal_status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """List all proposals (admin auth required)."""
    query = db.query(Proposal)
    if proposal_status:
        query = query.filter(Proposal.status == proposal_status)
    total = query.count()
    proposals = query.order_by(Proposal.created_at.desc()).offset(skip).limit(limit).all()
    # Return without rfp_text for list view (too large)
    results = []
    for p in proposals:
        d = p.to_dict()
        results.append(d)
    return {"total": total, "proposals": results}


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Get a single proposal with full content (admin auth required)."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal.to_dict()


@router.put("/proposals/{proposal_id}")
async def update_proposal(
    proposal_id: int,
    payload: ProposalUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Update proposal status or content (admin auth required)."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    valid_statuses = {"draft", "reviewed", "sent"}
    if payload.status and payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")

    try:
        if payload.status is not None:
            proposal.status = payload.status
        if payload.proposal_content is not None:
            proposal.proposal_content = json.dumps(payload.proposal_content)
        db.commit()
        db.refresh(proposal)
        return proposal.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/proposals/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a proposal (admin auth required)."""
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    try:
        db.delete(proposal)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
