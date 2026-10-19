"""Suggested rubric changes, for you to accept or reject on the Rubric review screen (nothing changes until you do):

- a tag for each key point (standard / supporting / beyond_standard) with the paragraph that backs it, decided by the
  judge from the closest paragraphs of the original source texts (library.search), never from the wiki or memory;
- merges of key points that are items of one list in the reference (e.g. a list of indicators) into one point;
- a new exact-match fact list holding only hard facts (numbers, periods, thresholds, yes/no answers), each tagged the
  same way.

Suggestions are stored with the topic (bench.rubrics.suggestions); accepting them and saving makes a new rubric version.
The grading prompt is not changed.

  python -m bench.suggest <reference-sha256> [topics, e.g. 1,5]
"""
import asyncio
import datetime as dt
import pathlib
import sys
import tempfile

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import judge
from .config import get_settings
from .data import load
from .library import Library

TAGS = ["standard", "supporting", "beyond_standard"]

HARD_FACTS_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "F1, F2, ..."},
                       "fact": {"type": "string", "description": "One short sentence holding the hard fact"}},
        "required": ["id", "fact"], "additionalProperties": False}}},
    "required": ["facts"], "additionalProperties": False,
}

HARD_FACTS_SYSTEM = """You are an IFRS 9 expert preparing an exact-match checklist for grading answers.
From the human-written reference answer, list only its hard facts: numbers, amounts and percentages, time periods
(days, months, years), thresholds, dates, and the yes/no answer to a question when the reference gives one.
- Each fact is one short sentence that contains the hard value and what it applies to, so it can be checked as
  stated, contradicted or not stated.
- Do not list definitions, explanations, lists of examples or general requirements without a hard value.
- Only facts the reference itself states. At most 10. If it has none, return an empty list."""

ITEM = {"type": "object", "properties": {
    "id": {"type": "string"},
    "tag": {"type": "string", "enum": TAGS},
    "paragraph": {"type": "string", "description": "The paragraph number that backs the tag, as shown; empty for beyond_standard"},
    "document": {"type": "string", "description": "That paragraph's document, as shown; empty for beyond_standard"},
    "found": {"type": "boolean", "description": "false when the point is probably in a Standard but none of the paragraphs shown says it"},
    "reason": {"type": "string"}},
    "required": ["id", "tag", "paragraph", "document", "found", "reason"], "additionalProperties": False}

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {"type": "array", "items": ITEM},
        "facts": {"type": "array", "items": ITEM},
        "merges": {"type": "array", "items": {"type": "object", "properties": {
            "ids": {"type": "array", "items": {"type": "string"}},
            "point": {"type": "string", "description": "One point keeping every item of the list"},
            "tag": {"type": "string", "enum": TAGS},
            "reason": {"type": "string"}},
            "required": ["ids", "point", "tag", "reason"], "additionalProperties": False}},
    },
    "required": ["points", "facts", "merges"], "additionalProperties": False,
}

SUGGEST_SYSTEM = """You review an IFRS grading rubric against the original source texts.
Each key point (K...) and fact (F...) comes with the closest paragraphs found in the source documents, each marked
with its tier:
- Standard: a Standard's own text (Part A, including its appendices);
- Supporting: documents published with the Standard (Part B implementation guidance and illustrative examples,
  Part C basis for conclusions).
1. For every key point and fact, suggest a tag from the paragraphs shown only, never from memory:
   standard = a Standard paragraph shown states its substance; supporting = only a Supporting paragraph shown states it;
   beyond_standard = no paragraph shown states it (practice, regulation, opinion, or the text shown does not say it).
   Give the paragraph number and document that back the tag (empty for beyond_standard). Set found = false when you
   think a Standard probably does say it but none of the paragraphs shown does, so a person checks it.
2. Suggest merges: key points that are only items of one list in the reference (e.g. a list of indicators or
   examples) should be a single point that keeps every item. Never merge distinct requirements or conditions.
   Return no merges if there are none.
Give a short reason for each."""


def _candidates(lib: Library, text: str) -> str:
    return "\n".join(f"    [{h['paragraph']}] {h['document']} ({'Standard' if h['tier'] == 'standard' else 'Supporting'}): "
                     f"{' '.join(h['text'].split())[:700]}" for h in lib.search(text))


def _user(title: str, reference: str, points: list[dict], facts: list[dict], lib: Library) -> str:
    kp = "\n\n".join(f"{p['id']} (now tagged {p['kind']}): {p['point']}\n  closest paragraphs:\n{_candidates(lib, p['point'])}" for p in points)
    fs = "\n\n".join(f"{f['id']}: {f['fact']}\n  closest paragraphs:\n{_candidates(lib, f['fact'])}" for f in facts) or "(none)"
    return (f"Topic: {title}\n\n<reference_answer>\n{reference}\n</reference_answer>\n\n<key_points>\n{kp}\n</key_points>"
            f"\n\n<facts>\n{fs}\n</facts>")


async def suggest_topic(t, row: dict, lib: Library) -> dict:
    """Hard facts first (from the reference), then one call that tags every key point and fact and proposes merges."""
    hf = await judge._json_call(HARD_FACTS_SYSTEM, f"Topic: {t.title}\n\nQuestions the topic asks:\n" + "\n".join(t.questions)
                                + f"\n\n<reference_answer label=\"{t.reference_label}\">\n{t.reference}\n</reference_answer>",
                                HARD_FACTS_SCHEMA)
    facts = hf["data"]["facts"]
    sg = await judge._json_call(SUGGEST_SYSTEM, _user(t.title, t.reference, row["key_points"], facts, lib), SUGGEST_SCHEMA)
    d = sg["data"]
    by_id = {x["id"]: x for x in d["facts"]}
    ids = {p["id"] for p in row["key_points"]}
    return {
        "made_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "model": sg["model"], "backend": sg.get("backend", "api"),
        "base_version": row["version"],
        "usage": {"hard_facts": hf["usage"], "suggest": sg["usage"]},
        "points": {x["id"]: {**{k: x[k] for k in ("tag", "paragraph", "document", "found", "reason")}, "status": None}
                   for x in d["points"] if x["id"] in ids},
        "merges": [{**m, "status": None} for m in d["merges"] if len(m["ids"]) > 1 and set(m["ids"]) <= ids],
        "facts": {"status": None, "items": [{"id": f["id"], "fact": f["fact"],
                                             **{k: by_id.get(f["id"], {}).get(k) for k in ("tag", "paragraph", "document", "found", "reason")}}
                                            for f in facts]},
    }


async def suggest(conn: psycopg.Connection, ref_sha: str, numbers: set[int] | None = None, log=print):
    row = conn.execute(
        """select reference, query_set from bench.runs where reference is not null and query_set is not null
           and encode(sha256(reference), 'hex') = %s order by created_at desc limit 1""", (ref_sha,)).fetchone()
    if not row:
        sys.exit(f"No stored run uses the reference file {ref_sha[:12]}…")
    with tempfile.TemporaryDirectory() as tmp:
        qs, ref = pathlib.Path(tmp, "query_set.txt"), pathlib.Path(tmp, "reference.docx")
        qs.write_bytes(row["query_set"])
        ref.write_bytes(row["reference"])
        topics = {t.number: t for t in load(qs, ref)}
    rows = [r for r in conn.execute("select * from bench.rubrics where reference_sha256 = %s order by topic_number", (ref_sha,))
            if not numbers or r["topic_number"] in numbers]
    lib = await asyncio.to_thread(Library, conn)
    sem, lock = asyncio.Semaphore(get_settings().concurrency), asyncio.Lock()
    log(f"Suggesting rubric changes for {len(rows)} topic(s)")

    async def one(r):
        t = topics.get(r["topic_number"])
        if not t:
            log(f"  topic {r['topic_number']}: not in the query set, skipped")
            return
        try:
            async with sem:
                s = await suggest_topic(t, r, lib)
        except Exception as e:
            log(f"  topic {r['topic_number']:>2}: failed ({type(e).__name__}: {e})")
            return
        async with lock:
            await asyncio.to_thread(conn.execute, "update bench.rubrics set suggestions = %s where reference_sha256 = %s and topic_number = %s",
                                    (Jsonb(s), ref_sha, r["topic_number"]))
        changed = sum(p["tag"] != next((k["kind"] for k in r["key_points"] if k["id"] == i), None) for i, p in s["points"].items())
        log(f"  topic {r['topic_number']:>2}: {changed} tag change(s), {len(s['merges'])} merge(s), {len(s['facts']['items'])} hard fact(s)")
    await asyncio.gather(*(one(r) for r in rows))
    log("Suggestions ready")


if __name__ == "__main__":
    if len(sys.argv) in (2, 3):
        nums = None
        if len(sys.argv) == 3:
            nums = set()
            for part in sys.argv[2].split(","):
                a, _, b = part.partition("-")
                nums.update(range(int(a), int(b or a) + 1))
        c = psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row)
        asyncio.run(suggest(c, sys.argv[1], nums, lambda m: print(m, flush=True)))
    else:
        sys.exit(__doc__)
