"""Apply supabase/migrations/*.sql in order (hosted Postgres, e.g. Render pre-deploy). Usage: python -m app.migrate

Locally the Supabase CLI applies the same files; the SQL is idempotent, so running this afterwards is safe.
"""
import pathlib

import psycopg

from .config import get_settings

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def main():
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute("create table if not exists public.rag_schema_migrations (name text primary key, applied_at timestamptz default now())")
        done = {r[0] for r in conn.execute("select name from public.rag_schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into public.rag_schema_migrations (name) values (%s)", (f.name,))
            print(f"applied {f.name}")
        print("migrations up to date")


if __name__ == "__main__":
    main()
