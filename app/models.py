"""
Database models for Portfolio Management, Email Tracking, Signal Classification,
Opportunity Management, Proposal Generation, and Lead Discovery
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Portfolio(Base):
    """Portfolio entry - stores skill + projects + link"""
    __tablename__ = "portfolios"

    id          = Column(Integer, primary_key=True, index=True)
    skill       = Column(String(100), nullable=False, index=True)
    portfolio_link = Column(String(500), nullable=False)
    projects    = Column(Text, nullable=False)   # pipe-separated: "Proj A|Proj B"
    description = Column(Text, default="")
    image_url   = Column(String(500), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def to_dict(self):
        return {
            "id":             self.id,
            "skill":          self.skill,
            "portfolio_link": self.portfolio_link,
            "projects":       self.projects.split("|") if self.projects else [],
            "description":    self.description or "",
            "image_url":      self.image_url,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
            "updated_at":     self.updated_at.isoformat() if self.updated_at else None,
        }


class Email(Base):
    """Email tracking - stores all generated emails with status"""
    __tablename__ = "emails"

    id               = Column(Integer, primary_key=True, index=True)
    job_url          = Column(String(1000), nullable=False)
    company_name     = Column(String(200), nullable=True, index=True)
    job_role         = Column(String(200), nullable=False, index=True)
    email_subject    = Column(String(500), nullable=False)
    email_body       = Column(Text, nullable=False)
    skills           = Column(Text, nullable=True)  # JSON string
    matched_portfolios = Column(Text, nullable=True)  # JSON string
    status           = Column(String(50), default="draft", index=True)  # draft/sent/responded/interested/not_interested
    notes            = Column(Text, nullable=True)
    generated_at     = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    sent_at          = Column(DateTime(timezone=True), nullable=True)
    responded_at     = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def to_dict(self):
        import json
        return {
            "id":               self.id,
            "job_url":          self.job_url,
            "company_name":     self.company_name,
            "job_role":         self.job_role,
            "email_subject":    self.email_subject,
            "email_body":       self.email_body,
            "skills":           json.loads(self.skills) if self.skills else [],
            "matched_portfolios": json.loads(self.matched_portfolios) if self.matched_portfolios else [],
            "status":           self.status,
            "notes":            self.notes or "",
            "generated_at":     self.generated_at.isoformat() if self.generated_at else None,
            "sent_at":          self.sent_at.isoformat() if self.sent_at else None,
            "responded_at":     self.responded_at.isoformat() if self.responded_at else None,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Phase 1: Signal Classification ────────────────────────────────────────────

class Signal(Base):
    """Classified internet signal — job posting, RFP notice, or service request"""
    __tablename__ = "signals"

    id               = Column(Integer, primary_key=True, index=True)
    source_url       = Column(String(1000), nullable=True)
    raw_text         = Column(Text, nullable=True)
    signal_type      = Column(String(50), nullable=False, index=True)  # job_hiring | rfp_opportunity | service_request | other
    company_name     = Column(String(200), nullable=True, index=True)
    detected_skills  = Column(Text, nullable=True)   # JSON list
    confidence_score = Column(Float, default=0.0)
    status           = Column(String(50), default="new", index=True)  # new | processed | ignored
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        import json
        return {
            "id":               self.id,
            "source_url":       self.source_url,
            "signal_type":      self.signal_type,
            "company_name":     self.company_name,
            "detected_skills":  json.loads(self.detected_skills) if self.detected_skills else [],
            "confidence_score": self.confidence_score,
            "status":           self.status,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
        }


# ── Phase 2: Opportunity Management ───────────────────────────────────────────

class Opportunity(Base):
    """Scored sales opportunity derived from a signal"""
    __tablename__ = "opportunities"

    id                = Column(Integer, primary_key=True, index=True)
    signal_id         = Column(Integer, ForeignKey("signals.id"), nullable=True)
    company_name      = Column(String(200), nullable=True, index=True)
    source_url        = Column(String(1000), nullable=True)
    opportunity_type  = Column(String(50), nullable=False)  # email_outreach | proposal
    skill_match_score = Column(Float, default=0.0)
    signal_strength   = Column(Float, default=0.0)
    overall_score     = Column(Float, default=0.0, index=True)
    priority          = Column(String(20), default="low", index=True)  # high | medium | low
    status            = Column(String(50), default="new", index=True)  # new | email_sent | rfp_requested | rfp_received | proposal_sent | closed
    notes             = Column(Text, nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at        = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def to_dict(self):
        return {
            "id":                self.id,
            "signal_id":         self.signal_id,
            "company_name":      self.company_name,
            "source_url":        self.source_url,
            "opportunity_type":  self.opportunity_type,
            "skill_match_score": round(self.skill_match_score or 0.0, 3),
            "signal_strength":   round(self.signal_strength or 0.0, 3),
            "overall_score":     round(self.overall_score or 0.0, 3),
            "priority":          self.priority,
            "status":            self.status,
            "notes":             self.notes or "",
            "created_at":        self.created_at.isoformat() if self.created_at else None,
            "updated_at":        self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Phase 3: Notifications ─────────────────────────────────────────────────────

class Notification(Base):
    """In-app notification for marketing team"""
    __tablename__ = "notifications"

    id              = Column(Integer, primary_key=True, index=True)
    opportunity_id  = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    title           = Column(String(300), nullable=False)
    message         = Column(Text, nullable=False)
    is_read         = Column(Boolean, default=False, index=True)
    email_sent      = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id":             self.id,
            "opportunity_id": self.opportunity_id,
            "title":          self.title,
            "message":        self.message,
            "is_read":        self.is_read,
            "email_sent":     self.email_sent,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }


# ── Phase 5: Proposals ─────────────────────────────────────────────────────────

class Proposal(Base):
    """AI-generated proposal from an uploaded RFP document"""
    __tablename__ = "proposals"

    id               = Column(Integer, primary_key=True, index=True)
    opportunity_id   = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    rfp_filename     = Column(String(500), nullable=True)
    rfp_text         = Column(Text, nullable=True)
    requirements     = Column(Text, nullable=True)   # JSON list
    proposal_content = Column(Text, nullable=True)   # JSON with sections
    status           = Column(String(50), default="draft", index=True)  # draft | reviewed | sent
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    def to_dict(self):
        import json
        return {
            "id":               self.id,
            "opportunity_id":   self.opportunity_id,
            "rfp_filename":     self.rfp_filename,
            "requirements":     json.loads(self.requirements) if self.requirements else [],
            "proposal_content": json.loads(self.proposal_content) if self.proposal_content else {},
            "status":           self.status,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Phase 6: Lead Discovery ────────────────────────────────────────────────────

class DiscoverySource(Base):
    """Configured source URL for the automated lead discovery agent"""
    __tablename__ = "discovery_sources"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String(200), nullable=False)
    url                  = Column(String(1000), nullable=False)
    source_type          = Column(String(50), nullable=False)  # job_board | procurement | news
    scan_interval_hours  = Column(Integer, default=24)
    last_scanned_at      = Column(DateTime(timezone=True), nullable=True)
    is_active            = Column(Boolean, default=True, index=True)
    keywords             = Column(Text, nullable=True)  # JSON list of target keywords
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        import json
        return {
            "id":                  self.id,
            "name":                self.name,
            "url":                 self.url,
            "source_type":         self.source_type,
            "scan_interval_hours": self.scan_interval_hours,
            "last_scanned_at":     self.last_scanned_at.isoformat() if self.last_scanned_at else None,
            "is_active":           self.is_active,
            "keywords":            json.loads(self.keywords) if self.keywords else [],
            "created_at":          self.created_at.isoformat() if self.created_at else None,
        }