"""Saved rubrics: key points built once per reference file (by its SHA-256) and reused by every run.

  python -m bench.rubric list
  python -m bench.rubric rebuild <reference-sha256>   # build again on purpose (same judge prompt), replacing the saved one
  python -m bench.rubric seed <run-id>                # save the key points an earlier run built as the rubric for its reference
"""
import asyncio
import hashlib
import pathlib
import sys
import tempfile

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import judge
from .config import get_settings
from .data import load


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(conn: psycopg.Connection, ref_sha: str, number: int) -> dict | None:
    return conn.execute(
        "select * from bench.rubrics where reference_sha256 = %s and topic_number = %s", (ref_sha, number)
    ).fetchone()


def save(conn: psycopg.Connection, ref_sha: str, ref_name: str | None, number: int, title: str, key_points: list,
         usage: dict | None, model: str | None, source_run: str, replace: bool = False):
    """Store a topic's key points. Without replace, a rubric already saved (e.g. by a concurrent run) is kept."""
    conn.execute(
        f"""insert into bench.rubrics (reference_sha256, topic_number, reference_name, topic_title, key_points, key_points_usage,
                                      judge_model, source_run)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (reference_sha256, topic_number) do {'update set reference_name = excluded.reference_name, '
            'topic_title = excluded.topic_title, key_points = excluded.key_points, key_points_usage = excluded.key_points_usage, '
            'judge_model = excluded.judge_model, source_run = excluded.source_run, created_at = now(), '
            'version = bench.rubrics.version + 1, reviewed_at = null' if replace else 'nothing'}""",
        (ref_sha, number, ref_name, title, Jsonb(key_points), Jsonb(usage) if usage else None, model, source_run),
    )
    # every version is kept; rebuilt key points need approving again (the facts and their approval are kept)
    conn.execute(
        """insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at, note)
           select reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at, %s
           from bench.rubrics where reference_sha256 = %s and topic_number = %s on conflict do nothing""",
        ("rebuilt" if replace else "built", ref_sha, number),
    )


async def rebuild(conn: psycopg.Connection, ref_sha: str):
    """Build the rubric's topics again from the latest run that used this reference file, replacing them one by one."""
    row = conn.execute(
        """select id, reference_name, reference, query_set from bench.runs
           where reference is not null and query_set is not null and encode(sha256(reference), 'hex') = %s
           order by created_at desc limit 1""", (ref_sha,),
    ).fetchone()
    if not row:
        sys.exit(f"No stored run uses the reference file {ref_sha[:12]}…")
    with tempfile.TemporaryDirectory() as tmp:
        qs, ref = pathlib.Path(tmp, "query_set.txt"), pathlib.Path(tmp, "reference.docx")
        qs.write_bytes(row["query_set"])
        ref.write_bytes(row["reference"])
        topics = load(qs, ref)
    saved = {r["topic_number"] for r in conn.execute("select topic_number from bench.rubrics where reference_sha256 = %s", (ref_sha,))}
    topics = [t for t in topics if t.number in saved] if saved else topics  # rebuild what the rubric holds
    s = get_settings()
    sem = asyncio.Semaphore(s.concurrency)
    lock = asyncio.Lock()

    async def one(t):
        async with sem:
            kp = await judge.key_points(t)
        async with lock:
            await asyncio.to_thread(save, conn, ref_sha, row["reference_name"], t.number, t.title,
                                    kp["data"]["key_points"], kp["usage"], kp["model"], "rebuild", True)
        print(f"  topic {t.number:>2}: {len(kp['data']['key_points'])} key points", flush=True)

    print(f"Rebuilding the rubric for {row['reference_name']} ({ref_sha[:12]}…), {len(topics)} topics", flush=True)
    await asyncio.gather(*(one(t) for t in topics))
    print("Rubric rebuilt", flush=True)


def seed(conn: psycopg.Connection, run_id: str):
    row = conn.execute("select id, reference_name, reference, results from bench.runs where id = %s", (run_id,)).fetchone()
    if not row or not row["reference"]:
        sys.exit(f"Run {run_id} not found or has no reference file")
    ref_sha, topics = sha256(row["reference"]), (row["results"] or {}).get("topics", {})
    n = 0
    for rec in topics.values():
        if rec.get("key_points"):
            save(conn, ref_sha, row["reference_name"], rec["number"], rec["title"], rec["key_points"],
                 rec.get("key_points_usage"), (row["results"].get("config") or {}).get("judge_model"), run_id, replace=True)
            n += 1
    print(f"Saved {n} topics' key points from run {run_id} as the rubric for {row['reference_name']} ({ref_sha[:12]}…)")


def main(argv: list[str]):
    conn = psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row)
    if argv[:1] == ["list"]:
        for r in conn.execute(
            """select reference_sha256, max(reference_name) as name, count(*) as topics,
                      sum(jsonb_array_length(key_points)) as points, min(created_at) as built, max(created_at) as updated
               from bench.rubrics group by reference_sha256 order by max(created_at) desc"""
        ).fetchall():
            print(f"{r['reference_sha256'][:12]}…  {r['name']}  {r['topics']} topics, {r['points']} key points, "
                  f"built {r['built']:%Y-%m-%d %H:%M}, updated {r['updated']:%Y-%m-%d %H:%M}")
    elif argv[:1] == ["rebuild"] and len(argv) == 2:
        asyncio.run(rebuild(conn, argv[1]))
    elif argv[:1] == ["seed"] and len(argv) == 2:
        seed(conn, argv[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
