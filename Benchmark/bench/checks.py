"""Answer checks: completeness, exact match and citation accuracy, in one judge call per answer (CHECKS_MODEL).

- Completeness: is each of the topic's questions (Q1, Q2, ...) answered, partly answered or not answered?
  Score = answered 1, partly 0.5, not 0, averaged, as a percentage.
- Exact match: is each of the topic's exact-match facts (short, specific facts taken from the reference answer once per
  reference file, kept with the rubric for you to approve) stated, contradicted or not stated?
  Score = share of facts stated. A topic whose reference has no such facts is not measured.
- Citation accuracy: each paragraph citation is looked up in the Standard's own text (the sources kept by the wikis) and
  the judge decides whether that paragraph supports the statement it is attached to.
  Score = supported 1, partly 0.5, not supported 0, averaged. A wiki citation naming a source that does not hold the
  paragraph counts as not supported. A citation whose paragraph is not in those texts (e.g. a document no wiki holds) or
  that points to a whole page cannot be checked: it is counted, not scored.
The judge sees one answer at a time and never the name of the system that wrote it.

  python -m bench.checks facts <reference-sha256>          # make the exact-match fact lists still missing
  python -m bench.checks backfill <run-id>|all             # run the checks on saved answers (no question is asked again)
"""
import asyncio
import re
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import judge
from .config import get_settings

VERSION = "checks-1"
MAX_CITATIONS = 40   # per answer, after removing repeats; any beyond are counted, not checked
MAX_PARAGRAPH = 3000  # characters of a cited paragraph's text given to the judge
WEIGHT = {"answered": 1.0, "partly": 0.5, "not_answered": 0.0, "supported": 1.0, "not_supported": 0.0}

# ---------- exact-match facts (once per reference file and topic) ----------

FACTS_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "F1, F2, ..."},
                       "fact": {"type": "string", "description": "One short, specific, self-contained fact"}},
        "required": ["id", "fact"], "additionalProperties": False}}},
    "required": ["facts"], "additionalProperties": False,
}

FACTS_SYSTEM = """You are an IFRS 9 expert preparing an exact-match checklist for grading answers.
From the human-written reference answer, list the short, specific facts an answer must state exactly to be right:
numbers, time periods, thresholds and percentages, dates, the yes/no answer to a question, named categories or lists,
and precisely stated requirements or definitions.
- Each fact is one short, self-contained sentence that can be checked as stated, contradicted or not stated.
- Only facts the reference itself states; add nothing. Skip general explanation, background and opinion.
- At most 12 facts. If the reference contains no such facts, return an empty list."""


async def make_facts(topic_title: str, questions: list[str], reference: str, reference_label: str = "") -> dict:
    user = (f"Topic: {topic_title}\n\nQuestions the topic asks:\n" + "\n".join(questions)
            + f"\n\n<reference_answer label=\"{reference_label}\">\n{reference}\n</reference_answer>")
    return await judge._json_call(FACTS_SYSTEM, user, FACTS_SCHEMA)  # the judge model, like the rubric's key points


def save_facts(conn: psycopg.Connection, ref_sha: str, number: int, facts: list, usage: dict | None, model: str | None):
    """Store a topic's new fact list (only where none is saved yet) as a new rubric version, not yet approved."""
    row = conn.execute(
        """update bench.rubrics set facts = %s, facts_usage = %s, facts_model = %s, version = version + 1, facts_reviewed_at = null
           where reference_sha256 = %s and topic_number = %s and facts is null returning version""",
        (Jsonb(facts), Jsonb(usage) if usage else None, model, ref_sha, number)).fetchone()
    if row:
        conn.execute(
            """insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at, note)
               select reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at, 'facts made'
               from bench.rubrics where reference_sha256 = %s and topic_number = %s on conflict do nothing""", (ref_sha, number))


def questions_of(text: str) -> list[str]:
    """The topic's questions ("Q1. ...") from its question text."""
    return [ln.strip() for ln in (text or "").splitlines() if re.match(r"\s*Q\d+[.):]", ln)]


async def facts_for_reference(conn: psycopg.Connection, ref_sha: str, log=print):
    """Make the fact lists the rubric for this reference file is still missing, from the latest run that used it."""
    import pathlib, tempfile
    from .data import load
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
    missing = [r["topic_number"] for r in conn.execute(
        "select topic_number from bench.rubrics where reference_sha256 = %s and facts is null order by topic_number", (ref_sha,))]
    sem, lock = asyncio.Semaphore(get_settings().concurrency), asyncio.Lock()
    log(f"Making exact-match fact lists for {len(missing)} topic(s)")

    async def one(n):
        t = topics.get(n)
        if not t:
            log(f"  topic {n}: not in the query set, skipped")
            return
        async with sem:
            r = await make_facts(t.title, t.questions, t.reference, t.reference_label)
        async with lock:
            await asyncio.to_thread(save_facts, conn, ref_sha, n, r["data"]["facts"], r["usage"], r["model"])
        log(f"  topic {n:>2}: {len(r['data']['facts'])} facts")
    await asyncio.gather(*(one(n) for n in missing))


# ---------- citations ----------

WIKI_CITE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]")   # [[source-slug|5.5.1]]
WIKI_LINK = re.compile(r"\[\[([^\]|]+)\]\]")                            # [[page]]: a whole page, not a paragraph
BRACKET = re.compile(r"(?<!\[)\[([^\[\]\n]{1,60})\](?!\])")              # [5.5.4], [B5.5.43], [Appendix A: credit loss]
LABEL_LINE = re.compile(r"^\[([^\]\n]+)\][ \t]*", re.M)
STANDARD_NAME = re.compile(r"\b(?:IFRS|IAS|IFRIC|SIC)\s*\d+\b")
Q_PREFIX = re.compile(r"^Q\d+[.):]\s*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z*\[(])")


APPENDIX = re.compile(r"^\s*App(?:endix)?\.?\s*([A-Z])\s*[:.\-–]\s*", re.I)  # "AppA: credit loss", "Appendix A - ..."


def _is_clause(s: str) -> bool:
    return bool(re.search(r"\d", s)) or bool(APPENDIX.match(s))


def _parts(label: str) -> list[str]:
    """The paragraphs a citation label names: "B5.5.30(a), B5.5.30(b)" -> both; "5.5.13–5.5.16" -> each end."""
    label = STANDARD_NAME.sub(" ", label)
    label = re.sub(r"\b(?:paragraphs?|paras?|para\.)\s*", "", label, flags=re.I)
    if m := APPENDIX.match(label):
        term = label[m.end():].strip(" .")
        return [f"Appendix {m.group(1).upper()}: {term}"] if term else []
    out = []
    for p in re.split(r",|;|\band\b|&", label):
        for q in re.split(r"\s*[–-]\s*", p.strip()):
            q = q.strip(" .")
            if q and _is_clause(q):
                out.append(q)
    return out


def _lookup_keys(part: str) -> list[str]:
    keys = [part]
    base = re.sub(r"(\([a-z0-9]{1,4}\))+$", "", part)  # sub-paragraph letters: B5.5.30(a) -> B5.5.30
    if base != part:
        keys.append(base)
    return keys


def citations(answer: str) -> list[dict]:
    """Each citation in the answer with the statement it is attached to (the sentence it ends, citations removed)."""
    out, seen = [], set()
    for line in answer.splitlines():
        for sent in SENTENCE_END.split(line):
            found = [("source", m.group(1).strip(), m.group(2).strip()) for m in WIKI_CITE.finditer(sent)]
            found += [("page", m.group(1).strip(), "") for m in WIKI_LINK.finditer(sent)]
            rest = WIKI_LINK.sub(" ", WIKI_CITE.sub(" ", sent))
            found += [("bare", "", m.group(1).strip()) for m in BRACKET.finditer(rest) if _is_clause(m.group(1))]
            if not found:
                continue
            statement = " ".join(BRACKET.sub(" ", WIKI_LINK.sub(" ", WIKI_CITE.sub(" ", sent))).split()).strip(" *-•")
            statement = re.sub(r"\s+([.,;:])", r"\1", statement)
            for kind, src, label in found:
                key = (kind, src, label, statement)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"kind": kind, "source": src, "label": label, "statement": statement})
    return out


class Library:
    """The Standard's own paragraphs, from the source texts the wikis keep (read only)."""

    def __init__(self, conn: psycopg.Connection):
        self.by_source: dict[str, dict[str, str]] = {}
        self.titles: dict[str, str] = {}
        for r in conn.execute("""select distinct on (s.slug) s.slug, s.title, s.text from wiki.sources s
                                 order by s.slug, length(s.text) desc"""):
            paras: dict[str, str] = {}
            ms = list(LABEL_LINE.finditer(r["text"] or ""))
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(r["text"])
                key = " ".join(m.group(1).split())
                paras[key] = (paras.get(key, "") + "\n" + r["text"][m.end():end].strip()).strip()
            self.by_source[r["slug"]] = paras
            self.titles[r["slug"]] = r["title"]

    def find(self, part: str, source: str | None = None) -> list[tuple[str, str]]:
        """(source slug, paragraph text) for each source holding this paragraph; only the named source when given."""
        hits = []
        for slug, paras in self.by_source.items():
            if source and slug != source:
                continue
            for k in _lookup_keys(part):
                if k in paras:
                    hits.append((slug, paras[k]))
                    break
        return hits


def resolve(cites: list[dict], lib: Library) -> list[dict]:
    """Attach each citation's paragraph text, or why it cannot be checked."""
    for c in cites:
        if c["kind"] == "page":
            c["status"], c["reason"] = "not_checkable", "points to a whole page, not a paragraph"
            continue
        parts = _parts(c["label"])
        if not parts:
            c["status"], c["reason"] = "not_checkable", "no paragraph number in the citation"
            continue
        texts, wrong_source, missing = [], [], []
        for p in parts:
            hits = lib.find(p, c["source"] or None)
            if not hits and c["source"]:
                if lib.find(p):
                    wrong_source.append(p)
                    continue
            if not hits:
                missing.append(p)
                continue
            for slug, text in hits:
                texts.append({"paragraph": p, "source": lib.titles.get(slug, slug), "text": text[:MAX_PARAGRAPH]})
        if wrong_source and not texts:
            c["status"], c["reason"] = "not_supported", f"names a source that does not hold {', '.join(wrong_source)}"
        elif not texts:
            c["status"], c["reason"] = "not_checkable", f"{', '.join(missing)} is not in the source texts available"
        else:
            c["paragraphs"] = texts
            c["status"] = "to_check"
    return cites


# ---------- the check call ----------

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "status": {"type": "string", "enum": ["answered", "partly", "not_answered"]},
            "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "status": {"type": "string", "enum": ["stated", "contradicted", "not_stated"]},
            "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
        "citations": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "status": {"type": "string", "enum": ["supported", "partly", "not_supported"]},
            "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
    },
    "required": ["questions", "facts", "citations"], "additionalProperties": False,
}

CHECK_SYSTEM = """You check one answer to a set of IFRS questions. You are not told which system wrote it.
Return one entry for every item listed, using its id, with a short note.
1. Questions (Q1, Q2, ...): does the answer address the question? answered = a direct, substantive answer to all of it;
   partly = only part of it, or only vaguely; not_answered = missing, or the answer says it cannot answer.
   Judge whether it is addressed, not whether it is correct.
2. Facts (F1, F2, ...): does the answer state the fact? stated = the same content (wording may differ, but numbers,
   periods, thresholds and yes/no answers must match exactly); contradicted = it states something incompatible;
   not_stated = it does not say it.
3. Citations (C1, C2, ...): each gives a statement from the answer and the text of the paragraph(s) it cites.
   supported = the cited text says what the statement claims, or directly backs it; partly = it backs only part of the
   statement; not_supported = it does not back it. Use only the cited text, not your own knowledge."""


def _check_user(questions: list[str], facts: list[dict], cites: list[dict], answer: str) -> str:
    qs = "\n".join(f"Q{i}: {Q_PREFIX.sub('', q)}" for i, q in enumerate(questions, 1)) or "(none)"
    fs = "\n".join(f"{f['id']}: {f['fact']}" for f in facts) or "(none)"
    cs = []
    for c in cites:
        paras = "\n".join(f"  [{p['paragraph']}] ({p['source']}): {p['text']}" for p in c["paragraphs"])
        cs.append(f"{c['id']}: statement: {c['statement']}\n  cites: {c['label']}\n{paras}")
    return (f"<questions>\n{qs}\n</questions>\n\n<facts>\n{fs}\n</facts>\n\n<citations>\n" + ("\n\n".join(cs) or "(none)")
            + f"\n</citations>\n\n<answer>\n{answer}\n</answer>")


def prepare(answer: str, questions: list[str], facts: list[dict] | None, lib: Library) -> dict:
    """Everything the check call needs; the citations that cannot be checked are already settled."""
    cites = resolve(citations(answer), lib)
    to_check = [c for c in cites if c["status"] == "to_check"]
    for i, c in enumerate(to_check[:MAX_CITATIONS], 1):
        c["id"] = f"C{i}"
    for c in to_check[MAX_CITATIONS:]:
        c["status"], c["reason"] = "not_checkable", f"over the {MAX_CITATIONS} citations checked per answer"
    sent = [c for c in to_check if c.get("id")]
    return {"questions": questions, "facts": facts or [], "cites": cites,
            "user": _check_user(questions, facts or [], sent, answer)}


def score(prep: dict, result: dict | None, facts_info: dict) -> tuple[dict, dict]:
    """The stored check record and the three metrics, from the judge's verdicts."""
    from .metrics import measured, not_measured
    d = (result or {}).get("data") or {"questions": [], "facts": [], "citations": []}
    qv = {x["id"]: x for x in d["questions"]}
    fv = {x["id"]: x for x in d["facts"]}
    cv = {x["id"]: x for x in d["citations"]}
    qs = [{"id": f"Q{i}", "question": q, **{k: qv.get(f"Q{i}", {}).get(k) for k in ("status", "note")}}
          for i, q in enumerate(prep["questions"], 1)]
    fs = [{**f, **{k: fv.get(f["id"], {}).get(k) for k in ("status", "note")}} for f in prep["facts"]]
    cs = []
    for c in prep["cites"]:
        c = {k: v for k, v in c.items() if k != "paragraphs"} | ({"paragraphs": [p["paragraph"] for p in c["paragraphs"]]} if c.get("paragraphs") else {})
        if c.get("id"):
            v = cv.get(c["id"], {})
            c["status"], c["note"] = v.get("status"), v.get("note")
        cs.append(c)
    m = {}
    qscores = [WEIGHT[q["status"]] for q in qs if q["status"] in WEIGHT]
    m["completeness"] = (measured(round(100 * sum(qscores) / len(qscores), 1)) if qscores
                         else not_measured("no questions found in the topic" if not qs else "the judge returned no verdicts"))
    if not fs:
        m["exact_match"] = not_measured("the reference answer for this topic has no exact-match facts"
                                        if facts_info.get("made") else "no exact-match fact list for this topic yet")
    else:
        got = [f for f in fs if f["status"]]
        m["exact_match"] = (measured(round(100 * sum(f["status"] == "stated" for f in got) / len(got), 1)) if got
                            else not_measured("the judge returned no verdicts"))
    scored = [c for c in cs if c["status"] in ("supported", "partly", "not_supported")]
    if scored:
        m["citation_accuracy"] = measured(round(100 * sum(WEIGHT.get(c["status"], 0.5) for c in scored) / len(scored), 1))
    else:
        n_un = sum(c["status"] == "not_checkable" for c in cs)
        m["citation_accuracy"] = not_measured("the answer has no citations" if not cs
                                              else f"none of its {n_un} citation(s) could be checked against a paragraph")
    counts = {"citations": len(cs), "checked": len(scored), "not_checkable": sum(c["status"] == "not_checkable" for c in cs),
              "supported": sum(c["status"] == "supported" for c in cs), "partly": sum(c["status"] == "partly" for c in cs),
              "not_supported": sum(c["status"] == "not_supported" for c in cs),
              "facts_contradicted": sum(f["status"] == "contradicted" for f in fs)}
    rec = {"version": VERSION, "model": (result or {}).get("model"), "backend": (result or {}).get("backend"),
           "usage": (result or {}).get("usage"), "batch": (result or {}).get("batch", False), "facts_used": facts_info,
           "questions": qs, "facts": fs, "citations": cs, "counts": counts}
    return rec, m


# ---------- running the checks on a run's answers ----------

def _facts_info(rubric_row: dict | None) -> dict:
    if not rubric_row:
        return {"made": False}
    return {"made": rubric_row.get("facts") is not None, "version": rubric_row.get("version"),
            "approved": rubric_row["facts_reviewed_at"].isoformat(timespec="seconds") if rubric_row.get("facts_reviewed_at") else None}


def _todo(data: dict, rubric_rows: dict[int, dict]):
    """(topic rec, rep, system, answer) for every saved answer whose checks are missing or used an older fact list."""
    for rec in data.get("topics", {}).values():
        info = _facts_info(rubric_rows.get(rec["number"]))
        for rid, run in rec.get("runs", {}).items():
            for sysname, ans in (run.get("systems") or run.get("answers") or {}).items():
                done = ans.get("checks") or {}
                if done.get("version") == VERSION and (done.get("facts_used") or {}).get("version") == info.get("version") \
                        and (done.get("facts_used") or {}).get("approved") == info.get("approved"):
                    continue
                yield rec, rid, sysname, ans, info


async def run_checks(data: dict, conn: psycopg.Connection, ref_sha: str, sem: asyncio.Semaphore, use_batch: bool,
                     save, log=print, lock: asyncio.Lock | None = None) -> int:
    """Check every saved answer that needs it; each result is kept as it arrives (save() is awaited after each)."""
    s = get_settings()
    lock = lock or asyncio.Lock()
    rubric_rows = {r["topic_number"]: r for r in conn.execute(
        "select topic_number, facts, version, facts_reviewed_at from bench.rubrics where reference_sha256 = %s", (ref_sha,))}
    todo = list(_todo(data, rubric_rows))
    if not todo:
        return 0
    lib = await asyncio.to_thread(Library, conn)
    preps = {}
    for rec, rid, sysname, ans, info in todo:
        facts = (rubric_rows.get(rec["number"]) or {}).get("facts")
        preps[f"t{rec['number']}-r{rid}-{sysname}"] = (ans, info, prepare(ans.get("answer") or "", questions_of(rec.get("question")), facts, lib))
    log(f"Answer checks: {len(preps)} answer(s), {s.checks_model}")

    async def keep(key, result):
        ans, info, prep = preps[key]
        rec, m = score(prep, result, info)
        async with lock:
            ans["checks"] = rec
            ans["metrics"] = {**(ans.get("metrics") or {}), **m}
            await save()

    left = list(preps)
    if use_batch and s.judge_backend == "api":
        reqs = {k: judge._params(CHECK_SYSTEM, preps[k][2]["user"], CHECK_SCHEMA, s.checks_model) for k in left}
        try:
            got = await judge.grade_batch(reqs, None, lambda _id: asyncio.sleep(0), log, "answer checks")
            left = []
            for k, res in got.items():
                if isinstance(res, Exception):
                    left.append(k)
                else:
                    await keep(k, res)
        except Exception as e:
            log(f"  answer checks batch failed ({type(e).__name__}: {e}); checking normally")
    failed = 0

    async def one(k):
        nonlocal failed
        async with sem:
            try:
                await keep(k, await judge._json_call(CHECK_SYSTEM, preps[k][2]["user"], CHECK_SCHEMA, s.checks_model))
            except Exception as e:
                failed += 1
                log(f"  {k}: answer checks failed ({type(e).__name__}: {e})")
    await asyncio.gather(*(one(k) for k in left))
    log(f"Answer checks done: {len(preps) - failed} of {len(preps)}")
    return len(preps) - failed


def backfill(run_ids: list[str]) -> None:
    """Run the answer checks on saved runs (answers are not asked again), then refresh their summaries."""
    from . import rubric
    from .metrics import compute
    from .run import aggregate
    s = get_settings()
    conn = psycopg.connect(s.database_url, autocommit=True, row_factory=dict_row)
    if run_ids == ["all"]:
        run_ids = [r["id"] for r in conn.execute("select id from bench.runs where results is not null order by created_at")]
    for rid in run_ids:
        row = conn.execute("select results, mode, reference from bench.runs where id = %s", (rid,)).fetchone()
        if not row or not row["results"] or not row["reference"]:
            print(f"{rid}: no results or no reference file")
            continue
        data, ref_sha = row["results"], rubric.sha256(row["reference"])
        asyncio.run(facts_for_reference(conn, ref_sha))

        async def save():
            await asyncio.to_thread(conn.execute, "update bench.runs set results = %s where id = %s", (Jsonb(data), rid))
        print(f"{rid}:", flush=True)
        asyncio.run(run_checks(data, conn, ref_sha, asyncio.Semaphore(s.concurrency), False, save, lambda m: print(m, flush=True)))
        asyncio.run(compute(data, row["mode"]))
        aggregate(data)
        conn.execute("update bench.runs set results = %s where id = %s", (Jsonb(data), rid))
        by = data["metrics"]["by_system"]
        print(f"{rid}: " + " | ".join(f"{k}: " + ", ".join(
            f"{n} {v[k].get('mean') if v[k].get('mean') is not None else 'not measured'}" for n, v in by.items())
            for k in ("completeness", "exact_match", "citation_accuracy")), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["facts"] and len(sys.argv) == 3:
        c = psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row)
        asyncio.run(facts_for_reference(c, sys.argv[2], lambda m: print(m, flush=True)))
    elif sys.argv[1:2] == ["backfill"] and len(sys.argv) > 2:
        backfill(sys.argv[2:])
    else:
        sys.exit(__doc__)
