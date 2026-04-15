"""
Configuration module for Cold Email Generator
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # LLM Configuration
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TEMPERATURE: float = 0.3
    MAX_TOKENS: int = 2000
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"

    # Vector Store
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    COLLECTION_NAME: str = "portfolio_skills"

    # ── NEW: Database ──────────────────────────────────────────────────────────
    # SQLite by default; swap for PostgreSQL: postgresql://user:pass@host/db
    DATABASE_URL: str = "sqlite:///./portfolio.db"

    # ── NEW: Admin Auth ────────────────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "ivoyant@admin"   # Change this in .env for production

    # Application
    APP_NAME: str = "Cold Email Generator"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = True
    PORT: int = 8000

    # Company Information
    COMPANY_NAME: str = "Ivoyant Systems Pvt Ltd"
    COMPANY_WEBSITE: str = "https://www.ivoyant.com"

    # ── Phase 3: SMTP / Marketing Notifications ────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    MARKETING_EMAIL: str = ""   # where opportunity alerts are sent

    # ── Phase 6: Lead Discovery Agent ──────────────────────────────────────────
    DISCOVERY_ENABLED: bool = False
    DISCOVERY_INTERVAL_HOURS: int = 24

    # ── Phase 6+: Global Search (SearXNG via web_scraper) ──────────────────────
    SEARCH_ENABLED: bool = False
    SEARXNG_BASE_URL: str = "http://localhost:8080/search"

    # ── Multi-LLM ────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    DEFAULT_LLM_PROVIDER: str = "openai"

    # ── Daily Opportunity Report ─────────────────────────────────────────────
    DAILY_REPORT_ENABLED: bool = False
    DAILY_REPORT_SEND_HOUR: int = 8     # 8 AM daily

    # ── Capture Management (HigherGov / procurement scraping) ────────────────
    HIGHERGOV_EMAIL: str = ""
    HIGHERGOV_PASSWORD: str = ""
    HIGHERGOV_LOGIN_URL: str = ""   # set in .env — e.g. https://www.highergov.com/login
    HIGHERGOV_LISTING_URL: str = "https://www.highergov.com/contract-opportunity/"

    # Comma-separated keyword groups used to filter solicitations
    # LLM provider to use for capture qualification (gemini recommended for large docs)
    CAPTURE_LLM_PROVIDER: str = "gemini"

    # Max concurrent sub-page scrapes during a capture scan
    CAPTURE_MAX_CONCURRENT: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
