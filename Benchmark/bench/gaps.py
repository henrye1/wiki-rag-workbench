"""RAG-vs-wiki gaps with 95% confidence intervals.

For each test, every topic gives one wiki-minus-RAG difference (each system's mean over the topic's repetitions). The
interval comes from resampling the topics with replacement (10,000 times, fixed seed): when it crosses zero the run shows
no clear difference rather than a leader.
"""
import random
import statistics

LOWER_IS_BETTER = {"latency_s", "cost_usd"}
JUDGED = ("similarity", "coverage", "coverage_standard", "coverage_std_supp")
RESAMPLES = 10_000


def _topic_values(rec: dict) -> dict[str, dict[str, float]]:
    """metric -> system -> this topic's mean over its repetitions (graded runs for the judge's tests; all answers otherwise)."""
    out: dict[str, dict[str, list]] = {}
    for run in rec.get("runs", {}).values():
        sys_ = run.get("systems") or run.get("answers") or {}
        for name, a in sys_.items():
            if run.get("judgement"):
                for k in JUDGED:
                    if a.get(k) is not None:
                        out.setdefault(k, {}).setdefault(name, []).append(a[k])
            for k, m in (a.get("metrics") or {}).items():
                if m.get("status") == "measured" and m.get("value") is not None:
                    out.setdefault(k, {}).setdefault(name, []).append(m["value"])
        if run.get("judgement") and run.get("winner"):
            score = {"wiki": 1.0, "rag": -1.0}.get(run["winner"], 0.0)  # +1 wiki win, -1 RAG win, 0 tie
            out.setdefault("wins", {}).setdefault("wiki", []).append(score)
            out["wins"].setdefault("rag", []).append(0.0)
    return {k: {n: statistics.mean(v) for n, v in by.items()} for k, by in out.items()}


def gaps(data: dict, seed: int = 42) -> dict:
    per_topic: dict[str, list[float]] = {}
    for rec in data.get("topics", {}).values():
        for k, by in _topic_values(rec).items():
            if "rag" in by and "wiki" in by:
                per_topic.setdefault(k, []).append(by["wiki"] - by["rag"])
    out = {}
    for k, diffs in per_topic.items():
        lower = k in LOWER_IS_BETTER
        entry = {"diff": round(statistics.mean(diffs), 4), "n_topics": len(diffs), "better": "lower" if lower else "higher"}
        if len(diffs) < 2:
            out[k] = {**entry, "ci": None, "leader": None, "verdict": "too few topics for an interval"}
            continue
        rng = random.Random(f"{seed}-{k}")
        means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(RESAMPLES))
        lo, hi = means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]
        if lo > 0:
            leader = "rag" if lower else "wiki"
        elif hi < 0:
            leader = "wiki" if lower else "rag"
        else:
            leader = None
        out[k] = {**entry, "ci": [round(lo, 4), round(hi, 4)], "leader": leader,
                  "verdict": f"{'Wiki' if leader == 'wiki' else 'RAG'} better" if leader else "no clear difference"}
    return out
