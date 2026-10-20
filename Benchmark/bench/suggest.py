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
import re
import sys
import tempfile

import httpx

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
- Never list remarks about the reference itself (e.g. "the reference gives two approaches", "the answer lists three
  examples"): only facts about IFRS that an answer could state.
- Only facts the reference itself states. At most 10. If it has none, return an empty list."""

ITEM = {"type": "object", "properties": {
    "id": {"type": "string"},
    "tag": {"type": "string", "enum": TAGS},
    "paragraph": {"type": "string", "description": "The paragraph number that backs the tag, as shown; empty for beyond_standard"},
    "document": {"type": "string", "description": "That paragraph's document, as shown; empty for beyond_standard"},
    "check": {"type": "boolean", "description": "true ONLY if you believe a Standard does state this but none of the paragraphs shown does; "
                                                "false when it is backed by a paragraph shown, or when it comes from practice, regulation or opinion"},
    "reason": {"type": "string"}},
    "required": ["id", "tag", "paragraph", "document", "check", "reason"], "additionalProperties": False}

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
The candidate paragraphs (P1, P2, ...) are given once, in full, each marked with its document and tier; each key point
(K...) and fact (F...) lists the ids of its closest paragraphs, found by words and by meaning. Tiers:
- Standard: a Standard's own text (Part A, including its appendices);
- Supporting: documents published with the Standard (Part B implementation guidance and illustrative examples,
  Part C basis for conclusions).
1. For every key point and fact, suggest a tag from the paragraphs shown only, never from memory:
   standard = a Standard paragraph shown states its substance; supporting = only a Supporting paragraph shown states it;
   beyond_standard = no paragraph shown states it (practice, regulation, opinion, or the text shown does not say it).
   Give the paragraph number (e.g. 5.5.5, not P3) and document that back the tag (empty for beyond_standard).
   You may use any paragraph listed, not only the item's own. Set check = true only when you believe a Standard does
   say it but none of the paragraphs shown does, so a person looks it up; a point that comes from practice, regulation
   or opinion is beyond_standard with check = false.
2. Suggest merges: key points that are only items of one list in the reference (e.g. a list of indicators or
   examples) should be a single point that keeps every item. Never merge distinct requirements or conditions, and
   never merge points whose tags differ (now or as you suggest them).
   Return no merges if there are none.
Give a short reason for each."""


class Finder:
    """Candidate paragraphs for a text: by words (library.search, BM25) and by meaning (the RAG's stored passage
    embeddings, POST /search/paragraphs), merged; each candidate is a library paragraph of a ticked document."""

    def __init__(self, lib: Library, http: httpx.AsyncClient):
        self.lib, self.http, self.semantic = lib, http, True
        self.by_file = {f"{lib.titles[s]}.pdf": s for s in lib.by_source}

    async def _by_meaning(self, text: str, k: int) -> list[dict]:
        if not self.semantic:
            return []
        s = get_settings()
        try:
            r = await self.http.post(f"{s.rag_url}/search/paragraphs", json={"text": text, "k": k, "filenames": list(self.by_file)},
                                     headers={"X-API-Key": s.rag_api_key}, timeout=60)
            r.raise_for_status()
        except Exception:
            self.semantic = False  # the RAG cannot search by meaning here: words only, recorded with the suggestions
            return []
        out = []
        for h in r.json():
            slug = self.by_file.get(h["filename"])
            if slug and (hit := self.lib.find(h["para_ref"], slug)):
                out.append({"paragraph": h["para_ref"], "source": slug, "document": self.lib.names[slug],
                            "tier": self.lib.tiers[slug], "text": hit[0][1]})
        return out

    async def find(self, text: str) -> list[dict]:
        found = await self._by_meaning(text, 8) + self.lib.search(text, k=8)
        out, seen = [], set()
        for h in found:
            key = (h["source"], h["paragraph"])
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out[:14]

    def lookup(self, label: str) -> list[dict]:
        """A paragraph named in a reason (e.g. "5.5.1"), in any ticked document."""
        return [{"paragraph": label, "source": slug, "document": self.lib.names[slug], "tier": self.lib.tiers[slug], "text": text}
                for slug, text in self.lib.find(label)]


# paragraph numbers a reason may name: 5.5.1, B5.5.17, IE12, IG A.1, 35H, Appendix A: credit loss
NAMED = re.compile(r"\b(?:Appendix [A-Z]: [a-z][a-z \-]+?(?=[,.;)]|$)|IG [A-Z]\.\d+|[A-Z]{1,3}\d+(?:\.\d+)+[A-Z]?|\d+\.\d+(?:\.\d+)+[A-Z]?|IE\d+|BC\d+(?:\.\d+)*|\d{1,3}[A-Z]{1,2})\b")


def _named(reason: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).strip() for m in NAMED.finditer(reason or "")))


def _user(title: str, reference: str, items: list[tuple[str, str, str | None, list[dict]]]) -> str:
    """Every candidate paragraph once, in full, with an id; each key point and fact lists the ids of its candidates."""
    pool: dict[tuple, str] = {}
    blocks = {"K": [], "F": []}
    for iid, text, kind, cands in items:
        ids = []
        for h in cands:
            key = (h["source"], h["paragraph"])
            if key not in pool:
                pool[key] = f"P{len(pool) + 1}"
            ids.append(pool[key])
        now = f" (now tagged {kind})" if kind else ""
        blocks[iid[0] if iid[0] in blocks else "K"].append(f"{iid}{now}: {text}\n  closest paragraphs: {', '.join(ids) or '(none found)'}")
    cand = {pool[(h["source"], h["paragraph"])]: h for *_, cands in items for h in cands}
    paras = "\n\n".join(f"{pid} [{h['paragraph']}] {h['document']} ({'Standard' if h['tier'] == 'standard' else 'Supporting'}):\n"
                         f"{' '.join(h['text'].split())}" for pid, h in sorted(cand.items(), key=lambda x: int(x[0][1:])))
    return (f"Topic: {title}\n\n<reference_answer>\n{reference}\n</reference_answer>\n\n<paragraphs>\n{paras}\n</paragraphs>"
            f"\n\n<key_points>\n" + "\n\n".join(blocks["K"]) + "\n</key_points>\n\n<facts>\n"
            + ("\n\n".join(blocks["F"]) or "(none)") + "\n</facts>")


META_FACT = re.compile(r"\b(?:the )?(?:reference|memo|assessment|answer|author)\b[^.]{0,40}\b(?:gives|lists|states|describes|mentions|says|notes|"
                       r"provides|sets out|presents|offers|refers|contains|includes|discusses|explains)\b", re.I)


def _keep_fact(f: dict) -> bool:
    """A hard fact about IFRS, not a remark about the reference itself ("the reference gives two approaches")."""
    return not META_FACT.search(f["fact"])


async def suggest_topic(t, row: dict, finder: Finder) -> dict:
    """Hard facts first (from the reference), then one call that tags every key point and fact (with their candidate
    paragraphs in full) and proposes merges; items whose reason names a paragraph not shown are asked again with it."""
    hf = await judge._json_call(HARD_FACTS_SYSTEM, f"Topic: {t.title}\n\nQuestions the topic asks:\n" + "\n".join(t.questions)
                                + f"\n\n<reference_answer label=\"{t.reference_label}\">\n{t.reference}\n</reference_answer>",
                                HARD_FACTS_SCHEMA)
    facts = [f for f in hf["data"]["facts"] if _keep_fact(f)]
    dropped = [f["fact"] for f in hf["data"]["facts"] if not _keep_fact(f)]
    cands = {p["id"]: await finder.find(p["point"]) for p in row["key_points"]}
    cands |= {f["id"]: await finder.find(f["fact"]) for f in facts}
    items = [(p["id"], p["point"], p["kind"], cands[p["id"]]) for p in row["key_points"]] + [(f["id"], f["fact"], None, cands[f["id"]]) for f in facts]
    sg = await judge._json_call(SUGGEST_SYSTEM, _user(t.title, t.reference, items), SUGGEST_SCHEMA)
    d, usage = sg["data"], {"hard_facts": hf["usage"], "suggest": sg["usage"]}
    for x in d["points"] + d["facts"]:
        x["found"] = not x.pop("check", False)  # stored as "found", as the screen and export read it
    verdict = {x["id"]: x for x in d["points"] + d["facts"]}
    # second look: a reason that names a paragraph the judge was not shown gets that paragraph, and the item is asked again
    again, added = [], {}
    for iid, text, kind, cs in items:
        shown = {h["paragraph"] for h in cs}
        extra = [h for lab in _named((verdict.get(iid) or {}).get("reason", "")) if lab not in shown for h in finder.lookup(lab)]
        if extra:
            again.append((iid, text, kind, cs + extra))
            added[iid] = sorted({h["paragraph"] for h in extra})
    if again:
        sg2 = await judge._json_call(SUGGEST_SYSTEM, _user(t.title, t.reference, again), SUGGEST_SCHEMA)
        usage["second_look"] = sg2["usage"]
        for x in sg2["data"]["points"] + sg2["data"]["facts"]:
            x["found"] = not x.pop("check", False)
            if x["id"] in added:
                verdict[x["id"]] = {**x, "second_look": added[x["id"]]}
    keys = ("tag", "paragraph", "document", "found", "reason")
    ids = {p["id"] for p in row["key_points"]}
    kinds = {p["id"]: p["kind"] for p in row["key_points"]}
    merges = []
    for m in d["merges"]:
        if len(m["ids"]) < 2 or not set(m["ids"]) <= ids:
            continue
        tags = {kinds[i] for i in m["ids"]} | {(verdict.get(i) or {}).get("tag", kinds[i]) for i in m["ids"]}
        if len(tags) == 1:  # never merge points with different tags
            merges.append({**m, "status": None})
    return {
        "made_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "model": sg["model"], "backend": sg.get("backend", "api"),
        "base_version": row["version"], "usage": usage, "search": "words and meaning" if finder.semantic else "words only",
        "points": {i: {**{k: verdict[i][k] for k in keys}, **({"second_look": verdict[i]["second_look"]} if "second_look" in verdict[i] else {}),
                       "status": None} for i in ids if i in verdict},
        "merges": merges,
        "facts": {"status": None, "dropped": dropped,
                  "items": [{"id": f["id"], "fact": f["fact"], **{k: (verdict.get(f["id"]) or {}).get(k) for k in keys},
                             **({"second_look": verdict[f["id"]]["second_look"]} if "second_look" in (verdict.get(f["id"]) or {}) else {})}
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
    # only the source documents you ticked for this reference (all when none are saved)
    ref = conn.execute("select tag_sources from bench.references where reference_sha256 = %s", (ref_sha,)).fetchone()
    ticked = set(ref["tag_sources"]) if ref and ref["tag_sources"] is not None else None
    lib = await asyncio.to_thread(Library, conn, ticked)
    if not lib.by_source:
        sys.exit("None of the ticked source documents exists: tick at least one on the Rubric review screen")
    docs = [{"slug": s, "name": lib.names[s], "tier": lib.tiers[s]} for s in sorted(lib.by_source)]
    sem, lock = asyncio.Semaphore(get_settings().concurrency), asyncio.Lock()
    log(f"Suggesting rubric changes for {len(rows)} topic(s), checking tags against: {', '.join(d['name'] for d in docs)}")

    async def one(r):
        t = topics.get(r["topic_number"])
        if not t:
            log(f"  topic {r['topic_number']}: not in the query set, skipped")
            return
        try:
            async with sem:
                s = await suggest_topic(t, r, finder)
            s["documents"] = docs  # the documents these suggestions were checked against
        except Exception as e:
            log(f"  topic {r['topic_number']:>2}: failed ({type(e).__name__}: {e})")
            return
        async with lock:
            await asyncio.to_thread(conn.execute, "update bench.rubrics set suggestions = %s where reference_sha256 = %s and topic_number = %s",
                                    (Jsonb(s), ref_sha, r["topic_number"]))
        changed = sum(p["tag"] != next((k["kind"] for k in r["key_points"] if k["id"] == i), None) for i, p in s["points"].items())
        log(f"  topic {r['topic_number']:>2}: {changed} tag change(s), {len(s['merges'])} merge(s), {len(s['facts']['items'])} hard fact(s)")
    async with httpx.AsyncClient() as http:
        finder = Finder(lib, http)
        await asyncio.gather(*(one(r) for r in rows))
    log("Suggestions ready" + ("" if finder.semantic else " (searched by words only: the RAG's search by meaning was not reachable)"))


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
