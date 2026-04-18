"""
Database configuration and session management.
Supports both SQLite (local dev) and PostgreSQL (production).
Switch by setting DATABASE_URL in .env:
  SQLite:     sqlite:///./portfolio.db
  PostgreSQL: postgresql://user:password@host:5432/genai-dev
"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

_is_postgres = settings.DATABASE_URL.startswith("postgresql")

# Engine — SQLite needs check_same_thread=False, PostgreSQL uses connection pooling
if _is_postgres:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"},
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables on startup. Safe to run multiple times."""
    Base.metadata.create_all(bind=engine)
    _apply_migrations()


def _apply_migrations():
    """
    Add new columns to existing tables that pre-date the column definition.
    SQLAlchemy create_all() only creates missing tables, not missing columns.
    Works with both SQLite (PRAGMA) and PostgreSQL (information_schema).
    Safe to run on every startup — skips columns that already exist.
    """
    # (schema, table, column, sql_type)
    # schema=None means no schema prefix (SQLite) or public schema (PostgreSQL)
    migrations = [
        ("solicitations", "agency_registration_section", "TEXT"),
        ("solicitations", "attachment_urls",             "TEXT"),
        ("solicitations", "capture_id",                  "VARCHAR(20)"),
        ("keyword_sets",  "is_active",                   "BOOLEAN DEFAULT FALSE"),
    ]

    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                if _is_postgres:
                    # Resolve the schema name from the model's __table_args__
                    schema = _get_model_schema(table)
                    result = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = :table "
                        "AND column_name = :column"
                    ), {"schema": schema, "table": table, "column": column})
                    exists = result.fetchone() is not None
                    qualified = f"{schema}.{table}"
                else:
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    exists = column in [row[1] for row in result.fetchall()]
                    qualified = table

                if not exists:
                    conn.execute(text(
                        f"ALTER TABLE {qualified} ADD COLUMN {column} {col_type}"
                    ))
                    conn.commit()
                    logger.info(f"[DB] Migration applied: {qualified}.{column}")
            except Exception as e:
                logger.debug(f"[DB] Migration skipped for {table}.{column}: {e}")


def _get_model_schema(tablename: str) -> str:
    """Return the schema name for a given table (from model __table_args__)."""
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if getattr(cls, "__tablename__", None) == tablename:
            args = getattr(cls, "__table_args__", {})
            if isinstance(args, dict):
                return args.get("schema", "mailposalix")
            if isinstance(args, tuple):
                for item in args:
                    if isinstance(item, dict):
                        return item.get("schema", "mailposalix")
    return "mailposalix"
