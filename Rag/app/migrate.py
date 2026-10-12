"""Apply supabase/migrations/*.sql in order (hosted Postgres, e.g. Render pre-deploy). Usage: python -m app.migrate

Locally the Supabase CLI applies the same files; the SQL is idempotent, so running this afterwards is safe.
"""
import pathlib
import sys

import psycopg

from .config import get_settings

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def _explain(e: Exception) -> str:
    """Turn a connection failure into an actionable message (shown in the Render deploy log)."""
    url = get_settings().database_url
    host = url.split("@")[-1].split("/")[0] if "@" in url else "(no host in DATABASE_URL)"
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    hints = []
    if "127.0.0.1" in url or "localhost" in url:
        hints.append("DATABASE_URL points at localhost: set it to the Supabase session-pooler URI")
    if "db." in host and "supabase.co" in host:
        hints.append("this is Supabase's direct (IPv6-only) host: use the Session pooler URI (...pooler.supabase.com:5432)")
    if ":6543" in host:
        hints.append("port 6543 is the transaction pooler: use the session pooler on port 5432")
    if "password authentication failed" in msg:
        hints.append("wrong database password (URL-encode special characters such as @ # / ?)")
    return f"Cannot connect to the database at {host}: {msg}" + "".join(f"\n  hint: {h}" for h in hints)


def _redacted(url: str) -> str:
    """The URL with its password hidden, so the deploy log shows what was actually configured."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return f"{url[:12]}... (not a postgresql:// URL)"
    creds, at, host = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}" if at else url


def _connect():
    try:
        return psycopg.connect(get_settings().database_url, autocommit=True, connect_timeout=15)
    except psycopg.OperationalError as e:
        sys.exit(_explain(e))
    except psycopg.ProgrammingError as e:  # unparseable DATABASE_URL
        sys.exit(f"DATABASE_URL is not a valid connection string ({str(e).strip()}): {_redacted(get_settings().database_url)}\n"
                 "  hint: expected postgresql://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres"
                 "?sslmode=require; URL-encode special characters in the password")


def main():
    with _connect() as conn:
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
