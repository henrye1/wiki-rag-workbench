"""Multi-source synthesis: how well each answer brings together a topic's key points when they come from more than one
source document. Worked out only from what a run stored (its key points, the paragraph each names as backing it, and
the judge's grades in both orders) and the documents the wikis keep (their names and paragraph labels); no model or
API call, so it shows for every run already graded.

- A key point's document is the document holding the paragraph its backing reference names, e.g. "5.5.1 (<document>)".
  The name in brackets picks the document; where it fits more than one (a shorter name), the one holding the paragraph
  label is taken. A key point naming no backing paragraph, or one that fits no single document, is left out.
- A topic is multi-source when its key points come from two or more documents. Its main document is the one most of
  its key points come from (a tie goes to a "standard" tier document, then a "supporting" one, then by name).
- Secondary-document coverage: the share of the key points from the other documents an answer covered (full = 1,
  partial = 0.5, missing = 0).
- All documents covered: the share of answers that covered at least half of the key points from every document the
  topic needs.
Each is read per grading order and averaged over the two orders, then over a topic's graded repetitions, as coverage
is. The wiki-minus-RAG gap and its 95% interval come from resampling the multi-source topics, in the same way as the
run's other gaps (Benchmark/bench/gaps.py; the benchmark runs in its own environment, so it is not imported here)."""
import random
import re
import statistics

KEYS = ("ms_secondary", "ms_all_docs")
WEIGHT = {"full": 1.0, "partial": 0.5, "missing": 0.0}
HALF = 0.5  # "covered" for a document: at least this share of its key points
TIER_ORDER = {"standard": 0, "supporting": 1}
RESAMPLES = 10_000
_REF = re.compile(r"^(.*?)\s+\((.+)\)\s*$")  # "<label> (<document>)"; a label's own "(a)" has no space before it
_SUB = re.compile(r"(\s*\([a-z0-9]{1,4}\))+$")  # sub-paragraph letters, e.g. "5.5.17(a)"


def _holds(labels: set[str], label: str) -> bool:
    return label in labels or _SUB.sub("", label) in labels


def resolve(ref: str | None, docs: list[dict]) -> str | None:
    """The name of the document a backing reference points to, or None. docs: [{name, labels}] for the candidate
    documents (one entry per name; labels: the paragraph labels it holds)."""
    if not ref or not ref.strip():
        return None
    m = _REF.match(ref.strip())
    label, said = (m.group(1).strip(), m.group(2).strip()) if m else (ref.strip(), "")
    holders = {d["name"] for d in docs if _holds(d["labels"], label)}
    if said:
        # the name given, or a longer form of it ("<name> (<more>)"): the longest name that fits
        named = [d["name"] for d in docs if said == d["name"] or said.startswith(d["name"] + " ")]
        if named:
            best = max(len(n) for n in named)
            named = {n for n in named if len(n) == best}
            pick = named & holders if len(named) > 1 else named
            return next(iter(pick)) if len(pick) == 1 else None
        # a shorter name than the documents' ("<name>" for "<name> <part>"): the one holding the paragraph
        wider = {d["name"] for d in docs if d["name"].startswith(said + " ")}
        pick = wider & holders if len(wider) > 1 else wider
        return next(iter(pick)) if len(pick) == 1 else None
    return next(iter(holders)) if len(holders) == 1 else None


def topic_documents(points: list[dict], docs: list[dict]) -> tuple[dict[str, str], int]:
    """(key point id -> its document name, how many key points were left out)."""
    out, left = {}, 0
    for p in points:
        d = resolve(p.get("ref"), docs)
        if d:
            out[p["id"]] = d
        else:
            left += 1
    return out, left


def main_document(doc_of: dict[str, str], tiers: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for d in doc_of.values():
        counts[d] = counts.get(d, 0) + 1
    return min(counts, key=lambda d: (-counts[d], TIER_ORDER.get(tiers.get(d, ""), 2), d))


def _scores(grades: dict, doc_of: dict[str, str], main: str) -> dict[str, float | None]:
    """One grading order's two figures (0-100) for one answer."""
    by_doc: dict[str, list[float]] = {}
    for pid, d in doc_of.items():
        by_doc.setdefault(d, []).append(WEIGHT.get(grades.get(pid, "missing"), 0.0))
    secondary = [w for d, ws in by_doc.items() if d != main for w in ws]
    return {"ms_secondary": 100 * sum(secondary) / len(secondary) if secondary else None,
            "ms_all_docs": 100.0 if all(sum(ws) / len(ws) >= HALF for ws in by_doc.values()) else 0.0}


def _orders(graded: dict | None) -> list[dict]:
    if not graded:
        return []
    return graded.get("grades_by_order") or ([graded["grades"]] if graded.get("grades") else [])


def _answer(graded: dict | None, doc_of: dict, main: str) -> dict[str, float]:
    """One answer's figures: each order's, averaged over the orders."""
    per = [_scores(g, doc_of, main) for g in _orders(graded)]
    out = {}
    for k in KEYS:
        xs = [x[k] for x in per if x[k] is not None]
        if xs:
            out[k] = statistics.mean(xs)
    return out


def _graded(run: dict, pair: str, side: str) -> dict | None:
    """An answer as graded in a pair: the RAG column's own grading; the wiki's in that column's pair."""
    if side == "wiki" and pair != "rag":
        return ((run.get("pairs") or {}).get(pair) or {}).get("wiki")
    return (run.get("systems") or {}).get(side)


def _gap(diffs: list[float], seed, k: str, rag: str) -> dict | None:
    """As Benchmark/bench/gaps.py: mean wiki-minus-RAG difference over topics, 95% interval from 10,000 resamples."""
    if not diffs:
        return None
    entry = {"diff": round(statistics.mean(diffs), 4), "n_topics": len(diffs), "better": "higher"}
    if len(diffs) < 2:
        return {**entry, "ci": None, "leader": None, "verdict": "too few topics for an interval"}
    rng = random.Random(f"{seed}-{k}")
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(RESAMPLES))
    lo, hi = means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]
    leader = "wiki" if lo > 0 else rag if hi < 0 else None
    return {**entry, "ci": [round(lo, 4), round(hi, 4)], "leader": leader,
            "verdict": f"{'Wiki' if leader == 'wiki' else 'RAG'} better" if leader else "no clear difference"}


def measure(data: dict, docs: list[dict], seed=42) -> dict:
    """The run's multi-source figures per RAG column against the wiki: {topics, multi_source, points, left_out,
    pairs: {pair: {by_system: {sys: {k: {mean, n}}}, gaps: {k: gap}}}}. docs: [{name, tier, labels}] for the documents a
    backing reference may point to."""
    pairs_of = [s for s in ((data.get("config") or {}).get("systems_compared") or []) if s != "wiki"]
    tiers = {d["name"]: d.get("tier") for d in docs}
    topics, multi, points, left = 0, [], 0, 0
    for n, rec in (data.get("topics") or {}).items():
        kps = rec.get("key_points") or []
        if not kps:
            continue
        topics += 1
        doc_of, out = topic_documents(kps, docs)
        points += len(kps)
        left += out
        if len(set(doc_of.values())) >= 2:
            multi.append((n, rec, doc_of, main_document(doc_of, tiers)))
    result = {"topics": topics, "multi_source": len(multi), "points": points, "left_out": left,
              "multi_source_topics": sorted(int(n) if str(n).isdigit() else n for n, *_ in multi), "pairs": {}}
    for pair in pairs_of:
        per_topic: dict[str, dict[str, list[float]]] = {k: {} for k in KEYS}  # k -> side -> topic values
        diffs: dict[str, list[float]] = {k: [] for k in KEYS}
        for n, rec, doc_of, main in multi:
            vals: dict[str, dict[str, list[float]]] = {k: {pair: [], "wiki": []} for k in KEYS}
            for run in (rec.get("runs") or {}).values():
                if not run.get("judgement"):
                    continue
                for side in (pair, "wiki"):
                    for k, v in _answer(_graded(run, pair, side), doc_of, main).items():
                        vals[k][side].append(v)
            for k in KEYS:
                means = {s: statistics.mean(v) for s, v in vals[k].items() if v}
                for s, v in means.items():
                    per_topic[k].setdefault(s, []).append(v)
                if pair in means and "wiki" in means:
                    diffs[k].append(means["wiki"] - means[pair])
        result["pairs"][pair] = {
            "by_system": {s: {k: {"mean": round(statistics.mean(per_topic[k][s]), 2), "n": len(per_topic[k][s])}
                              for k in KEYS if per_topic[k].get(s)} for s in (pair, "wiki")},
            "gaps": {k: g for k in KEYS if (g := _gap(diffs[k], seed, k, pair))},
        }
    return result
