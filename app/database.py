"""
Database configuration and session management
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

# Create engine - sqlite for now, easy to switch to PostgreSQL
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """FastAPI dependency for database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables on startup"""
    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns():
    """Add small backward-compatible schema updates for existing databases."""
    inspector = inspect(engine)
    try:
        tables = set(inspector.get_table_names())
    except Exception:
        return

    if "solicitations" not in tables:
        return

    existing = {col["name"] for col in inspector.get_columns("solicitations")}
    additions = {
        "attachment_details": "TEXT",
        "agency_registration_details": "TEXT",
    }

    with engine.begin() as conn:
        for column_name, sql_type in additions.items():
            if column_name not in existing:
                conn.execute(text(f"ALTER TABLE solicitations ADD COLUMN {column_name} {sql_type}"))
