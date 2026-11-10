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
