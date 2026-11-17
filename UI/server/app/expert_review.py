"""Expert review of a benchmark run's judge, read only: Excel files for reviewers to grade the same key points the judge
graded, blind, and the results once they send them back.

A run's judge graded each pair of answers twice, once in each order (A/B, then swapped), and kept each order's grades,
notes and preferred answer. A reviewer file shows one of those two readings exactly as the judge saw it, picked at random
per topic, so "A" and "B" in the judge's notes are the answers the reviewer sees as A and B. Which system wrote which
answer is only in the KEY file, never in a reviewer file.

Every choice comes from one seed (shown in the app and kept in the KEY): how the topics are shared out between the
reviewers, and which of the judge's two readings each topic shows. The same run, settings and seed give the same files.
"""
import datetime as dt
import io
import random
import re
import statistics
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .run_export import _plain

# The topics are shared out evenly within each of these groups of topic numbers (the user's split, so each reviewer gets
# topics from both halves of the question set); topics outside them form one more group.
GROUPS = ((1, 14), (15, 26))
# A key point's weight in coverage: a copy of Benchmark/bench/run.py WEIGHT, which this server cannot import (the
# benchmark runs in its own environment); change both together
WEIGHT = {"full": 1.0, "partial": 0.5, "missing": 0.0}
GRADES = ("full", "partial", "missing")
AGREE = ("yes", "partly", "no")
PREFER = ("A", "B", "tie")
MAX_REVIEWERS = 4
CELL_MAX = 32767  # Excel's limit for one cell
JUDGE_FILL = PatternFill("solid", fgColor="EDEDED")
YOURS_FILL = PatternFill("solid", fgColor="FFF4CC")
HEAD_FONT = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")


class ReviewError(ValueError):
    """The run cannot give these files (a choice it does not have, or files that do not belong together)."""


# ---------- what a run offers, and how its topics are shared out ----------
def _topics(data: dict) -> list[dict]:
    return sorted((data.get("topics") or {}).values(), key=lambda t: t.get("number") or 0)


def _orders(run: dict, pair: str) -> dict:
    """A pair's two gradings by order ("1", "2"): the pair with RAG per topic is the run's own; another pair's is under
    pairs."""
    if pair == "rag":
        return run.get("orders") or {}
    return ((run.get("pairs") or {}).get(pair) or {}).get("orders") or {}


def _usable(t: dict, pair: str, rep: str) -> bool:
    o = _orders((t.get("runs") or {}).get(rep) or {}, pair)
    return all(k in o and (o[k].get("systems") or {}).get("wiki") and (o[k].get("systems") or {}).get(pair) for k in ("1", "2"))


def options(data: dict) -> dict:
    """The pairs (RAG column against the wiki) and repetitions this run can give, best first."""
    systems = (data.get("config") or {}).get("systems_compared") or []
    pairs = [p for p in ("rag_q", "rag") if p in systems]
    reps = sorted({k for t in _topics(data) for k in (t.get("runs") or {})}, key=lambda k: int(k) if k.isdigit() else 0)
    usable = {p: [r for r in reps if any(_usable(t, p, r) for t in _topics(data))] for p in pairs}
    return {"pairs": [p for p in pairs if usable[p]], "repetitions": {p: [int(r) for r in v] for p, v in usable.items() if v}}


def _groups(numbers: list[int]) -> list[list[int]]:
    out = [[n for n in numbers if lo <= n <= hi] for lo, hi in GROUPS]
    rest = [n for n in numbers if not any(lo <= n <= hi for lo, hi in GROUPS)]
    return [g for g in out + [rest] if g]


def split(numbers: list[int], reviewers: int, seed: int) -> list[list[int]]:
    """Each topic to one reviewer: within each group the topics are shuffled and dealt in turn, the deal carrying on from
    one group to the next, so the reviewers' totals differ by at most one and each group is shared as evenly."""
    rng = random.Random(f"{seed}-split")
    out: list[list[int]] = [[] for _ in range(reviewers)]
    turn = 0
    for g in _groups(sorted(numbers)):
        g = g[:]
        rng.shuffle(g)
        for n in g:
            out[turn % reviewers].append(n)
            turn += 1
    return [sorted(x) for x in out]


def _reading(seed: int, number: int) -> str:
    """Which of the judge's two readings (orders) a topic shows: the seed's choice, so A/B is random per topic."""
    return random.Random(f"{seed}-order-{number}").choice(("1", "2"))


def _check(data: dict, pair: str, rep: int, reviewers: int):
    opt = options(data)
    if pair not in opt["pairs"]:
        raise ReviewError(f"This run has no judged pair '{pair}'")
    if rep not in opt["repetitions"][pair]:
        raise ReviewError(f"This run has no repetition {rep} for that pair")
    if not 1 <= reviewers <= MAX_REVIEWERS:
        raise ReviewError(f"Reviewers: 1 to {MAX_REVIEWERS}")


def plan(data: dict, pair: str, rep: int, reviewers: int, seed: int) -> dict:
    """The topic split the files will use, and the topics left out because that repetition was not judged for them."""
    _check(data, pair, rep, reviewers)
    nums = [t["number"] for t in _topics(data) if _usable(t, pair, str(rep))]
    left_out = [t["number"] for t in _topics(data) if t["number"] not in nums]
    groups = _groups(nums)
    return {"seed": seed, "pair": pair, "repetition": rep, "options": options(data),
            "groups": [[g[0], g[-1]] for g in groups], "left_out": left_out,
            "reviewers": [{"n": i + 1, "topics": ts, "by_group": [sum(1 for n in ts if n in g) for g in groups]}
                          for i, ts in enumerate(split(nums, reviewers, seed))]}


# ---------- writing the files ----------
def _text(v) -> str | int | float | None:
    if v is None or isinstance(v, (int, float)):
        return v
    s = ILLEGAL_CHARACTERS_RE.sub("", str(v))
    if len(s) > CELL_MAX:
        keep = CELL_MAX - 200
        s = s[:keep] + f"\n… [cut here: {len(s) - keep:,} more characters; the full text is in the run's side-by-side review]"
    return s


def _put(ws, row: int, values: list, fills: dict | None = None):
    for c, v in enumerate(values, 1):
        cell = ws.cell(row=row, column=c, value=_text(v))
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"  # text, never a formula
        cell.alignment = WRAP
        if fills and c in fills:
            cell.fill = fills[c]


def _table(ws, header: list[str], widths: list[int], rows: list[list], fills: dict | None = None,
           lists: dict[int, tuple] | None = None):
    """A sheet as a table: bold frozen header, filters, wrapped text, and a drop-down on the given columns."""
    _put(ws, 1, header)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
        ws.cell(row=1, column=c).font = HEAD_FONT
        if fills and c in fills:
            ws.cell(row=1, column=c).fill = fills[c]
    for i, r in enumerate(rows, 2):
        _put(ws, i, r, fills)
    ws.freeze_panes = "A2"
    last = max(len(rows) + 1, 2)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{last}"
    for c, choices in (lists or {}).items():
        dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True,
                            showErrorMessage=True, errorTitle="Pick from the list", error="Choose one of: " + ", ".join(choices))
        col = get_column_letter(c)
        dv.add(f"{col}2:{col}{last}")
        ws.add_data_validation(dv)


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _letter(label: dict, system: str) -> str:
    return "tie" if system == "tie" else next((k for k, v in label.items() if v == system), "")


def _cover(points: list[dict], grades: dict) -> float | None:
    ids = [p["id"] for p in points]
    if not ids or any(grades.get(i) not in WEIGHT for i in ids):
        return None
    return round(100 * sum(WEIGHT[grades[i]] for i in ids) / len(ids), 1)


INSTRUCTIONS = [
    ("What this is", "You are checking an automated judge. For each topic, two answers to the same question (Answer A and "
     "Answer B) were graded against a reference text, one key point at a time. The judge's grades are in the grey columns. "
     "Please grade the same key points yourself in the yellow columns."),
    ("Work on your own", "Grade independently: do not discuss the answers or your grades with other reviewers, and do not "
     "try to find out where an answer came from. Answer A and Answer B are in a random order for each topic; the order "
     "means nothing."),
    ("1. Read", "On the Answers sheet, read the topic's question, its reference text, then Answer A and Answer B."),
    ("2. Grade the key points", "On the Key points sheet, give each key point a grade for Answer A and for Answer B (Your "
     "grade: A, Your grade: B), judged against the reference text. Grade first, then compare with the judge."),
    ("3. Agree with the judge?", "yes: you agree with both of the judge's grades. partly: you agree with one, or with its "
     "grades but not its note. no: you disagree with both. Say why in Comment when it is not yes."),
    ("4. Which answer is closer?", "On the Answers sheet, pick the answer closer to the reference text overall (A, B or "
     "tie) in Your preference, and add a comment if you like."),
    ("full", "The answer states the point with its substance and conditions intact (the wording may differ)."),
    ("partial", "The answer touches the point but loses a condition, a nuance or part of it."),
    ("missing", "The point is absent, or the answer says its material does not address it."),
    ("Kind", "Each key point's kind (as the rubric records it) is shown for information; grade every kind the same way."),
    ("Please", "Fill in only the yellow columns, using the drop-downs; leave the grey columns, the rows and the sheet "
     "names as they are, and send the file back under its own name."),
]


def build(data: dict, run_id: str, pair: str, rep: int, reviewers: int, seed: int, label: dict) -> tuple[dict[str, bytes], str]:
    """The files by name (one per reviewer, then the KEY), and all the text written into the reviewer files (to check that
    nothing that must stay out of them is in them)."""
    p = plan(data, pair, rep, reviewers, seed)
    topics = {t["number"]: t for t in _topics(data)}
    made = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    name = {"wiki": label.get("wiki", "Wiki"), pair: label.get(pair, pair)}
    files, written = {}, []
    key_topics, key_points = [], []
    for rv in p["reviewers"]:
        wb = Workbook()
        ins = wb.active
        ins.title = "Instructions"
        review_id = f"Run {run_id} · Reviewer {rv['n']} of {reviewers} · repetition {rep}"
        _put(ins, 1, ["Expert review", review_id])
        _put(ins, 2, ["Your topics", ", ".join(map(str, rv["topics"])) or "none"])
        for i, (k, v) in enumerate(INSTRUCTIONS, 4):
            _put(ins, i, [k, v])
            ins.cell(row=i, column=1).font = HEAD_FONT
        ins.cell(row=1, column=1).font = Font(bold=True, size=14)
        ins.cell(row=2, column=1).font = HEAD_FONT
        ins.column_dimensions["A"].width = 26
        ins.column_dimensions["B"].width = 110
        kp_rows, ans_rows = [], []
        for n in rv["topics"]:
            t = topics[n]
            run = t["runs"][str(rep)]
            k = _reading(seed, n)
            o = _orders(run, pair)[k]
            lab = o["blind_labels"]  # {"A": system, "B": system}, as the judge saw them in this reading
            g = {s: (o["systems"].get(s) or {}).get("grades") or {} for s in lab.values()}
            notes = o.get("point_notes") or {}
            for kp in t.get("key_points") or []:
                kp_rows.append([n, t.get("code"), t.get("title"), kp.get("id"), kp.get("kind"), kp.get("point"),
                                g[lab["A"]].get(kp["id"], ""), g[lab["B"]].get(kp["id"], ""), notes.get(kp["id"], ""),
                                None, None, None, None])
                key_points.append([n, kp.get("id"), kp.get("kind"), g["wiki"].get(kp["id"], ""), g[pair].get(kp["id"], "")])
            ans_rows.append([n, t.get("code"), t.get("title"), t.get("question"), t.get("reference"),
                             _plain(((run.get("systems") or {}).get(lab["A"]) or {}).get("answer")),
                             _plain(((run.get("systems") or {}).get(lab["B"]) or {}).get("answer")),
                             _letter(lab, o.get("winner") or ""), None, None])
            both = _both(run, pair)
            key_topics.append([rv["n"], n, t.get("code"), t.get("title"), name[lab["A"]], name[lab["B"]], int(k),
                               name.get(o.get("winner"), "tie"),
                               _cover(t.get("key_points") or [], g["wiki"]), _cover(t.get("key_points") or [], g[pair]),
                               both["wiki"], both[pair]])
        J, Y = JUDGE_FILL, YOURS_FILL
        _table(wb.create_sheet("Key points"),
               ["Topic", "Code", "Title", "Key point", "Kind", "Point", "Judge: A", "Judge: B", "Judge's note",
                "Your grade: A", "Your grade: B", "Agree with judge", "Comment"],
               [7, 8, 24, 9, 11, 50, 10, 10, 50, 13, 13, 14, 40], kp_rows,
               {7: J, 8: J, 9: J, 10: Y, 11: Y, 12: Y, 13: Y}, {10: GRADES, 11: GRADES, 12: AGREE})
        _table(wb.create_sheet("Answers"),
               ["Topic", "Code", "Title", "Question", "Reference text", "Answer A", "Answer B", "Judge's preference",
                "Your preference", "Comment"],
               [7, 8, 24, 40, 60, 70, 70, 12, 12, 40], ans_rows, {8: J, 9: Y, 10: Y}, {9: PREFER})
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                written.extend(str(c.value) for c in row if c.value is not None)
        files[f"Expert_Review_{run_id}_Reviewer{rv['n']}.xlsx"] = _save(wb)
    files[f"Expert_Review_{run_id}_KEY.xlsx"] = _key(run_id, p, made, name, key_topics, key_points)
    return files, "\n".join(written)


def _both(run: dict, pair: str) -> dict:
    """Each system's coverage as the run scored it in this pair (the mean of the judge's two readings)."""
    wiki = (run.get("systems") or {}).get("wiki") if pair == "rag" else ((run.get("pairs") or {}).get(pair) or {}).get("wiki")
    return {"wiki": (wiki or {}).get("coverage"), pair: ((run.get("systems") or {}).get(pair) or {}).get("coverage")}


def _key(run_id: str, p: dict, made: str, name: dict, topics: list, points: list) -> bytes:
    wb = Workbook()
    s = wb.active
    s.title = "Settings"
    rows = [["KEY: keep this file yourself; never send it to a reviewer", ""], ["Run", run_id],
            ["Wiki", name["wiki"]], ["Wiki against", name[p["pair"]]], ["Pair", p["pair"]], ["Repetition", p["repetition"]],
            ["Reviewers", len(p["reviewers"])], ["Seed", p["seed"]], ["Made", made],
            ["Topics left out", ", ".join(map(str, p["left_out"])) or "none"]]
    for i, r in enumerate(rows, 1):
        _put(s, i, r)
        s.cell(row=i, column=1).font = HEAD_FONT
    s.cell(row=1, column=1).font = Font(bold=True, size=14, color="C00000")
    s.column_dimensions["A"].width = 22
    s.column_dimensions["B"].width = 40
    _table(wb.create_sheet("Topics"),
           ["Reviewer", "Topic", "Code", "Title", "Answer A is", "Answer B is", "Judge's reading shown",
            "Judge's preference (this reading)", "Judge coverage: Wiki (this reading)", f"Judge coverage: {name[p['pair']]} (this reading)",
            "Judge coverage: Wiki (run, both readings)", f"Judge coverage: {name[p['pair']]} (run, both readings)"],
           [10, 7, 8, 30, 18, 18, 12, 18, 14, 14, 14, 14], topics)
    _table(wb.create_sheet("Key points"),
           ["Topic", "Key point", "Kind", "Judge: Wiki", f"Judge: {name[p['pair']]}"], [7, 10, 12, 12, 18], points)
    return _save(wb)


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


# ---------- reading the returned files ----------
def _sheet(wb, title: str) -> list[dict]:
    if title not in wb.sheetnames:
        raise ReviewError(f"Sheet '{title}' is missing")
    rows = list(wb[title].iter_rows(values_only=True))
    head = [str(h).strip() if h is not None else "" for h in rows[0]] if rows else []
    return [dict(zip(head, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]


def _norm(v, allowed: tuple) -> str | None:
    s = str(v).strip() if v is not None else ""
    for a in allowed:
        if s.lower() == a.lower():
            return a
    return None


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 1) if xs else None


def _ci(xs: list[float]) -> str:
    """An approximate 95% interval for a mean (normal approximation; rough for few topics)."""
    if len(xs) < 2:
        return "—"
    m, h = statistics.fmean(xs), 1.96 * statistics.stdev(xs) / len(xs) ** 0.5
    return f"{round(m - h, 1) + 0.0:+.1f} to {round(m + h, 1) + 0.0:+.1f}"  # + 0.0: no "-0.0"


def results(key: bytes, returned: list[bytes]) -> bytes:
    """The results workbook: how often the reviewers agree with the judge, for the wiki's answers and the RAG answers
    separately, their preferences, and the wiki − RAG coverage gap from the reviewers' grades beside the judge's."""
    kb = load_workbook(io.BytesIO(key), read_only=True)
    if "Settings" not in kb.sheetnames:
        raise ReviewError("The first file is not a KEY file (it has no Settings sheet)")
    settings = {str(r[0]): r[1] for r in kb["Settings"].iter_rows(values_only=True) if r and r[0]}
    run_id, pair = str(settings["Run"]), str(settings["Pair"])
    rag_name, wiki_name = str(settings["Wiki against"]), str(settings["Wiki"])
    topics = {int(r["Topic"]): r for r in _sheet(kb, "Topics")}
    judge = {(int(r["Topic"]), str(r["Key point"])): r for r in _sheet(kb, "Key points")}
    grades: dict[tuple, dict] = {}  # (topic, key point) -> reviewer's grades by system, agree, comment
    prefs: dict[int, dict] = {}
    read = []
    for blob in returned:
        wb = load_workbook(io.BytesIO(blob), read_only=True)
        ident = str(next(wb["Instructions"].iter_rows(min_row=1, max_row=1, values_only=True))[1] or "")
        m = re.match(r"Run (\S+) · Reviewer (\d+) of", ident)
        if not m or m.group(1) != run_id:
            raise ReviewError(f"A returned file is not from run {run_id}: '{ident}'")
        rv = int(m.group(2))
        read.append(rv)
        for r in _sheet(wb, "Key points"):
            n, kp = int(r["Topic"]), str(r["Key point"])
            t = topics.get(n)
            if not t or int(t["Reviewer"]) != rv:
                raise ReviewError(f"Reviewer {rv}'s file has topic {n}, which the KEY gives to another reviewer")
            sys_of = {"A": t["Answer A is"], "B": t["Answer B is"]}
            grades[(n, kp)] = {"reviewer": rv, "kind": judge[(n, kp)]["Kind"],
                               sys_of["A"]: _norm(r.get("Your grade: A"), GRADES), sys_of["B"]: _norm(r.get("Your grade: B"), GRADES),
                               "agree": _norm(r.get("Agree with judge"), AGREE), "comment": r.get("Comment") or ""}
        for r in _sheet(wb, "Answers"):
            n = int(r["Topic"])
            t = topics.get(n)
            if not t or int(t["Reviewer"]) != rv:
                raise ReviewError(f"Reviewer {rv}'s file has topic {n}, which the KEY gives to another reviewer")
            sys_of = {"A": t["Answer A is"], "B": t["Answer B is"], "tie": "tie"}
            mine = _norm(r.get("Your preference"), PREFER)
            prefs[n] = {"reviewer": rv, "pref": sys_of.get(mine) if mine else None, "comment": r.get("Comment") or ""}
    if len(set(read)) != len(read):
        raise ReviewError("The same reviewer's file was given twice")
    systems = (wiki_name, rag_name)
    jcol = {wiki_name: "Judge: Wiki", rag_name: f"Judge: {rag_name}"}
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    by_kp, by_topic = [], []
    stats = {s: {"n": 0, "same": 0, "higher": 0, "lower": 0, "judge": [], "mine": []} for s in systems}
    per_rv: dict[tuple, dict] = {}
    agree = {a: 0 for a in AGREE}
    for (n, kp), g in sorted(grades.items()):
        j = judge[(n, kp)]
        row = [g["reviewer"], n, kp, g["kind"]]
        for s in systems:
            jg, mg = _norm(j[jcol[s]], GRADES), g.get(s)
            row += [jg, mg]
            if jg and mg:
                st, rs = stats[s], per_rv.setdefault((g["reviewer"], s), {"n": 0, "same": 0})
                st["n"] += 1
                rs["n"] += 1
                st["judge"].append(WEIGHT[jg])
                st["mine"].append(WEIGHT[mg])
                if jg == mg:
                    st["same"] += 1
                    rs["same"] += 1
                elif WEIGHT[mg] > WEIGHT[jg]:
                    st["higher"] += 1
                else:
                    st["lower"] += 1
        if g["agree"]:
            agree[g["agree"]] += 1
        by_kp.append(row + [g["agree"], g["comment"]])
    gaps = {"this": [], "both": [], "mine": []}
    pref_same, pref_n = 0, 0
    for n, t in sorted(topics.items()):
        pts = [kp for (tn, kp) in grades if tn == n]
        mine = {s: [grades[(n, kp)].get(s) for kp in pts] for s in systems}
        cov = {s: round(100 * sum(WEIGHT[x] for x in v) / len(v), 1) if v and all(v) else None for s, v in mine.items()}
        jt = (t["Judge coverage: Wiki (this reading)"], t[f"Judge coverage: {rag_name} (this reading)"])
        jb = (t["Judge coverage: Wiki (run, both readings)"], t[f"Judge coverage: {rag_name} (run, both readings)"])
        complete = None not in cov.values() and None not in jt
        if complete:
            gaps["this"].append(jt[0] - jt[1])
            gaps["mine"].append(cov[wiki_name] - cov[rag_name])
            if None not in jb:
                gaps["both"].append(jb[0] - jb[1])
        pr = prefs.get(n) or {}
        jp = t["Judge's preference (this reading)"]
        if pr.get("pref"):
            pref_n += 1
            pref_same += pr["pref"] == jp
        by_topic.append([t["Reviewer"], n, t["Code"], t["Title"], jt[0], cov[wiki_name], jt[1], cov[rag_name],
                         round(jt[0] - jt[1], 1) if complete else None,
                         round(cov[wiki_name] - cov[rag_name], 1) if complete else None, jp, pr.get("pref"),
                         "yes" if complete else "not fully graded", pr.get("comment", "")])

    def pct(a, b):
        return f"{100 * a / b:.0f}%" if b else "—"

    lines = [["Expert review results", f"Run {run_id} · Wiki against {rag_name} · repetition {settings['Repetition']} · "
              f"seed {settings['Seed']}"],
             ["Files read", f"reviewers {', '.join(map(str, sorted(read)))} of {settings['Reviewers']}"],
             ["Key points graded", f"{len(grades)} of {len(judge)} rows in the KEY"], [],
             ["Agreement with the judge", "Key points compared", "Same grade", "Reviewer higher", "Reviewer lower",
              "Judge coverage", "Reviewer coverage"]]
    for s in systems:
        st = stats[s]
        lines.append([s, st["n"], pct(st["same"], st["n"]), pct(st["higher"], st["n"]), pct(st["lower"], st["n"]),
                      f"{100 * statistics.fmean(st['judge']):.1f}%" if st["judge"] else "—",
                      f"{100 * statistics.fmean(st['mine']):.1f}%" if st["mine"] else "—"])
    lines += [["Read it as", "If the judge favours one system, the reviewers grade that system lower than the judge more "
               "often (Reviewer lower) than they do the other."], [],
              ["Agree with judge (column)", "yes", "partly", "no"], ["", agree["yes"], agree["partly"], agree["no"]], [],
              ["Preferred answer", "Topics compared", "Reviewer picks the judge's answer"],
              ["", pref_n, pct(pref_same, pref_n)], [],
              ["Wiki − RAG coverage gap", "Topics", "Mean gap (points)", "Approx. 95% interval"],
              ["Judge, the reading the reviewers saw", len(gaps["this"]), _mean(gaps["this"]), _ci(gaps["this"])],
              ["Judge, as the run scored it (both readings)", len(gaps["both"]), _mean(gaps["both"]), _ci(gaps["both"])],
              ["Reviewers", len(gaps["mine"]), _mean(gaps["mine"]), _ci(gaps["mine"])],
              ["Reviewers − judge (same topics)", len(gaps["mine"]),
               _mean([a - b for a, b in zip(gaps["mine"], gaps["this"])]),
               _ci([a - b for a, b in zip(gaps["mine"], gaps["this"])])],
              ["Read it as", "A positive 'Reviewers − judge' means the reviewers see the wiki further ahead than the judge "
               "did; negative, less far ahead. Only topics with every key point graded for both answers count."]]
    for i, r in enumerate(lines, 1):
        _put(summary, i, r)
        summary.cell(row=i, column=1).font = HEAD_FONT
    summary.cell(row=1, column=1).font = Font(bold=True, size=14)
    for c, w in enumerate([40, 22, 18, 18, 18, 16, 18], 1):
        summary.column_dimensions[get_column_letter(c)].width = w
    _table(wb.create_sheet("By reviewer"), ["Reviewer", "System", "Key points compared", "Same grade"], [10, 22, 18, 12],
           [[rv, s, v["n"], pct(v["same"], v["n"])] for (rv, s), v in sorted(per_rv.items())])
    _table(wb.create_sheet("By topic"),
           ["Reviewer", "Topic", "Code", "Title", "Judge: Wiki %", "Reviewer: Wiki %", f"Judge: {rag_name} %",
            f"Reviewer: {rag_name} %", "Judge gap", "Reviewer gap", "Judge's preference", "Reviewer's preference",
            "Fully graded", "Comment"], [10, 7, 8, 30, 12, 12, 14, 14, 10, 12, 16, 16, 14, 40], by_topic)
    _table(wb.create_sheet("By key point"),
           ["Reviewer", "Topic", "Key point", "Kind", "Judge: Wiki", "Reviewer: Wiki", f"Judge: {rag_name}",
            f"Reviewer: {rag_name}", "Agree with judge", "Comment"], [10, 7, 10, 12, 12, 14, 16, 16, 14, 40], by_kp)
    return _save(wb)
