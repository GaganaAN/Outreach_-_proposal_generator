"""
Database models for Portfolio Management and Email Tracking
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
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