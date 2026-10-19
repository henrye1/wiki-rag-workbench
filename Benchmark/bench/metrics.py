"""Per-answer tests that need no judge: latency and cost per query (the recorded tokens of the AI calls behind the answer
x the price list). The run summary also lists the judge-based tests, as not measured until they are run.

A test that cannot be worked out is stored as not measured, with the reason; never as 0 or an estimate.

  python -m bench.metrics backfill <run-id>|all   # add these tests to saved runs (no question is asked again)
"""
import json
import pathlib
import statistics
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import get_settings

VERSION = "kept-1"
PRICES = json.loads((pathlib.Path(__file__).parent / "prices.json").read_text())
CHEAP = ("latency_s", "cost_usd")
CONTEXT = ("faithfulness", "context_recall")  # Full mode: one Claude Sonnet 5.5 call per answer, reading what the answer read
ANSWER_CHECKS = ("completeness", "exact_match", "citation_accuracy")


def not_measured(reason: str) -> dict:
    return {"value": None, "status": "not measured", "reason": reason}


def measured(value) -> dict:
    return {"value": value, "status": "measured"}


def cost_usd(usage: list[dict] | None) -> tuple[float | None, str]:
    """Generation tokens x price. The services' embedding calls report no token count, so their (very small) cost is left out."""
    if usage is None:
        return None, "the AI calls behind this answer were not recorded (run made before tokens were recorded)"
    total, missing = 0.0, []
    for u in usage:
        if u.get("step") == "embed":
            continue
        price = PRICES.get(u.get("model") or "")
        if not price or u.get("input_tokens") is None:
            missing.append(u.get("model") or "?")
            continue
        out = (u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0)
        total += u["input_tokens"] / 1e6 * price["input"] + out / 1e6 * price["output"]
    if missing:
        return None, f"no price or token count for {', '.join(sorted(set(missing)))}"
    return round(total, 5), ""


def answer_metrics(ans: dict) -> dict:
    out = {"latency_s": measured(ans["latency_s"]) if ans.get("latency_s") is not None else not_measured("not recorded")}
    c, why = cost_usd(ans.get("usage"))
    out["cost_usd"] = measured(c) if c is not None else not_measured(why)
    return out


def _answers(data: dict):
    """(topic, rep, system, answer dict) for every saved answer, graded or not."""
    for t in data.get("topics", {}).values():
        for rid, run in t.get("runs", {}).items():
            src = run.get("systems") or run.get("answers") or {}
            for sysname, ans in src.items():
                yield t, rid, sysname, ans


def summarise(data: dict, mode: str | None) -> dict:
    """Per system: mean, sd and n of each per-answer test; not measured (with the reasons) when none was."""
    by: dict[str, dict] = {}
    for t, rid, sysname, ans in _answers(data):
        for k, m in (ans.get("metrics") or {}).items():
            slot = by.setdefault(sysname, {}).setdefault(k, {"values": [], "reasons": set()})
            if m["status"] == "measured" and m["value"] is not None:
                slot["values"].append(m["value"])
            else:
                slot["reasons"].add(m.get("reason") or "not measured")
    out = {}
    for sysname, ms in by.items():
        out[sysname] = {}
        for k, slot in ms.items():
            xs, digits = slot["values"], 4 if k == "cost_usd" else 2
            if xs:
                out[sysname][k] = {"mean": round(statistics.mean(xs), digits), "sd": round(statistics.stdev(xs), digits) if len(xs) > 1 else 0.0,
                                   "n": len(xs), "status": "measured", **({"not_measured_in": len(slot["reasons"])} if slot["reasons"] else {})}
            else:
                out[sysname][k] = {"mean": None, "n": 0, **not_measured("; ".join(sorted(slot["reasons"])))}
        for k in CONTEXT:
            out[sysname].setdefault(k, not_measured("Quick mode: faithfulness and context recall run only in Full mode" if mode != "full"
                                                    else "faithfulness and context recall are not available yet"))
        for k in ANSWER_CHECKS:
            out[sysname].setdefault(k, not_measured("the answer checks have not been run on this run's answers"))
    return {"version": VERSION, "mode": mode or "quick", "by_system": out}


async def compute(data: dict, mode: str | None, only_missing: bool = True) -> int:
    """Work out the per-answer tests for every saved answer (answers already done are left alone)."""
    n = 0
    for t, rid, sysname, ans in list(_answers(data)):
        if only_missing and all(k in (ans.get("metrics") or {}) for k in CHEAP):
            continue
        ans["metrics"] = {**(ans.get("metrics") or {}), **answer_metrics(ans)}
        n += 1
    data["metrics"] = summarise(data, mode)
    return n


def backfill(run_ids: list[str]) -> None:
    import asyncio
    conn = psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row)
    if run_ids == ["all"]:
        run_ids = [r["id"] for r in conn.execute("select id from bench.runs where results is not null order by created_at")]
    for rid in run_ids:
        row = conn.execute("select results, mode from bench.runs where id = %s", (rid,)).fetchone()
        if not row or not row["results"]:
            print(f"{rid}: no results")
            continue
        data = row["results"]
        n = asyncio.run(compute(data, row["mode"]))
        from .run import aggregate  # the summary, with the gaps' confidence intervals, from what the run already holds
        aggregate(data)
        conn.execute("update bench.runs set results = %s where id = %s", (Jsonb(data), rid))
        s = data["metrics"]["by_system"]
        print(f"{rid}: {n} answers | " + " | ".join(
            f"{k}: " + ", ".join(f"{sysname} {v[k].get('mean') if v[k].get('mean') is not None else 'not measured'}" for sysname, v in s.items())
            for k in CHEAP))


if __name__ == "__main__":
    if sys.argv[1:2] == ["backfill"] and len(sys.argv) > 2:
        backfill(sys.argv[2:])
    else:
        sys.exit(__doc__)
