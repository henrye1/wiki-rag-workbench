"""Import results.json runs written by the old file-based CLI into bench.runs.

  python -m bench.import_results results/20261008-130302 [more dirs...]

Inputs (query set / reference) are not stored for imported runs, so they can be viewed but not resumed.
"""
import json
import pathlib
import sys

import psycopg
from psycopg.types.json import Jsonb

from .config import ROOT, get_settings


def main(dirs: list[str]):
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        for d in dirs:
            path = pathlib.Path(d)
            path = (path if path.is_absolute() else ROOT / path) / "results.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg = data.get("config", {})
            status = "finished" if cfg.get("finished") else "failed"
            conn.execute(
                """insert into bench.runs (id, created_at, status, results, runs, topics, query_set_name, reference_name)
                   values (%s, coalesce(%s::timestamptz, now()), %s, %s, %s, %s, %s, %s)
                   on conflict (id) do update set results = excluded.results, status = excluded.status""",
                (path.parent.name, cfg.get("started"), status, Jsonb(data), cfg.get("runs") or 1,
                 ",".join(map(str, cfg.get("topics_selected") or [])), cfg.get("query_set"), cfg.get("reference")),
            )
            print(f"imported {path.parent.name} ({status})")


if __name__ == "__main__":
    main(sys.argv[1:])
