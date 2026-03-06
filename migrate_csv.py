"""
Migration script: Import existing portfolio.csv → SQLite database → ChromaDB
Run once after adding the new database layer:
    python migrate_csv.py
"""
import sys
import csv
import os

# Make sure the app package is importable
sys.path.insert(0, os.path.dirname(__file__))

from app.database import init_db, SessionLocal
from app.models import Portfolio
from app.core.vector_store import get_vector_store

CSV_PATH = "data/portfolio.csv"


def migrate():
    print("=" * 55)
    print("  Portfolio CSV  →  Database + Vector Store Migration")
    print("=" * 55)

    # 1. Create tables
    init_db()
    print("✓ Database tables ready")

    # 2. Read CSV
    if not os.path.exists(CSV_PATH):
        print(f"✗ CSV not found at {CSV_PATH}")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"✓ Found {len(rows)} rows in CSV")

    db = SessionLocal()
    vs = get_vector_store()

    success = 0
    skipped = 0

    for row in rows:
        skill        = (row.get("Skill") or row.get("skill") or "").strip()
        link         = (row.get("Portfolio Link") or row.get("portfolio_link") or "").strip()
        projects_raw = (row.get("Projects") or row.get("projects") or "").strip()
        description  = (row.get("Description") or row.get("description") or "").strip()

        if not skill or not link:
            skipped += 1
            continue

        projects = [p.strip() for p in projects_raw.split(",") if p.strip()] or [skill]

        # Check duplicate
        exists = db.query(Portfolio).filter(Portfolio.skill == skill).first()
        if exists:
            print(f"  ⚠  Skipping duplicate: {skill}")
            skipped += 1
            continue

        # DB row
        db_row = Portfolio(
            skill=skill,
            portfolio_link=link,
            projects="|".join(projects),
            description=description,
        )
        db.add(db_row)

        # Vector store
        try:
            vs.add_portfolio(
                skill=skill,
                portfolio_link=link,
                projects=projects,
                description=description,
            )
        except Exception as e:
            print(f"  ⚠  Vector store error for {skill}: {e}")

        success += 1
        print(f"  ✓  {skill}")

    db.commit()
    db.close()

    print()
    print(f"✓ Migrated : {success}")
    print(f"⚠  Skipped  : {skipped}")
    print(f"✓ Vector store now has {vs.count_documents()} documents")
    print()
    print("Migration complete!  You can now use the admin dashboard at /admin")
    print("=" * 55)


if __name__ == "__main__":
    migrate()