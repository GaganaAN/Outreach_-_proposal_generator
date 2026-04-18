"""
One-time migration: SQLite (portfolio.db) → PostgreSQL (genai-dev / mailposalix schema)

Run from the project root:
    python migrate_sqlite_to_postgres.py

Safe to re-run — skips rows that already exist (by primary key).
"""
import sqlite3
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from app.config import get_settings

SQLITE_PATH = "./portfolio.db"
SCHEMA = "mailposalix"

# Migration order must respect FK dependencies:
# signals → opportunities → notifications
# opportunities → proposals
# proposals → solicitations
TABLES = [
    "portfolios",
    "emails",
    "signals",
    "discovery_sources",
    "opportunities",
    "notifications",
    "proposals",
    "past_projects",
    "solicitations",
    "keyword_sets",
]


def get_pg_conn():
    settings = get_settings()
    url = settings.DATABASE_URL
    # Parse postgresql://user:pass@host:port/dbname?sslmode=require
    # Use psycopg2 directly with the URL
    return psycopg2.connect(url, sslmode="require")


def get_sqlite_rows(sqlite_cur, table):
    sqlite_cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in sqlite_cur.description]
    rows = sqlite_cur.fetchall()
    return cols, rows


def normalize_bool(val):
    """SQLite stores booleans as 0/1 integers."""
    if isinstance(val, int) and val in (0, 1):
        return bool(val)
    return val


def normalize_row(cols, row):
    """Convert SQLite row values to PostgreSQL-compatible types."""
    result = {}
    for col, val in zip(cols, row):
        if isinstance(val, int) and col in (
            "is_active", "is_read", "email_sent",
        ):
            val = bool(val)
        result[col] = val
    return result


def migrate_table(sqlite_cur, pg_cur, table):
    cols, rows = get_sqlite_rows(sqlite_cur, table)
    if not rows:
        print(f"  {table}: 0 rows — skipping")
        return 0

    qualified = f"{SCHEMA}.{table}"
    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    inserted = 0
    skipped = 0
    for row in rows:
        norm = normalize_row(cols, row)
        values = [norm[c] for c in cols]
        try:
            pg_cur.execute(
                f"INSERT INTO {qualified} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT (id) DO NOTHING",
                values,
            )
            if pg_cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"    [WARN] Row id={norm.get('id')} skipped: {e}")
            pg_cur.execute("ROLLBACK TO SAVEPOINT sp")
            continue
        pg_cur.execute("RELEASE SAVEPOINT sp")
        pg_cur.execute("SAVEPOINT sp")

    return inserted, skipped


def reset_sequences(pg_cur):
    """Reset PostgreSQL SERIAL sequences to max(id)+1 so new inserts don't conflict."""
    for table in TABLES:
        try:
            pg_cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{SCHEMA}.{table}', 'id'), "
                f"COALESCE(MAX(id), 0) + 1, false) FROM {SCHEMA}.{table}"
            )
        except Exception as e:
            print(f"  [WARN] Could not reset sequence for {table}: {e}")


def main():
    print(f"Connecting to SQLite: {SQLITE_PATH}")
    sqlite_con = sqlite3.connect(SQLITE_PATH)
    sqlite_cur = sqlite_con.cursor()

    print("Connecting to PostgreSQL...")
    try:
        pg_con = get_pg_conn()
    except Exception as e:
        print(f"[ERROR] Cannot connect to PostgreSQL: {e}")
        print("Check your DATABASE_URL in .env and ensure your IP is whitelisted in Azure.")
        sys.exit(1)

    pg_cur = pg_con.cursor()
    pg_con.autocommit = False

    print(f"\nMigrating {len(TABLES)} tables into schema '{SCHEMA}':\n")

    total_inserted = 0
    for table in TABLES:
        try:
            pg_cur.execute("SAVEPOINT sp")
            inserted, skipped = migrate_table(sqlite_cur, pg_cur, table)
            pg_con.commit()
            print(f"  ✓ {table}: {inserted} inserted, {skipped} already existed")
            total_inserted += inserted
        except Exception as e:
            pg_con.rollback()
            print(f"  ✗ {table}: FAILED — {e}")

    print("\nResetting PostgreSQL sequences...")
    try:
        pg_cur.execute("SAVEPOINT sp")
        reset_sequences(pg_cur)
        pg_con.commit()
        print("  ✓ Sequences reset")
    except Exception as e:
        pg_con.rollback()
        print(f"  [WARN] Sequence reset failed: {e}")

    sqlite_con.close()
    pg_cur.close()
    pg_con.close()

    print(f"\nDone. {total_inserted} rows migrated to PostgreSQL.")


if __name__ == "__main__":
    main()
