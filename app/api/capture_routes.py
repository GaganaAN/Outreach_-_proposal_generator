"""
Capture Management API — solicitation discovery, qualification, and proposal generation.

All endpoints require admin auth.

Endpoints:
  GET  /api/admin/solicitations/               list with filters
  GET  /api/admin/solicitations/stats          dashboard counts
  GET  /api/admin/solicitations/{id}           full detail (all 10 sections)
  PATCH /api/admin/solicitations/{id}/status   bid | no_bid | reviewing
  POST /api/admin/solicitations/scan-now       trigger manual HigherGov scan
  POST /api/admin/solicitations/scan-url       scrape a single URL on demand
  POST /api/admin/solicitations/{id}/generate-proposal  generate proposal from solicitation
  GET  /api/admin/solicitations/{id}/rfp-text  raw RFP text (for source linking)
  DELETE /api/admin/solicitations/{id}         delete a solicitation record
"""
import json
import logging
import secrets
import threading
import uuid
from datetime import datetime as _dt, timedelta
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, status
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Solicitation, Proposal

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Scan progress tracking ─────────────────────────────────────────────────────

_scan_registry: dict = {}
_scan_lock = threading.Lock()
_latest_scan_id: Optional[str] = None


def _create_scan() -> str:
    global _latest_scan_id
    scan_id = uuid.uuid4().hex[:8]
    with _scan_lock:
        _scan_registry[scan_id] = {
            "status": "running",
            "messages": ["Scan started — connecting to procurement sources..."],
            "cancel": threading.Event(),
        }
        _latest_scan_id = scan_id
    return scan_id


def _add_msg(scan_id: str, msg: str):
    with _scan_lock:
        entry = _scan_registry.get(scan_id)
        if entry:
            entry["messages"].append(msg)


def _finish_scan(scan_id: str, fin_status: str = "completed"):
    with _scan_lock:
        entry = _scan_registry.get(scan_id)
        if entry:
            entry["status"] = fin_status
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

class StatusUpdate(BaseModel):
    status: str                          # new | reviewing | bid | no_bid | proposal_generated
    bid_decision_notes: Optional[str] = None


class ScanUrlRequest(BaseModel):
    url: str


class GenerateProposalRequest(BaseModel):
    llm_provider: Optional[str] = None  # groq | openai | gemini | None → default


# ── List & Stats ───────────────────────────────────────────────────────────────

@router.get("/solicitations/scan-status")
async def get_scan_status(_: str = Depends(verify_admin)):
    """Return the status and progress messages of the most recent scan."""
    if not _latest_scan_id:
        return {"status": "idle", "messages": [], "scan_id": None}
    with _scan_lock:
        entry = _scan_registry.get(_latest_scan_id, {})
        return {
            "scan_id":  _latest_scan_id,
            "status":   entry.get("status", "idle"),
            "messages": list(entry.get("messages", [])),
        }


@router.post("/solicitations/scan-cancel")
async def cancel_scan(_: str = Depends(verify_admin)):
    """Request cancellation of the running scan."""
    if not _latest_scan_id:
        return {"message": "No active scan"}
    with _scan_lock:
        entry = _scan_registry.get(_latest_scan_id)
        if entry and entry.get("status") == "running":
            entry["cancel"].set()
            entry["messages"].append("Stop requested — finishing current task...")
            return {"message": "Cancel requested"}
    return {"message": "No active scan to cancel"}


@router.get("/solicitations/stats")
async def solicitation_stats(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Dashboard counts for the Capture Management tab."""
    total       = db.query(Solicitation).count()
    new_count   = db.query(Solicitation).filter(Solicitation.status == "new").count()
    reviewing   = db.query(Solicitation).filter(Solicitation.status == "reviewing").count()
    bid_count   = db.query(Solicitation).filter(Solicitation.status == "bid").count()
    no_bid      = db.query(Solicitation).filter(Solicitation.status == "no_bid").count()
    generated   = db.query(Solicitation).filter(Solicitation.status == "proposal_generated").count()
    high_match  = db.query(Solicitation).filter(Solicitation.scope_match_level == "High").count()
    medium_match = db.query(Solicitation).filter(Solicitation.scope_match_level == "Medium").count()

    return {
        "total":             total,
        "new":               new_count,
        "reviewing":         reviewing,
        "bid":               bid_count,
        "no_bid":            no_bid,
        "proposal_generated": generated,
        "high_match":        high_match,
        "medium_match":      medium_match,
    }


@router.get("/solicitations/")
async def list_solicitations(
    skip: int = 0,
    limit: int = 30,
    sol_status: Optional[str] = None,
    scope_level: Optional[str] = None,
    keyword: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    List solicitations with optional filters.
    Does NOT include raw_rfp_text in list response (too large).
    """
    query = db.query(Solicitation)
    if sol_status:
        query = query.filter(Solicitation.status == sol_status)
    if scope_level:
        query = query.filter(Solicitation.scope_match_level == scope_level)
    if keyword:
        query = query.filter(Solicitation.keyword_matched.ilike(f"%{keyword}%"))
    if search:
        query = query.filter(
            or_(
                Solicitation.title.ilike(f"%{search}%"),
                Solicitation.agency.ilike(f"%{search}%"),
                Solicitation.solicitation_number.ilike(f"%{search}%"),
            )
        )
    if date_from:
        try:
            query = query.filter(Solicitation.created_at >= _dt.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(
                Solicitation.created_at < _dt.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            )
        except ValueError:
            pass

    total = query.count()
    sols = (
        query
        .order_by(Solicitation.scope_match_percentage.desc(), Solicitation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "solicitations": [s.to_dict() for s in sols]}


# ── Detail ─────────────────────────────────────────────────────────────────────

@router.get("/solicitations/{solicitation_id}")
async def get_solicitation(
    solicitation_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Full solicitation detail — all 10 qualification sections."""
    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")
    return sol.to_dict()


@router.get("/solicitations/{solicitation_id}/rfp-text")
async def get_rfp_text(
    solicitation_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Return the raw RFP text (used for source document linking per PRD Section 7)."""
    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")
    return {
        "solicitation_id": sol.id,
        "title":           sol.title,
        "solicitation_url": sol.solicitation_url,
        "raw_rfp_text":    sol.raw_rfp_text or "",
        "pdf_filenames":   json.loads(sol.pdf_filenames) if sol.pdf_filenames else [],
    }


# ── Status / Bid Decision ──────────────────────────────────────────────────────

VALID_STATUSES = {"new", "reviewing", "bid", "no_bid", "proposal_generated"}


@router.patch("/solicitations/{solicitation_id}/status")
async def update_solicitation_status(
    solicitation_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    Update solicitation status (bid/no-bid decision workflow).
    Allowed transitions: new → reviewing → bid | no_bid → proposal_generated
    """
    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")

    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )

    try:
        sol.status = payload.status
        if payload.bid_decision_notes is not None:
            sol.bid_decision_notes = payload.bid_decision_notes
        db.commit()
        db.refresh(sol)
        return sol.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── Generate Proposal from Solicitation ────────────────────────────────────────

@router.post("/solicitations/{solicitation_id}/generate-proposal",
             status_code=status.HTTP_201_CREATED)
async def generate_proposal_from_solicitation(
    solicitation_id: int,
    payload: GenerateProposalRequest,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    Generate a technical proposal from a qualified Solicitation.
    The solicitation must have status 'bid'.
    Saves a Proposal record and links it back to the Solicitation.
    """
    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")

    if sol.status not in ("bid", "reviewing"):
        raise HTTPException(
            status_code=400,
            detail=f"Solicitation status is '{sol.status}'. Set status to 'bid' before generating."
        )

    try:
        from app.services.proposal_generator import get_proposal_generator
        generator = get_proposal_generator()
        result = generator.generate_from_solicitation(
            solicitation=sol,
            llm_provider=payload.llm_provider,
            db=db,
        )

        if result.get("no_match"):
            return {
                "no_match":        True,
                "message":         result["message"],
                "solicitation_id": solicitation_id,
            }

        # Save Proposal record
        proposal = Proposal(
            opportunity_id=None,
            rfp_filename=f"capture_{sol.solicitation_number or sol.id}",
            rfp_text=(sol.raw_rfp_text or "")[:10000],
            requirements=json.dumps(result["requirements"]),
            proposal_content=json.dumps(result["proposal_content"]),
            status="draft",
        )
        db.add(proposal)
        db.flush()

        # Link solicitation → proposal
        sol.proposal_id = proposal.id
        sol.status = "proposal_generated"
        db.commit()
        db.refresh(proposal)

        logger.info(
            f"[Capture] Proposal id={proposal.id} generated from solicitation id={sol.id}"
        )
        return {
            **proposal.to_dict(),
            "solicitation_id": sol.id,
            "past_projects":   result.get("past_projects", []),
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[Capture] Proposal generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Scan Triggers ──────────────────────────────────────────────────────────────

@router.post("/solicitations/scan-now")
async def scan_now(
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_admin),
):
    """
    Manually trigger a HigherGov scan for all active procurement sources.
    Runs in background — poll /scan-status for progress.
    """
    scan_id = _create_scan()
    background_tasks.add_task(_run_full_capture_scan, scan_id)
    return {"message": "Capture scan started", "scan_id": scan_id}


@router.post("/solicitations/scan-url")
async def scan_single_url(
    payload: ScanUrlRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_admin),
):
    """
    Scrape and qualify a single solicitation URL on demand.
    Useful for manually adding a specific solicitation found outside the discovery flow.
    """
    if not payload.url.startswith("http"):
        raise HTTPException(status_code=400, detail="url must be a valid HTTP/HTTPS URL")

    background_tasks.add_task(_run_single_url_scan, payload.url)
    return {"message": f"Single URL scan started for: {payload.url}"}


def _run_full_capture_scan(scan_id: str = ""):
    """Background: scan all active procurement DiscoverySources."""
    from app.database import SessionLocal
    from app.models import DiscoverySource
    from app.services.lead_discovery import get_lead_discovery_agent

    def msg(text: str):
        if scan_id:
            _add_msg(scan_id, text)

    def is_cancelled() -> bool:
        if not scan_id:
            return False
        with _scan_lock:
            return _scan_registry.get(scan_id, {}).get("cancel", threading.Event()).is_set()

    db = SessionLocal()
    try:
        msg("Looking up active procurement sources...")
        sources = (
            db.query(DiscoverySource)
            .filter(
                DiscoverySource.is_active == True,
                DiscoverySource.source_type == "procurement",
            )
            .all()
        )
        if not sources:
            msg("No active procurement sources found. Add one in Lead Discovery.")
            logger.info("[Capture] No active procurement sources configured")
            _finish_scan(scan_id)
            return

        msg(f"Found {len(sources)} source(s) — starting scan now...")
        agent = get_lead_discovery_agent()
        total_created = 0

        for i, source in enumerate(sources, 1):
            if is_cancelled():
                msg("Scan stopped by user.")
                _finish_scan(scan_id, "cancelled")
                return

            msg(f"Scanning {source.name} for matching solicitations...")
            try:
                def _on_save(sol, _src=source.name):
                    msg(f"✓ Saved [{sol.capture_id}] {sol.title[:60]} ({sol.scope_match_level} {sol.scope_match_percentage:.0f}%)")

                count = agent.scan_source(source, db, on_save=_on_save, is_cancelled=is_cancelled)
                total_created += count
                source.last_scanned_at = _dt.utcnow()
                db.commit()
                msg(f"✓ {source.name} — {count} new solicitation(s) added")
                logger.info(f"[Capture] Scanned '{source.name}': {count} solicitation(s) created")
            except Exception as e:
                msg(f"Could not complete scan for {source.name} — skipping")
                logger.error(f"[Capture] Scan failed for {source.name}: {e}")

            # Exit the source loop immediately if cancelled mid-scan
            if is_cancelled():
                msg("Scan stopped by user.")
                _finish_scan(scan_id, "cancelled")
                return

        if total_created > 0:
            msg(f"✓ Scan complete — {total_created} new solicitation(s) ready to review")
        else:
            msg("✓ Scan complete — no new solicitations found (already up to date)")
        _finish_scan(scan_id)

    except Exception as e:
        msg("Scan encountered an unexpected error.")
        _finish_scan(scan_id, "error")
        logger.error(f"[Capture] Full scan failed: {e}")
    finally:
        db.close()


def _run_single_url_scan(url: str):
    """Background: scrape + qualify a single solicitation URL."""
    from app.database import SessionLocal
    from app.services.capture_service import get_capture_service

    db = SessionLocal()
    try:
        sol = get_capture_service().scan_url(url, db)
        if sol:
            logger.info(f"[Capture] Single URL scan created solicitation id={sol.id}")
        else:
            logger.info(f"[Capture] Single URL scan: no solicitation created for {url}")
    except Exception as e:
        logger.error(f"[Capture] Single URL scan failed for {url}: {e}")
    finally:
        db.close()


# ── Attachment proxy download ──────────────────────────────────────────────────

@router.get("/solicitations/{solicitation_id}/download-attachment")
async def download_attachment(
    solicitation_id: int,
    url: str,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """
    Proxy-download a solicitation attachment URL through the server.
    Handles HigherGov auth-gated PDFs by using the stealth crawler session.
    Returns the file as an attachment download.
    """
    from fastapi.responses import Response

    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")

    # Resolve relative URLs against HigherGov base (stored URLs may be relative paths)
    HIGHERGOV_BASE = "https://www.highergov.com"
    if url.startswith("/"):
        url = HIGHERGOV_BASE + url

    # Validate the URL belongs to this solicitation's attachment_urls
    stored = json.loads(sol.attachment_urls) if sol.attachment_urls else {}
    # Match against both full and relative forms
    valid_urls = set()
    for v in stored.values():
        valid_urls.add(v)
        if v.startswith("/"):
            valid_urls.add(HIGHERGOV_BASE + v)
        elif v.startswith(HIGHERGOV_BASE):
            valid_urls.add(v[len(HIGHERGOV_BASE):])
    if url not in valid_urls:
        raise HTTPException(status_code=403, detail="URL not associated with this solicitation")

    filename = name or url.rstrip("/").split("/")[-1].split("?")[0] or "attachment.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    try:
        # Try plain httpx first — only accept if response is actually a PDF file
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            ct = resp.headers.get("content-type", "")
            is_pdf = resp.content[:4] == b"%PDF" or "pdf" in ct.lower()
            if resp.status_code == 200 and is_pdf and len(resp.content) > 500:
                return Response(
                    content=resp.content,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
    except Exception:
        pass

    # Fallback: use stealth crawler (handles auth-gated PDFs)
    try:
        from app.services.stealth_crawler import get_stealth_crawler, run_async
        crawler = get_stealth_crawler()
        pdf_bytes = run_async(crawler._fetch_pdf_bytes(url))
        if pdf_bytes:
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as e:
        logger.error(f"[Capture] Attachment download failed for {url}: {e}")

    raise HTTPException(
        status_code=502,
        detail=(
            "This document requires HigherGov login. "
            "Click 'Open URL ↗' to view it on HigherGov after logging in — "
            "the full text was already extracted and saved in the Raw RFP Text section."
        )
    )


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/solicitations/{solicitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_solicitation(
    solicitation_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin),
):
    """Delete a solicitation record (does not delete the linked Proposal)."""
    sol = db.query(Solicitation).filter(Solicitation.id == solicitation_id).first()
    if not sol:
        raise HTTPException(status_code=404, detail="Solicitation not found")
    try:
        db.delete(sol)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
