"""Full mode: faithfulness and context recall, in one call per answer (CONTEXT_MODEL) that reads exactly what the answer
read: the RAG's passages (stored with the answer) or the wiki's pages, rebuilt from the page versions the answer recorded
(the wiki's /read-text, with the same Sources setting).

- Faithfulness: the judge splits the answer into its factual claims and marks each backed or not backed by what was
  read. Score = share backed. Saved answers the wiki read are left out of what counts as backing: a claim backed only by
  an earlier answer is not backed by the wiki's pages.
- Context recall: for each rubric key point, does what was read contain it (present 1, partly 0.5, absent 0)?
  Score = the average, as a percentage. It shows whether a miss was the search's fault or the answer's.
The judge sees one answer at a time and never the name of the system that wrote it. Answers from runs made before
what was read was recorded are not measured.
"""
import asyncio

import httpx

from . import judge
from .config import get_settings

VERSION = "context-1"
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
            "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
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
Give a short note for each."""


def _context_rag(ans: dict) -> tuple[str | None, str]:
    read = ans.get("read")
    if read is None:
        return None, "the run was made before what each answer read was recorded"
    if not read:
        return "", ""
    return "\n\n".join(f"[{r.get('para_ref') or '?'}] {r.get('content') or ''}" for r in read), ""


async def _context_wiki(http: httpx.AsyncClient, wiki: str, sources: str, ans: dict) -> tuple[str | None, str]:
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
    return "\n\n".join(f"<page slug=\"{p['slug']}\" version=\"{p['version']}\">\n{p['text']}\n</page>" for p in got), note


def _user(questions: list[str], points: list[dict], context: str, answer: str) -> str:
    kp = "\n".join(f"{p['id']}: {p['point']}" for p in points) or "(none)"
    return (f"<questions>\n" + "\n".join(questions) + f"\n</questions>\n\n<key_points>\n{kp}\n</key_points>\n\n"
            f"<context>\n{context or '(nothing was read)'}\n</context>\n\n<answer>\n{answer}\n</answer>")


def score(result: dict | None, points: list[dict], note: str) -> tuple[dict, dict]:
    from .metrics import measured, not_measured
    d = (result or {}).get("data") or {"claims": [], "key_points": []}
    claims = d["claims"][:MAX_CLAIMS]
    kv = {x["id"]: x for x in d["key_points"]}
    kps = [{"id": p["id"], "kind": p.get("kind"), **{k: kv.get(p["id"], {}).get(k) for k in ("status", "note")}} for p in points]
    m = {}
    m["faithfulness"] = (measured(round(100 * sum(c["status"] == "backed" for c in claims) / len(claims), 1)) if claims
                         else not_measured("the judge found no factual claims in the answer"))
    got = [WEIGHT[k["status"]] for k in kps if k["status"] in WEIGHT]
    m["context_recall"] = (measured(round(100 * sum(got) / len(got), 1)) if got
                           else not_measured("no key points" if not kps else "the judge returned no verdicts"))
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
                ctx, note = _context_rag(ans) if sysname == "rag" else await _context_wiki(http, wiki, sources, ans)
            except Exception as e:
                ctx, note = None, f"what the answer read could not be rebuilt ({type(e).__name__})"
            if ctx is None:
                ans["metrics"] = {**(ans.get("metrics") or {}), "faithfulness": not_measured(note), "context_recall": not_measured(note)}
                continue
            prepared[key] = (rec, ans, note, _user(questions_of(rec.get("question")), rec.get("key_points") or [], ctx, ans.get("answer") or ""))

    async def keep(key, result):
        rec, ans, note, _ = prepared[key]
        r, m = score(result, rec.get("key_points") or [], note)
        async with lock:
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
