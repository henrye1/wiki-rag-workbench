"""Apply migrations/*.sql in order. Usage: python -m bench.migrate"""
import psycopg

from .config import ROOT, get_settings

MIGRATIONS = ROOT / "migrations"


def main():
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute("create schema if not exists bench")
        conn.execute("create table if not exists bench.schema_migrations (name text primary key, applied_at timestamptz default now())")
        done = {r[0] for r in conn.execute("select name from bench.schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into bench.schema_migrations (name) values (%s)", (f.name,))
            print(f"applied {f.name}")
        print("migrations up to date")


if __name__ == "__main__":
    main()
