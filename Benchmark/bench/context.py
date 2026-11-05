"""Full mode: faithfulness and context recall, in one call per answer (CONTEXT_MODEL) that reads exactly what the answer
read: the RAG's passages (stored with the answer) or the wiki's pages, rebuilt from the page versions the answer recorded
(the wiki's /read-text, with the same Sources setting).

- Faithfulness: the judge splits the answer into its factual claims and marks each backed or not backed by what was
  read. Score = share backed. Saved answers the wiki read are left out of what counts as backing: a claim backed only by
  an earlier answer is not backed by the wiki's pages.
- Context recall: for each rubric key point, does what was read contain it (present 1, partly 0.5, absent 0)?
  Score = the average, as a percentage. It shows whether a miss was the search's fault or the answer's.
  Standard-only context recall: over the key points tagged Standard, does the Standard's own text in what was read
  contain it? Each passage (RAG) and each citation on a page (wiki) is marked Standard or not by its paragraph's tier
  (library.kind_tier): editorial text (notes, agenda decisions, the introduction) and documents published with the
  Standard are never Standard text.
The judge sees one answer at a time and never the name of the system that wrote it. Answers from runs made before
what was read was recorded are not measured.

Re-score a stored run's saved answers and what they read, with no new answers:  python -m bench.context <run-id> ...
"""
import asyncio
import datetime as dt
import re
import sys

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import judge
from .config import get_settings
from .library import ACCOMPANYING_KINDS, kind_tier, paragraph_tier
from .systems import RAGS

VERSION = "context-3"  # 2: Standard-only context recall; 3: counted from Standard text only (each passage marked)
PREVIOUS = ("faithfulness", "context_recall", "context_recall_standard")
STD, NOT_STD = "Standard", "not Standard"
MAX_CLAIMS = 40
WEIGHT = {"present": 1.0, "partly": 0.5, "absent": 0.0}

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"}, "status": {"type": "string", "enum": ["backed", "not_backed"]},
            "note": {"type": "string"}}, "required": ["claim", "status", "note"], "additionalProperties": False}},
        "key_points": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "status": {"type": "string", "enum": ["present", "partly", "absent"]},
            "status_standard": {"type": "string", "enum": ["present", "partly", "absent"]},
            "note": {"type": "string"}}, "required": ["id", "status", "status_standard", "note"], "additionalProperties": False}},
    },
    "required": ["claims", "key_points"], "additionalProperties": False,
}

SYSTEM = f"""You check one answer against the text it was given to answer from (its context). You are not told which
system wrote it. Use only the context, never your own knowledge.
1. Faithfulness: split the answer into its factual claims (statements of substance; skip headings, restatements of the
   question, and statements that the material does not cover something), at most {MAX_CLAIMS}. Mark each:
   backed = the context states it or directly implies it; not_backed = the context does not say it, even if it is true.
2. Context recall: for each key point (K1, K2, ...), does the context contain it? present = with its substance;
   partly = only part of it; absent = not there. This is about the context, not the answer.
3. For each key point also give status_standard: the same question, counting only the Standard's own text. Each
   passage is marked (Standard) or (not Standard), and each citation on a page is followed by {{Standard}} or
   {{not Standard}}; a statement counts as Standard text only when one of its citations is marked {{Standard}}. Text marked
   not Standard (editorial notes, agenda decisions, the introduction, documents published with the Standard) and text
   with no citation do not count for status_standard.
Give a short note for each."""


def _rag_tier(source_type: str | None) -> str:
    """A RAG passage's tier from the reader's kind of it: documents published with the Standard and editorial text are
    supporting; the Standard's own text (its appendices included) is standard."""
    return "supporting" if source_type in ACCOMPANYING_KINDS else kind_tier("standard", source_type)


def _context_rag(ans: dict) -> tuple[str | None, str]:
    read = ans.get("read")
    if read is None:
        return None, "the run was made before what each answer read was recorded"
    if not read:
        return "", ""
    return "\n\n".join(f"[{r.get('para_ref') or '?'}] ({STD if _rag_tier(r.get('source_type')) == 'standard' else NOT_STD}) "
                       f"{r.get('content') or ''}" for r in read), ""


CITE = re.compile(r"\[\[(source-[^|\]]+)\|([^\]]+)\]\]")
RANGE = re.compile(r"\s*[–—-]\s*")


def _labels(group: str) -> list[str]:
    """The paragraph labels a citation names: "5.5.3, 5.5.4" -> both; "paragraphs B4.1.1–B4.1.26" -> its two ends."""
    group = re.sub(r"^\s*(?:paragraphs?|paras?)\s+", "", group.strip(), flags=re.I)
    out = []
    for part in re.split(r"\s*(?:[,;]|\band\b)\s*", group):
        out += [x for x in RANGE.split(part) if x] if ":" not in part else [part]
    return [x.strip() for x in out if x.strip()]


def mark_citations(text: str, metas: dict[str, dict]) -> str:
    """Each source citation on a page followed by {Standard} or {not Standard}, by the tier of what it cites."""
    def tag(m):
        meta = metas.get(m.group(1))
        std = meta is not None and any(paragraph_tier(meta, x) == "standard" for x in _labels(m.group(2)) or [m.group(2)])
        return m.group(0) + " {" + (STD if std else NOT_STD) + "}"
    return CITE.sub(tag, text)


def _source_metas(wiki: str) -> dict[str, dict]:
    """The run's wiki's own sources (slug -> reader meta), for the tier of each paragraph its pages cite."""
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as c:
        return {r["slug"]: r["meta"] or {} for r in c.execute(
            "select s.slug, s.meta from wiki.sources s join wiki.wikis w on w.id = s.wiki_id where w.slug = %s", (wiki,))}


async def _context_wiki(http: httpx.AsyncClient, wiki: str, sources: str, ans: dict, metas: dict) -> tuple[str | None, str]:
    read = ans.get("read")
    if read is None:
        return None, "the run was made before what each answer read was recorded"
    pages = [r for r in read if not r.get("saved")]
    if not pages:
        return "", ""
    s = get_settings()
    r = await http.post(f"{s.wiki_url}/wikis/{wiki}/read-text", json={"read": pages, "sources": sources},
                        headers={"X-API-Key": s.wiki_api_key}, timeout=120)
    r.raise_for_status()
    got = r.json()
    if any(p.get("text") is None for p in got):
        return None, "a page version the answer read is no longer in the wiki"
    note = "" if all(p.get("matches") for p in got) else "some page text differs from what was read"
    return "\n\n".join(f"<page slug=\"{p['slug']}\" version=\"{p['version']}\">\n{mark_citations(p['text'], metas)}\n</page>"
                       for p in got), note


def _user(questions: list[str], points: list[dict], context: str, answer: str) -> str:
    kp = "\n".join(f"{p['id']}: {p['point']}" for p in points) or "(none)"
    return (f"<questions>\n" + "\n".join(questions) + f"\n</questions>\n\n<key_points>\n{kp}\n</key_points>\n\n"
            f"<context>\n{context or '(nothing was read)'}\n</context>\n\n<answer>\n{answer}\n</answer>")


def score(result: dict | None, points: list[dict], note: str) -> tuple[dict, dict]:
    from .metrics import measured, not_measured
    d = (result or {}).get("data") or {"claims": [], "key_points": []}
    claims = d["claims"][:MAX_CLAIMS]
    kv = {x["id"]: x for x in d["key_points"]}
    kps = [{"id": p["id"], "kind": p.get("kind"), **{k: kv.get(p["id"], {}).get(k) for k in ("status", "status_standard", "note")}}
           for p in points]
    m = {}
    m["faithfulness"] = (measured(round(100 * sum(c["status"] == "backed" for c in claims) / len(claims), 1)) if claims
                         else not_measured("the judge found no factual claims in the answer"))
    got = [WEIGHT[k["status"]] for k in kps if k["status"] in WEIGHT]
    m["context_recall"] = (measured(round(100 * sum(got) / len(got), 1)) if got
                           else not_measured("no key points" if not kps else "the judge returned no verdicts"))
    std = [WEIGHT[k["status_standard"]] for k in kps if k["kind"] == "standard" and k["status_standard"] in WEIGHT]
    m["context_recall_standard"] = (measured(round(100 * sum(std) / len(std), 1)) if std
                                    else not_measured("none of this topic's key points is tagged Standard" if not any(k["kind"] == "standard" for k in kps)
                                                      else "the judge returned no verdicts"))
    rec = {"version": VERSION, "model": (result or {}).get("model"), "backend": (result or {}).get("backend"),
           "usage": (result or {}).get("usage"), "batch": (result or {}).get("batch", False), "note": note,
           "claims": claims, "key_points": kps}
    return rec, m


async def run_context(data: dict, sem: asyncio.Semaphore, use_batch: bool, save, log=print) -> int:
    """Faithfulness and context recall for every saved answer still without them (Full mode)."""
    from .checks import questions_of
    from .metrics import not_measured
    s = get_settings()
    cfg = data.get("config") or {}
    wiki, sources = cfg.get("wiki_slug"), cfg.get("sources") or "all"
    metas = await asyncio.to_thread(_source_metas, wiki) if wiki else {}
    todo = []
    for rec in data.get("topics", {}).values():
        for rid, run in rec.get("runs", {}).items():
            for sysname, ans in (run.get("systems") or run.get("answers") or {}).items():
                if (ans.get("context_checks") or {}).get("version") != VERSION:
                    todo.append((rec, rid, sysname, ans))
    if not todo:
        return 0
    log(f"Faithfulness and context recall: {len(todo)} answer(s), {s.context_model}")
    lock = asyncio.Lock()
    prepared = {}
    async with httpx.AsyncClient() as http:
        for rec, rid, sysname, ans in todo:
            key = f"x{rec['number']}-r{rid}-{sysname}"
            try:
                ctx, note = _context_rag(ans) if sysname in RAGS else await _context_wiki(http, wiki, sources, ans, metas)
            except Exception as e:
                ctx, note = None, f"what the answer read could not be rebuilt ({type(e).__name__})"
            if ctx is None:
                ans["metrics"] = {**(ans.get("metrics") or {}), **{k: not_measured(note) for k in ("faithfulness", "context_recall", "context_recall_standard")}}
                continue
            prepared[key] = (rec, ans, note, _user(questions_of(rec.get("question")), rec.get("key_points") or [], ctx, ans.get("answer") or ""))

    async def keep(key, result):
        rec, ans, note, _ = prepared[key]
        r, m = score(result, rec.get("key_points") or [], note)
        async with lock:
            old = ans.get("context_checks") or {}
            if old.get("version") and old.get("version") != VERSION and "context_checks_previous" not in ans:
                # an earlier version's record is kept with its scores, never overwritten
                ans["context_checks_previous"] = {**old, "metrics": {k: (ans.get("metrics") or {}).get(k) for k in PREVIOUS}}
            ans["context_checks"] = r
            ans["metrics"] = {**(ans.get("metrics") or {}), **m}
            await save()

    left = list(prepared)
    if use_batch and s.judge_backend == "api" and left:
        reqs = {k: judge._params(SYSTEM, prepared[k][3], SCHEMA, s.context_model) for k in left}
        try:
            got = await judge.grade_batch(reqs, None, lambda _id: asyncio.sleep(0), log, "context checks")
            left = [k for k, res in got.items() if isinstance(res, Exception)]
            for k, res in got.items():
                if not isinstance(res, Exception):
                    await keep(k, res)
        except Exception as e:
            log(f"  context checks batch failed ({type(e).__name__}: {e}); checking normally")
    failed = 0

    async def one(k):
        nonlocal failed
        async with sem:
            try:
                await keep(k, await judge._json_call(SYSTEM, prepared[k][3], SCHEMA, s.context_model))
            except Exception as e:
                failed += 1
                log(f"  {k}: context checks failed ({type(e).__name__}: {e})")
    await asyncio.gather(*(one(k) for k in left))
    await save()
    log(f"Faithfulness and context recall done: {len(prepared) - failed} of {len(prepared)}")
    return len(prepared) - failed


async def rescore(run_id: str, conn: psycopg.Connection):
    """Faithfulness and context recall again, at this VERSION, for a stored run: its saved answers and what each read
    (the RAG's stored passages; the wiki's pages at the versions recorded, from the wiki service). No answer is asked
    again and no grade changes. The earlier version's record stays with each answer (context_checks_previous)."""
    from . import metrics
    from .run import aggregate
    row = conn.execute("select results, log, mode, use_batch from bench.runs where id = %s", (run_id,)).fetchone()
    if not row:
        sys.exit(f"Run {run_id} not found")
    if (row["mode"] or "") != "full":
        sys.exit(f"Run {run_id} is not a Full run")
    s = get_settings()
    data, lines = row["results"], (row["log"] or "").splitlines()
    cfg = data["config"]
    before = (cfg.get("context_checks") or {}).get("version")

    def log(msg=""):
        print(msg, flush=True)
        lines.extend(msg.splitlines() or [""])

    async def save():
        await asyncio.to_thread(conn.execute, "update bench.runs set results = %s, log = %s, updated_at = now() where id = %s",
                                (Jsonb(data), "\n".join(lines[-300:]), run_id))
    log(f"--- {dt.datetime.now().isoformat(timespec='seconds')} re-score: faithfulness and context recall at {VERSION} (was {before})")
    use_batch = s.judge_backend != "claude-code" and row["use_batch"] is not False
    n = await run_context(data, asyncio.Semaphore(s.concurrency), use_batch, save, log)
    await metrics.compute(data, "full")
    aggregate(data)
    cfg["context_checks"] = {**(cfg.get("context_checks") or {}), "model": s.context_model, "version": VERSION,
                             "rescored": {"at": dt.datetime.now().isoformat(timespec="seconds"), "from": before, "answers": n}}
    await save()
    log(f"Re-scored {n} answer(s) of {run_id}")


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row) as conn:
        for run_id in sys.argv[1:]:
            await rescore(run_id, conn)


if __name__ == "__main__":
    asyncio.run(main())
