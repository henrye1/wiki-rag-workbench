"""A benchmark run's summary scorecard, built in one place: the tests in their order and labels, each system's score as
shown (or why it has none), the wiki-minus-RAG gap with its 95% interval and result, and the figures the run page's
system cards show. The run page shows these rows as they are (GET /api/bench/runs/{id} carries them as "scorecard"),
and the Scorecard CSV download writes the same rows, so the two cannot disagree."""

ORDER = ("similarity", "std_similarity", "coverage", "coverage_standard", "coverage_std_supp", "wins", "contradictions",
         "no_contradiction", "completeness", "exact_match", "exact_match_standard", "citation_accuracy", "faithfulness",
         "context_recall", "context_recall_standard", "latency_s", "cost_usd")
LABEL = {
    "similarity": "Similarity (0–10)", "coverage": "Coverage", "coverage_standard": "Standard-only coverage",
    "coverage_std_supp": "Standard + Supporting coverage", "exact_match_standard": "Standard-only exact match",
    "wins": "Wins (gap: share of answers)", "exact_match": "Exact match", "faithfulness": "Faithfulness",
    "citation_accuracy": "Citation accuracy", "context_recall": "Context recall", "context_recall_standard": "Standard-only context recall",
    "completeness": "Completeness", "latency_s": "Latency (s, lower is better)", "cost_usd": "Cost per query (lower is better)",
    "std_similarity": "Standard-only similarity (0–10)", "contradictions": "Contradictions per answer (lower is better)",
    "no_contradiction": "Answers with no contradiction",
}
CARD_LABEL = {"std_similarity": "Standard-only similarity", "contradictions": "Contradictions per answer",
              "no_contradiction": "Answers with no contradiction"}
JUDGED = ("similarity", "coverage", "coverage_standard", "coverage_std_supp")  # from the pair's own grading
EXTRAS = ("std_similarity", "contradictions", "no_contradiction")  # read from what the run stored besides its summary
COUNTED = ("contradictions", "no_contradiction")  # counts per answer: no wiki-minus-RAG interval


def _g(obj, *keys):
    for k in keys:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def _cell(ok: bool, text: str, value=None, reason: str = "") -> dict:
    return {"ok": ok, "text": text, "value": value, "reason": reason}


def _std_sim(d: dict, pair: str):
    return _g(d, "extras", "std_similarity") if pair == "rag" else _g(d, "extras", "pairs", pair, "std_similarity")


def fmt_metric(k: str, v: float) -> str:
    return f"${v:.4f}" if k == "cost_usd" else f"{v:.1f} s" if k == "latency_s" else f"{v:.1f}%"


def fmt_gap(k: str, v: float) -> str:
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


def extra(d: dict, sys: str, k: str, pair: str = "rag") -> dict:
    """One system's figure on an extra measure in one pair (the wiki's in another RAG column's pair is from that pair's
    grading), or "not measured" with the reason."""
    no = lambda why: _cell(False, "not measured", None, why)
    if k == "std_similarity":
        v = _g(_std_sim(d, pair), "by_system", sys)
        if not v or v.get("mean") is None:
            failed = _g(d, "extras", "std_similarity_failed")
            return no(f"failed: {failed}" if failed else "Quick mode: standard-only similarity runs only in Full mode"
                      if _g(d, "config", "mode") == "quick" else "standard-only similarity was not run on this run")
        return _cell(True, f"{v['mean']}/10", v["mean"], f"{v.get('n_topics')} topic(s)")
    c = _g(d, "extras", "pairs", pair, "contradictions", "wiki") if sys == "wiki" and pair != "rag" else _g(d, "extras", "contradictions", sys)
    if not c:
        return no("no answer in this run was checked for contradictions")
    if k == "contradictions":
        return _cell(True, f"{c['mean']:.2f}", c["mean"], f"{c['n']} answer(s)")
    return _cell(True, f"{c['none']} of {c['n']} ({c['none_pct']:.0f}%)", c["none_pct"], f"{c['n']} answer(s)")


def score(d: dict, sys: str, k: str, pair: str = "rag") -> dict:
    """One system's score on one test in one pair, or "Not run yet" with the reason. The judged tests and wins come from
    the pair's own grading (the wiki is graded once per RAG column); the other tests are per answer."""
    if k in EXTRAS:
        return extra(d, sys, k, pair)
    no = lambda why: _cell(False, "Not run yet", None, why)
    s = d.get("summary")
    if not s:
        return no("the run has not finished")
    other = _g(s, "pairs", pair) if pair != "rag" else None
    if k == "wins":
        n = ((other or {}).get("wins_by_run") if other else s.get("wins_by_run") or {}) or {}
        return _cell(True, str(n.get(sys) or 0), n.get(sys) or 0, "answers won (both grading orders agreeing)")
    if k in JUDGED:
        v = _g(other, "wiki", k) if sys == "wiki" and other else _g(s, "by_system", sys, k)
        if v and v.get("mean") is not None:
            return _cell(True, f"{v['mean']}/10" if k == "similarity" else f"{v['mean']}%", v["mean"], f"{v.get('n')} topic(s)")
        if k == "coverage_std_supp" and _g(d, "config", "sources") == "standard":
            return no("this run used Standard only (Part A), so Supporting points were not in play")
        return no("no graded answers")
    m = _g(d, "metrics", "by_system", sys, k)
    if not m:
        return no("not measured in this run")
    if m.get("status") != "measured" or m.get("mean") is None:
        return no(m.get("reason") or "not measured")
    return _cell(True, fmt_metric(k, m["mean"]), m["mean"],
                 f"{m.get('n')} answer(s)" + ("; some not measured" if m.get("not_measured_in") else ""))


def _gap(d: dict, pair: str, k: str):
    if k == "std_similarity":
        return _g(_std_sim(d, pair), "gap")
    if k in COUNTED:
        return None
    return _g(d, "summary", "gaps", k) if pair == "rag" else _g(d, "summary", "pairs", pair, "gaps", k)


def row(d: dict, pair: str, k: str) -> dict:
    """One test in one pair: both systems' scores, and the gap where both have a score and the run has one (else the
    reason it is not shown)."""
    r, w, e = score(d, pair, k, pair), score(d, "wiki", k, pair), _gap(d, pair, k)
    gap = None
    if e and r["ok"] and w["ok"]:
        ci = e.get("ci")
        gap = {"text": fmt_gap(k, e["diff"]), "value": e["diff"],
               "ci_text": f"{fmt_gap(k, ci[0])} to {fmt_gap(k, ci[1])}" if ci else "", "ci": ci or None,
               "verdict": e.get("verdict"), "leader": e.get("leader") or ""}
    note = "" if gap else (r["reason"] if not r["ok"] else w["reason"] if not w["ok"] else "no interval: a count per answer" if k in COUNTED else "")
    return {"key": k, "label": LABEL[k], "rag": r, "wiki": w, "gap": gap, "note": note}


def build(d: dict) -> dict:
    """The run's scorecards (one per RAG column, each against the wiki) and its system cards' extra figures."""
    systems = _g(d, "config", "systems_compared") or []
    pairs = [s for s in systems if s != "wiki"]
    cards = {sys: {"std_similarity": extra(d, sys, "std_similarity", "rag_q" if sys == "rag_q" else "rag"),
                   **{k: extra(d, sys, k) for k in COUNTED}} for sys in systems}
    return {"pairs": [{"pair": p, "rows": [row(d, p, k) for k in ORDER]} for p in pairs],
            "cards": cards, "card_label": CARD_LABEL}
