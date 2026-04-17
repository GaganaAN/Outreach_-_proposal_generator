"""
Database configuration and session management
"""
from sqlalchemy import create_engine
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
    """Create all tables and apply any missing column migrations on startup."""
    Base.metadata.create_all(bind=engine)
    _apply_migrations()


def _apply_migrations():
    """
    Add new columns to existing tables that pre-date the column definition.
    SQLAlchemy create_all() only creates missing tables, not missing columns.
    Safe to run on every startup — skips columns that already exist.
    """
    migrations = [
        # (table, column, sql_type)
        ("solicitations", "agency_registration_section", "TEXT"),
        ("solicitations", "attachment_urls",             "TEXT"),
        ("keyword_sets",  "is_active",                   "BOOLEAN DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                existing = [
                    row[1] for row in
                    conn.execute(
                        __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
                    ).fetchall()
                ]
                if column not in existing:
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                        )
                    )
                    conn.commit()
            except Exception:
                pass  # table may not exist yet — create_all above will handle it