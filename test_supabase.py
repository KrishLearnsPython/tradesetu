
import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    sys.exit("ERROR: DATABASE_URL is missing from .env")

try:
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            database, username = cur.fetchone()

            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [row[0] for row in cur.fetchall()]

    print("SUCCESS: Connected to Supabase PostgreSQL")
    print(f"Database: {database}")
    print(f"Connected as: {username}")
    print(f"Public tables found: {len(tables)}")
    for table in tables:
        print(f"  - {table}")

except Exception as exc:
    print(f"CONNECTION FAILED: {type(exc).__name__}: {exc}")
    sys.exit(1)
