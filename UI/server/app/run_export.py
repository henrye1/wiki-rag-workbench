"""Downloads of one benchmark run, read only: its results (one row per topic, run and system), all its answers, and a
side-by-side review page. Each is built from the run as the run page receives it (GET /api/bench/runs/{id}), so the
reference memo is named only by its label, never by its file name."""
import csv
import html
import io
import re

LINK = re.compile(r"\[\[[^\]|]+\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")  # a wiki link shows its label (or its slug)
METRICS = ("completeness", "faithfulness", "citation_accuracy", "context_recall", "context_recall_standard",
           "exact_match", "exact_match_standard", "cost_usd")
GRADES = ("full", "partial", "missing")


def _topics(data: dict) -> list[dict]:
    return sorted((data.get("topics") or {}).values(), key=lambda t: t.get("number") or 0)


def _systems(data: dict) -> list[str]:
    return list((data.get("config") or {}).get("systems_compared") or [])


def _runs(t: dict) -> list[tuple[str, dict]]:
    return sorted((t.get("runs") or {}).items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)


def _answer(r: dict, sys: str) -> dict:
    return (r.get("systems") or {}).get(sys) or {}


def _winner(r: dict, sys: str) -> str:
    """The run's winner in the pair this system was graded in: the RAG (per question) column and the wiki's figures
    against it are from that pair's own grading."""
    if sys == "rag_q":
        return ((r.get("pairs") or {}).get("rag_q") or {}).get("winner") or ""
    return r.get("winner") or ""


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # the mark lets Excel read the file as UTF-8


def results_csv(data: dict, label: dict) -> bytes:
    """One row per topic, run and system: the judged scores, the key points' grades, contradictions, the run's winner,
    and the measured metrics."""
    rows = []
    for t in _topics(data):
        for n, r in _runs(t):
            for sys in _systems(data):
                a = _answer(r, sys)
                if not a:
                    continue
                grades = list((a.get("grades") or {}).values())
                m = a.get("metrics") or {}
                rows.append([t.get("number"), t.get("code"), t.get("title"), t.get("section"), n, label.get(sys, sys),
                             a.get("similarity"), a.get("coverage"), a.get("coverage_standard"), a.get("coverage_std_supp"),
                             *(grades.count(g) for g in GRADES), len(a.get("contradictions") or []), _winner(r, sys),
                             a.get("latency_s"), *((m.get(k) or {}).get("value") for k in METRICS)])
    return _csv(["topic", "code", "title", "section", "run", "system", "similarity (0-10)", "coverage %",
                 "standard-only coverage %", "standard + supporting coverage %", "key points full", "key points partial",
                 "key points missing", "contradictions", "winner of the run", "latency s", *METRICS], rows)


def _plain(text: str) -> str:
    return LINK.sub(lambda m: m.group(1) or m.group(2), text or "")


def _read(a: dict) -> str:
    """What the answer read: the wiki's pages (titles), a RAG answer's passages (references)."""
    out = []
    for x in a.get("read") or []:
        if isinstance(x, dict):
            out.append(str(x.get("title") or x.get("para_ref") or x.get("ref") or x.get("slug") or ""))
        else:
            out.append(str(x))
    return "; ".join(x for x in out if x)


def answers_csv(data: dict, label: dict) -> bytes:
    """Every answer of the run, as each system gave it, with the question, what it read and its latency."""
    rows = []
    for t in _topics(data):
        for n, r in _runs(t):
            for sys in _systems(data):
                a = _answer(r, sys)
                if a:
                    rows.append([t.get("number"), t.get("code"), t.get("title"), n, label.get(sys, sys), t.get("question"),
                                 a.get("answer"), _read(a), a.get("latency_s")])
    return _csv(["topic", "code", "title", "run", "system", "question", "answer", "read", "latency s"], rows)


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def review_html(data: dict, label: dict, run_id: str) -> bytes:
    """A page to read beside the run page: for each topic its question, the reference text, the key points with each
    system's grade, and the answers of every system side by side, run by run."""
    systems = _systems(data)
    parts = []
    for t in _topics(data):
        runs = _runs(t)
        head = "".join(f"<th>{_e(label.get(s, s))}</th>" for s in systems)
        points = "".join(
            f"<tr><td>{_e(p.get('id'))}</td><td>{_e(p.get('point'))}<div class=m>{_e(p.get('kind'))}</div></td>"
            + "".join("<td>" + " / ".join(_e((_answer(r, s).get('grades') or {}).get(p.get('id'), '—')) for _, r in runs) + "</td>"
                      for s in systems) + "</tr>"
            for p in t.get("key_points") or [])
        answers = "".join(
            f"<h4>Run {_e(n)}</h4><div class=cols style='grid-template-columns:repeat({len(systems)},1fr)'>"
            + "".join(f"<div class=ans><div class=sys>{_e(label.get(s, s))}"
                      f"<span class=m> · similarity {_e(_answer(r, s).get('similarity'))}/10 · coverage {_e(_answer(r, s).get('coverage'))}%"
                      f"{' · winner' if _winner(r, s) == s else ''}</span></div>"
                      f"<pre>{_e(_plain(_answer(r, s).get('answer')))}</pre></div>" for s in systems)
            + "</div>" for n, r in runs)
        parts.append(
            f"<section id=t{_e(t.get('number'))}><h2>{_e(t.get('number'))}. {_e(t.get('title'))}</h2>"
            f"<div class=m>{_e(t.get('code'))} · {_e(t.get('section'))}</div>"
            f"<h3>Question</h3><pre>{_e(t.get('question'))}</pre>"
            f"<details><summary>Reference text ({_e(data.get('reference_label') or 'reference memo')})</summary><pre>{_e(t.get('reference'))}</pre></details>"
            f"<h3>Key points: grade per run</h3><table><thead><tr><th>#</th><th>Point</th>{head}</tr></thead><tbody>{points}</tbody></table>"
            f"<h3>Answers</h3>{answers}</section>")
    toc = "".join(f"<a href='#t{_e(t.get('number'))}'>{_e(t.get('number'))}</a> " for t in _topics(data))
    cfg = data.get("config") or {}
    compared = data.get("compared") or {}
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Run {_e(run_id)} review</title><style>
body{{font:14px/1.45 system-ui,sans-serif;margin:16px;color:#1b1b1f;background:#fff}} h1{{font-size:20px}} h2{{font-size:17px;margin-top:28px}}
h3{{font-size:14px;margin:14px 0 6px}} h4{{margin:10px 0 4px}} .m{{color:#666;font-size:12px}}
pre{{white-space:pre-wrap;word-wrap:break-word;font:13px/1.45 system-ui,sans-serif;margin:0}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:4px 6px;vertical-align:top;text-align:left}}
.cols{{display:grid;gap:10px}} .ans{{border:1px solid #ddd;border-radius:6px;padding:8px;min-width:0}} .sys{{font-weight:600;margin-bottom:6px}}
section{{border-top:2px solid #eee}} nav a{{margin-right:4px}}
@media (max-width:800px){{.cols{{grid-template-columns:1fr!important}}}}
</style></head><body>
<h1>Run {_e(run_id)}: side-by-side review</h1>
<p class=m>{_e(compared.get('rag_collection'))} vs {_e(compared.get('wiki'))} · judge {_e(cfg.get('judge_model'))} · {_e(cfg.get('runs'))} run(s) per topic ·
reference: {_e(data.get('reference_label') or 'reference memo')} · grades read full / partial / missing, one per run</p>
<nav>Topics: {toc}</nav>{''.join(parts)}</body></html>"""
    return page.encode("utf-8")


def unmasked(blob: bytes, names: list[str]) -> list[str]:
    """Memo file names still in a download (it is refused if any are)."""
    text = blob.decode("utf-8", errors="replace")
    return [n for n in names if n in text]


# ---------- the summary scorecard, as the run page shows it (UI/web/.../benchmark/run.ts: score, extra, gapFor) ----------
GAP_ORDER = ("similarity", "std_similarity", "coverage", "coverage_standard", "coverage_std_supp", "wins", "contradictions",
             "no_contradiction", "completeness", "exact_match", "exact_match_standard", "citation_accuracy", "faithfulness",
             "context_recall", "context_recall_standard", "latency_s", "cost_usd")
GAP_LABEL = {
    "similarity": "Similarity (0–10)", "coverage": "Coverage", "coverage_standard": "Standard-only coverage",
    "coverage_std_supp": "Standard + Supporting coverage", "exact_match_standard": "Standard-only exact match",
    "wins": "Wins (gap: share of answers)", "exact_match": "Exact match", "faithfulness": "Faithfulness",
    "citation_accuracy": "Citation accuracy", "context_recall": "Context recall", "context_recall_standard": "Standard-only context recall",
    "completeness": "Completeness", "latency_s": "Latency (s, lower is better)", "cost_usd": "Cost per query (lower is better)",
    "std_similarity": "Standard-only similarity (0–10)", "contradictions": "Contradictions per answer (lower is better)",
    "no_contradiction": "Answers with no contradiction",
}
JUDGED = ("similarity", "coverage", "coverage_standard", "coverage_std_supp")
EXTRAS = ("std_similarity", "contradictions", "no_contradiction")
COUNTED = ("contradictions", "no_contradiction")


def _g(obj, *keys):
    for k in keys:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def _std_sim(d: dict, pair: str):
    return _g(d, "extras", "std_similarity") if pair == "rag" else _g(d, "extras", "pairs", pair, "std_similarity")


def _fmt_metric(k: str, v: float) -> str:
    return f"${v:.4f}" if k == "cost_usd" else f"{v:.1f} s" if k == "latency_s" else f"{v:.1f}%"


def _fmt_gap(k: str, v: float) -> str:
    sign, a = ("+" if v > 0 else "−" if v < 0 else ""), abs(v)
    if k == "cost_usd":
        return f"{sign}${a:.4f}"
    if k == "latency_s":
        return f"{sign}{a:.1f} s"
    if k in ("similarity", "std_similarity"):
        return f"{sign}{a:.2f}"
    if k == "wins":
        return f"{sign}{a * 100:.0f} pts"
    return f"{sign}{a:.1f} pts"


def _extra(d: dict, sys: str, k: str, pair: str) -> tuple[bool, str, object, str]:
    """(ok, text, value, reason) of an extra measure, as the page's extra()."""
    no = lambda why: (False, "not measured", None, why)
    if k == "std_similarity":
        v = _g(_std_sim(d, pair), "by_system", sys)
        if not v or v.get("mean") is None:
            failed = _g(d, "extras", "std_similarity_failed")
            return no(f"failed: {failed}" if failed else "Quick mode: standard-only similarity runs only in Full mode"
                      if _g(d, "config", "mode") == "quick" else "standard-only similarity was not run on this run")
        return True, f"{v['mean']}/10", v["mean"], f"{v.get('n_topics')} topic(s)"
    c = _g(d, "extras", "pairs", pair, "contradictions", "wiki") if sys == "wiki" and pair != "rag" else _g(d, "extras", "contradictions", sys)
    if not c:
        return no("no answer in this run was checked for contradictions")
    if k == "contradictions":
        return True, f"{c['mean']:.2f}", c["mean"], f"{c['n']} answer(s)"
    return True, f"{c['none']} of {c['n']} ({c['none_pct']:.0f}%)", c["none_pct"], f"{c['n']} answer(s)"


def _score(d: dict, sys: str, k: str, pair: str) -> tuple[bool, str, object, str]:
    """(ok, text, value, reason) of one system on one test in one pair, as the page's score()."""
    if k in EXTRAS:
        return _extra(d, sys, k, pair)
    no = lambda why: (False, "Not run yet", None, why)
    s = d.get("summary")
    if not s:
        return no("the run has not finished")
    other = _g(s, "pairs", pair) if pair != "rag" else None
    if k == "wins":
        n = ((other or {}).get("wins_by_run") if other else s.get("wins_by_run") or {}) or {}
        return True, str(n.get(sys) or 0), n.get(sys) or 0, "answers won (both grading orders agreeing)"
    if k in JUDGED:
        v = _g(other, "wiki", k) if sys == "wiki" and other else _g(s, "by_system", sys, k)
        if v and v.get("mean") is not None:
            return True, f"{v['mean']}/10" if k == "similarity" else f"{v['mean']}%", v["mean"], f"{v.get('n')} topic(s)"
        if k == "coverage_std_supp" and _g(d, "config", "sources") == "standard":
            return no("this run used Standard only (Part A), so Supporting points were not in play")
        return no("no graded answers")
    m = _g(d, "metrics", "by_system", sys, k)
    if not m:
        return no("not measured in this run")
    if m.get("status") != "measured" or m.get("mean") is None:
        return no(m.get("reason") or "not measured")
    return (True, _fmt_metric(k, m["mean"]), m["mean"],
            f"{m.get('n')} answer(s)" + ("; some not measured" if m.get("not_measured_in") else ""))


def _gap(d: dict, pair: str, k: str):
    if k == "std_similarity":
        return _g(_std_sim(d, pair), "gap")
    if k in COUNTED:
        return None
    return _g(d, "summary", "gaps", k) if pair == "rag" else _g(d, "summary", "pairs", pair, "gaps", k)


def scorecard_csv(data: dict, label: dict) -> bytes:
    """The run page's scorecards, one row per pair and test: each system's score as shown and as a number, the
    wiki-minus-RAG gap with its 95% interval and the verdict, or why a test has no score."""
    rows = []
    for pair in [s for s in _systems(data) if s != "wiki"]:
        for k in GAP_ORDER:
            r, w, e = _score(data, pair, k, pair), _score(data, "wiki", k, pair), _gap(data, pair, k)
            shown = bool(e) and r[0] and w[0]
            ci = (e or {}).get("ci") if shown else None
            note = "" if shown else (r[3] if not r[0] else w[3] if not w[0] else "no interval: a count per answer" if k in COUNTED else "")
            rows.append([f"Wiki vs {label.get(pair, pair)}", GAP_LABEL[k], r[1], w[1], r[2], w[2],
                         _fmt_gap(k, e["diff"]) if shown else "", e["diff"] if shown else "",
                         f"{_fmt_gap(k, ci[0])} to {_fmt_gap(k, ci[1])}" if ci else "", ci[0] if ci else "", ci[1] if ci else "",
                         e.get("verdict") if shown else "", e.get("leader") if shown and e.get("leader") else "", note,
                         r[3] if r[0] else "", w[3] if w[0] else ""])
    return _csv(["scorecard", "test", "RAG", "Wiki", "RAG value", "Wiki value", "Wiki − RAG", "Wiki − RAG value",
                 "95% confidence interval", "interval low", "interval high", "result", "leader", "note",
                 "RAG covers", "Wiki covers"], rows)
