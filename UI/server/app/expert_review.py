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
MAX_SHARED = 4
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


def shared_topics(numbers: list[int], shared: int, seed: int) -> list[int]:
    """The topics every reviewer gets, chosen at random and spread evenly over the groups (with 4: two from each)."""
    rng = random.Random(f"{seed}-shared")
    groups = [g[:] for g in _groups(sorted(numbers))]
    for g in groups:
        rng.shuffle(g)
    out, gi = [], 0
    while len(out) < min(shared, len(numbers)):
        g = groups[gi % len(groups)]
        if g:
            out.append(g.pop())
        gi += 1
    return sorted(out)


def split(numbers: list[int], reviewers: int, seed: int, shared: list[int] | None = None) -> list[list[int]]:
    """The topics of each reviewer: the shared topics, plus the rest each to one reviewer. Within each group the rest are
    shuffled and dealt in turn, the deal carrying on from one group to the next, so the reviewers' totals differ by at
    most one and each group is shared as evenly. With no shared topics the split is as it was before they existed."""
    rng = random.Random(f"{seed}-split")
    out: list[list[int]] = [list(shared or []) for _ in range(reviewers)]
    turn = 0
    for g in _groups(sorted(n for n in numbers if n not in (shared or []))):
        g = g[:]
        rng.shuffle(g)
        for n in g:
            out[turn % reviewers].append(n)
            turn += 1
    return [sorted(x) for x in out]


def _reading(seed: int, number: int) -> str:
    """Which of the judge's two readings (orders) a topic shows: the seed's choice, so A/B is random per topic."""
    return random.Random(f"{seed}-order-{number}").choice(("1", "2"))


def _check(data: dict, pair: str, rep: int, reviewers: int, shared: int):
    opt = options(data)
    if pair not in opt["pairs"]:
        raise ReviewError(f"This run has no judged pair '{pair}'")
    if rep not in opt["repetitions"][pair]:
        raise ReviewError(f"This run has no repetition {rep} for that pair")
    if not 1 <= reviewers <= MAX_REVIEWERS:
        raise ReviewError(f"Reviewers: 1 to {MAX_REVIEWERS}")
    if not 0 <= shared <= MAX_SHARED:
        raise ReviewError(f"Shared topics: 0 to {MAX_SHARED}")


def plan(data: dict, pair: str, rep: int, reviewers: int, seed: int, shared: int = 0) -> dict:
    """The topic split the files will use: the shared topics (every reviewer's), each reviewer's topics, and the topics
    left out because that repetition was not judged for them."""
    _check(data, pair, rep, reviewers, shared)
    nums = [t["number"] for t in _topics(data) if _usable(t, pair, str(rep))]
    left_out = [t["number"] for t in _topics(data) if t["number"] not in nums]
    groups = _groups(nums)
    common = shared_topics(nums, shared, seed) if nums else []
    return {"seed": seed, "pair": pair, "repetition": rep, "options": options(data),
            "groups": [[g[0], g[-1]] for g in groups], "left_out": left_out, "shared": common,
            "reviewers": [{"n": i + 1, "topics": ts, "own": [n for n in ts if n not in common],
                           "by_group": [sum(1 for n in ts if n in g) for g in groups],
                           "own_by_group": [sum(1 for n in ts if n in g and n not in common) for g in groups]}
                          for i, ts in enumerate(split(nums, reviewers, seed, common))]}


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


def _cover(points: list[dict], grades: dict, kind: str | None = None) -> float | None:
    """Coverage %, as the run computes it (full 1, partial ½, missing 0), over all key points or one kind's; None when a
    point has no grade or there is no point of that kind."""
    ids = [p["id"] for p in points if kind is None or p.get("kind") == kind]
    if not ids or any(grades.get(i) not in WEIGHT for i in ids):
        return None
    return round(100 * sum(WEIGHT[grades[i]] for i in ids) / len(ids), 1)


STANDARD = "standard"  # the key point kind that counts for standard-only coverage (as the run's coverage_standard)


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


def build(data: dict, run_id: str, pair: str, rep: int, reviewers: int, seed: int, label: dict,
          shared: int = 0) -> tuple[dict[str, bytes], str]:
    """The files by name (one per reviewer, then the KEY), and all the text written into the reviewer files (to check that
    nothing that must stay out of them is in them). A shared topic is written the same in every reviewer's file: one
    judge reading, so the same Answer A and Answer B."""
    p = plan(data, pair, rep, reviewers, seed, shared)
    topics = {t["number"]: t for t in _topics(data)}
    made = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    name = {"wiki": label.get("wiki", "Wiki"), pair: label.get(pair, pair)}
    who = {n: [rv["n"] for rv in p["reviewers"] if n in rv["topics"]] for rv in p["reviewers"] for n in rv["topics"]}
    rows, key_topics, key_points = {}, [], []
    for n in sorted(who):  # each topic once: what every reviewer who has it sees, and its line in the KEY
        t = topics[n]
        run = t["runs"][str(rep)]
        k = _reading(seed, n)
        o = _orders(run, pair)[k]
        lab = o["blind_labels"]  # {"A": system, "B": system}, as the judge saw them in this reading
        g = {s: (o["systems"].get(s) or {}).get("grades") or {} for s in lab.values()}
        notes = o.get("point_notes") or {}
        pts = t.get("key_points") or []
        kp_rows = [[n, t.get("code"), t.get("title"), kp.get("id"), kp.get("kind"), kp.get("point"),
                    g[lab["A"]].get(kp["id"], ""), g[lab["B"]].get(kp["id"], ""), notes.get(kp["id"], ""),
                    None, None, None, None] for kp in pts]
        ans_row = [n, t.get("code"), t.get("title"), t.get("question"), t.get("reference"),
                   _plain(((run.get("systems") or {}).get(lab["A"]) or {}).get("answer")),
                   _plain(((run.get("systems") or {}).get(lab["B"]) or {}).get("answer")),
                   _letter(lab, o.get("winner") or ""), None, None]
        rows[n] = (kp_rows, ans_row)
        key_points += [[n, kp.get("id"), kp.get("kind"), g["wiki"].get(kp["id"], ""), g[pair].get(kp["id"], "")] for kp in pts]
        both = _both(run, pair)
        key_topics.append([n, t.get("code"), t.get("title"), ", ".join(map(str, who[n])), "yes" if n in p["shared"] else "no",
                           name[lab["A"]], name[lab["B"]], int(k), name.get(o.get("winner"), "tie"),
                           _cover(pts, g["wiki"], STANDARD), _cover(pts, g[pair], STANDARD),
                           both["wiki"]["coverage_standard"], both[pair]["coverage_standard"],
                           _cover(pts, g["wiki"]), _cover(pts, g[pair]), both["wiki"]["coverage"], both[pair]["coverage"]])
    files, written = {}, []
    for rv in p["reviewers"]:
        wb = Workbook()
        ins = wb.active
        ins.title = "Instructions"
        review_id = f"Run {run_id} · Reviewer {rv['n']} of {reviewers} · repetition {rep}"
        common = [n for n in rv["topics"] if n in p["shared"]]
        _put(ins, 1, ["Expert review", review_id])
        _put(ins, 2, ["Your topics", ", ".join(map(str, rv["topics"])) or "none"])
        _put(ins, 3, ["Shared topics", (", ".join(map(str, common)) + ": every reviewer has these topics, exactly as they "
                      "are here. Grade them on your own, like the others.") if common and reviewers > 1 else "none"])
        for i, (k, v) in enumerate(INSTRUCTIONS, 5):
            _put(ins, i, [k, v])
            ins.cell(row=i, column=1).font = HEAD_FONT
        ins.cell(row=1, column=1).font = Font(bold=True, size=14)
        for r in (2, 3):
            ins.cell(row=r, column=1).font = HEAD_FONT
        ins.column_dimensions["A"].width = 26
        ins.column_dimensions["B"].width = 110
        J, Y = JUDGE_FILL, YOURS_FILL
        _table(wb.create_sheet("Key points"),
               ["Topic", "Code", "Title", "Key point", "Kind", "Point", "Judge: A", "Judge: B", "Judge's note",
                "Your grade: A", "Your grade: B", "Agree with judge", "Comment"],
               [7, 8, 24, 9, 11, 50, 10, 10, 50, 13, 13, 14, 40], [r for n in rv["topics"] for r in rows[n][0]],
               {7: J, 8: J, 9: J, 10: Y, 11: Y, 12: Y, 13: Y}, {10: GRADES, 11: GRADES, 12: AGREE})
        _table(wb.create_sheet("Answers"),
               ["Topic", "Code", "Title", "Question", "Reference text", "Answer A", "Answer B", "Judge's preference",
                "Your preference", "Comment"],
               [7, 8, 24, 40, 60, 70, 70, 12, 12, 40], [rows[n][1] for n in rv["topics"]], {8: J, 9: Y, 10: Y}, {9: PREFER})
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                written.extend(str(c.value) for c in row if c.value is not None)
        files[f"Expert_Review_{run_id}_Reviewer{rv['n']}.xlsx"] = _save(wb)
    files[f"Expert_Review_{run_id}_KEY.xlsx"] = _key(run_id, p, made, name, key_topics, key_points)
    return files, "\n".join(written)


def _both(run: dict, pair: str) -> dict:
    """Each system's coverage and standard-only coverage as the run scored them in this pair (the mean of the judge's two
    readings)."""
    wiki = (run.get("systems") or {}).get("wiki") if pair == "rag" else ((run.get("pairs") or {}).get(pair) or {}).get("wiki")
    rag = (run.get("systems") or {}).get(pair) or {}
    return {s: {k: (x or {}).get(k) for k in ("coverage", "coverage_standard")} for s, x in (("wiki", wiki), (pair, rag))}


KEY_TOPICS = ["Topic", "Code", "Title", "Reviewers", "Shared", "Answer A is", "Answer B is", "Judge's reading shown",
              "Judge's preference (this reading)",
              "Judge standard-only coverage: Wiki (this reading)", "Judge standard-only coverage: RAG (this reading)",
              "Judge standard-only coverage: Wiki (run, both readings)", "Judge standard-only coverage: RAG (run, both readings)",
              "Judge coverage: Wiki (this reading)", "Judge coverage: RAG (this reading)",
              "Judge coverage: Wiki (run, both readings)", "Judge coverage: RAG (run, both readings)"]


def _key(run_id: str, p: dict, made: str, name: dict, topics: list, points: list) -> bytes:
    wb = Workbook()
    s = wb.active
    s.title = "Settings"
    rows = [["KEY: keep this file yourself; never send it to a reviewer", ""], ["Run", run_id],
            ["Wiki", name["wiki"]], ["Wiki against", name[p["pair"]]], ["Pair", p["pair"]], ["Repetition", p["repetition"]],
            ["Reviewers", len(p["reviewers"])], ["Seed", p["seed"]],
            ["Shared topics", ", ".join(map(str, p["shared"])) or "none"], ["Made", made],
            ["Topics left out", ", ".join(map(str, p["left_out"])) or "none"],
            ["RAG", f"in the column names below, RAG is {name[p['pair']]}"]]
    for i, r in enumerate(rows, 1):
        _put(s, i, r)
        s.cell(row=i, column=1).font = HEAD_FONT
    s.cell(row=1, column=1).font = Font(bold=True, size=14, color="C00000")
    s.column_dimensions["A"].width = 22
    s.column_dimensions["B"].width = 50
    _table(wb.create_sheet("Topics"), KEY_TOPICS, [7, 8, 30, 10, 8, 18, 18, 12, 18] + [14] * 8, topics)
    _table(wb.create_sheet("Key points"), ["Topic", "Key point", "Kind", "Judge: Wiki", "Judge: RAG"], [7, 10, 12, 12, 12], points)
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


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


def _ints(v) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", str(v or ""))]


SYSTEMS = ("wiki", "rag")


def results(key: bytes, returned: list[bytes]) -> bytes:
    """The results workbook: the wiki − RAG gap from the reviewers' grades beside the judge's (standard-only coverage
    first, then coverage over all key points), how often the reviewers agree with the judge for the wiki's answers and the
    RAG answers separately, how often they agree with each other on the shared topics, and their preferences. A shared
    topic counts once in a gap: its reviewers' grades are averaged first."""
    kb = load_workbook(io.BytesIO(key), read_only=True)
    if "Settings" not in kb.sheetnames:
        raise ReviewError("The first file is not a KEY file (it has no Settings sheet)")
    settings = {str(r[0]): r[1] for r in kb["Settings"].iter_rows(values_only=True) if r and r[0]}
    run_id = str(settings["Run"])
    show = {"wiki": str(settings["Wiki"]), "rag": str(settings["Wiki against"])}
    shared = set(_ints(settings.get("Shared topics")))
    topics = {int(r["Topic"]): r for r in _sheet(kb, "Topics")}
    owners = {n: set(_ints(t["Reviewers"])) for n, t in topics.items()}
    judge = {(int(r["Topic"]), str(r["Key point"])): r for r in _sheet(kb, "Key points")}
    points: dict[int, list[tuple[str, str]]] = {}
    for (n, kp), r in judge.items():
        points.setdefault(n, []).append((kp, str(r["Kind"] or "")))
    grades: dict[tuple, dict] = {}  # (reviewer, topic, key point) -> the reviewer's grade per system, agree, comment
    prefs: dict[tuple, dict] = {}  # (reviewer, topic) -> preferred system (or tie), comment
    read = []
    for blob in returned:
        wb = load_workbook(io.BytesIO(blob), read_only=True)
        if "Instructions" not in wb.sheetnames:
            raise ReviewError("A returned file is not a reviewer file (it has no Instructions sheet)")
        ident = str(next(wb["Instructions"].iter_rows(min_row=1, max_row=1, values_only=True))[1] or "")
        m = re.match(r"Run (\S+) · Reviewer (\d+) of", ident)
        if not m or m.group(1) != run_id:
            raise ReviewError(f"A returned file is not from run {run_id}: '{ident}'")
        rv = int(m.group(2))
        if rv in read:
            raise ReviewError(f"Reviewer {rv}'s file was given twice")
        read.append(rv)

        def side(n: int) -> dict:
            t = topics.get(n)
            if not t or rv not in owners[n]:
                raise ReviewError(f"Reviewer {rv}'s file has topic {n}, which the KEY does not give to that reviewer")
            return {x: "wiki" if t[f"Answer {x} is"] == show["wiki"] else "rag" for x in ("A", "B")}
        for r in _sheet(wb, "Key points"):
            n, kp = int(r["Topic"]), str(r["Key point"])
            sys_of = side(n)
            grades[(rv, n, kp)] = {sys_of["A"]: _norm(r.get("Your grade: A"), GRADES),
                                   sys_of["B"]: _norm(r.get("Your grade: B"), GRADES),
                                   "agree": _norm(r.get("Agree with judge"), AGREE), "comment": r.get("Comment") or ""}
        for r in _sheet(wb, "Answers"):
            n = int(r["Topic"])
            sys_of = {**side(n), "tie": "tie"}
            mine = _norm(r.get("Your preference"), PREFER)
            prefs[(rv, n)] = {"pref": sys_of[mine] if mine else None, "comment": r.get("Comment") or ""}
    expected = sum(len(points.get(n, [])) for n, o in owners.items() for rv in o if rv in read)

    # agreement with the judge: every reviewer's grade counts
    stats = {s: {"n": 0, "same": 0, "higher": 0, "lower": 0, "judge": [], "mine": []} for s in SYSTEMS}
    per_rv: dict[tuple, dict] = {}
    agree = {a: 0 for a in AGREE}
    by_kp = []
    for (rv, n, kp), g in sorted(grades.items(), key=lambda x: (x[0][1], x[0][0], x[0][2])):
        j = judge[(n, kp)]
        row = [rv, n, "yes" if n in shared else "no", kp, j["Kind"]]
        for s in SYSTEMS:
            jg, mg = _norm(j["Judge: Wiki" if s == "wiki" else "Judge: RAG"], GRADES), g.get(s)
            row += [jg, mg]
            if jg and mg:
                st, rs = stats[s], per_rv.setdefault((rv, s), {"n": 0, "same": 0})
                st["n"] += 1
                rs["n"] += 1
                st["judge"].append(WEIGHT[jg])
                st["mine"].append(WEIGHT[mg])
                rs["same"] += jg == mg
                st["same"] += jg == mg
                st["higher"] += WEIGHT[mg] > WEIGHT[jg]
                st["lower"] += WEIGHT[mg] < WEIGHT[jg]
        if g["agree"]:
            agree[g["agree"]] += 1
        by_kp.append(row + [g["agree"], g["comment"]])

    # per topic: the reviewers' grades averaged per key point (a shared topic counts once), then coverage
    def mine_cov(n: int, kind: str | None) -> dict | None:
        done = [rv for rv in sorted(owners[n] & set(read))
                if all(grades.get((rv, n, kp), {}).get(s) for kp, _ in points.get(n, []) for s in SYSTEMS)]
        pts = [kp for kp, k in points.get(n, []) if kind is None or k == kind]
        if not done or not pts:
            return None
        return {s: round(100 * statistics.fmean(statistics.fmean(WEIGHT[grades[(rv, n, kp)][s]] for rv in done) for kp in pts), 1)
                for s in SYSTEMS} | {"by": done}

    measures = {"std": (STANDARD, "standard-only coverage"), "all": (None, "coverage")}
    gaps = {m: {"mine": [], "this": [], "run": []} for m in measures}
    by_topic = []
    for n, t in sorted(topics.items()):
        line = [n, t["Code"], t["Title"], t["Reviewers"], t["Shared"]]
        mc = {}
        for m, (kind, label) in measures.items():
            col = "Judge standard-only coverage" if m == "std" else "Judge coverage"
            jt = (t[f"{col}: Wiki (this reading)"], t[f"{col}: RAG (this reading)"])
            jr = (t[f"{col}: Wiki (run, both readings)"], t[f"{col}: RAG (run, both readings)"])
            mc[m] = c = mine_cov(n, kind)
            if c and None not in jt:
                gaps[m]["mine"].append(c["wiki"] - c["rag"])
                gaps[m]["this"].append(jt[0] - jt[1])
                gaps[m]["run"].append(jr[0] - jr[1] if None not in jr else None)
            line += [jt[0], c and c["wiki"], jt[1], c and c["rag"],
                     round(jt[0] - jt[1], 1) if None not in jt else None, round(c["wiki"] - c["rag"], 1) if c else None]
        line += [t["Judge's preference (this reading)"],
                 "; ".join(f"{rv}: {show.get(prefs[(rv, n)]['pref'], prefs[(rv, n)]['pref']) or '—'}"
                           for rv in sorted(owners[n]) if (rv, n) in prefs),
                 ", ".join(map(str, mc["all"]["by"])) if mc["all"] else "not fully graded",
                 " | ".join(f"{rv}: {prefs[(rv, n)]['comment']}" for rv in sorted(owners[n]) if prefs.get((rv, n), {}).get("comment"))]
        by_topic.append(line)

    system_of = {show["wiki"]: "wiki", show["rag"]: "rag", "tie": "tie"}
    pref_same = sum(1 for (rv, n), p in prefs.items()
                    if p["pref"] and p["pref"] == system_of.get(topics[n]["Judge's preference (this reading)"]))
    pref_n = sum(1 for p in prefs.values() if p["pref"])

    # the reviewers against each other, on the shared topics: pairs of reviewers giving the same grade or preference
    pair_kp = {s: [0, 0] for s in SYSTEMS}
    pair_pref = [0, 0]
    cmp_rows, cmp_prefs = [], []
    seen = sorted(read)
    for n in sorted(shared & set(topics)):
        rvs = [rv for rv in seen if rv in owners[n]]
        for kp, kind in points.get(n, []):
            row = [n, kp, kind]
            for s in SYSTEMS:
                vals = [grades.get((rv, n, kp), {}).get(s) for rv in rvs]
                row += vals
                got = [v for v in vals if v]
                for a in range(len(got)):
                    for b in range(a + 1, len(got)):
                        pair_kp[s][0] += got[a] == got[b]
                        pair_kp[s][1] += 1
                row.append("yes" if len(got) > 1 and len(set(got)) == 1 else "no" if len(got) > 1 else "—")
            cmp_rows.append(row)
        ps = [(prefs.get((rv, n)) or {}).get("pref") for rv in rvs]
        got = [p for p in ps if p]
        for a in range(len(got)):
            for b in range(a + 1, len(got)):
                pair_pref[0] += got[a] == got[b]
                pair_pref[1] += 1
        cmp_prefs.append([n, *[show.get(p, p) or "—" for p in ps],
                          "yes" if len(got) > 1 and len(set(got)) == 1 else "no" if len(got) > 1 else "—"])

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"

    def gap_lines(m: str) -> list[list]:
        label = measures[m][1]
        g = gaps[m]
        run_pairs = [(a, b) for a, b in zip(g["mine"], g["run"]) if b is not None]
        return [[f"Wiki − RAG gap in {label}", "Topics", "Mean gap (points)", "Approx. 95% interval"],
                [f"{label.capitalize()} gap: reviewers", len(g["mine"]), _mean(g["mine"]), _ci(g["mine"])],
                [f"{label.capitalize()} gap: judge, the reading the reviewers saw", len(g["this"]), _mean(g["this"]), _ci(g["this"])],
                [f"{label.capitalize()} gap: judge, as the run scored it (both readings)", len(run_pairs),
                 _mean([b for _, b in run_pairs]), _ci([b for _, b in run_pairs])],
                [f"{label.capitalize()} gap: reviewers − judge (the reading they saw)", len(g["mine"]),
                 _mean([a - b for a, b in zip(g["mine"], g["this"])]), _ci([a - b for a, b in zip(g["mine"], g["this"])])],
                [f"{label.capitalize()} gap: reviewers − judge (as the run scored it)", len(run_pairs),
                 _mean([a - b for a, b in run_pairs]), _ci([a - b for a, b in run_pairs])]]

    lines = [["Expert review results", f"Run {run_id} · Wiki against {show['rag']} (called RAG below) · repetition "
              f"{settings['Repetition']} · seed {settings['Seed']}"],
             ["Files read", f"reviewers {', '.join(map(str, sorted(read)))} of {settings['Reviewers']}; "
              f"shared topics {', '.join(map(str, sorted(shared))) or 'none'}"],
             ["Key points graded", f"{sum(1 for g in grades.values() if g.get('wiki') and g.get('rag'))} of {expected} "
              "(both answers graded)"], [],
             *gap_lines("std"),
             ["Read it as", "Standard-only coverage counts only the key points of kind 'standard'. A positive gap means the "
              "wiki covers more; a positive 'reviewers − judge' means the reviewers see the wiki further ahead than the judge "
              "did. A shared topic counts once (its reviewers' grades averaged); only topics with every key point graded for "
              "both answers count, and topics with no standard key point are left out of the standard-only figures."], [],
             *gap_lines("all"), [],
             ["Agreement with the judge", "Key points compared", "Same grade", "Reviewer higher", "Reviewer lower",
              "Judge coverage", "Reviewer coverage"]]
    for s in SYSTEMS:
        st = stats[s]
        lines.append([show[s], st["n"], _pct(st["same"], st["n"]), _pct(st["higher"], st["n"]), _pct(st["lower"], st["n"]),
                      f"{100 * statistics.fmean(st['judge']):.1f}%" if st["judge"] else "—",
                      f"{100 * statistics.fmean(st['mine']):.1f}%" if st["mine"] else "—"])
    lines += [["Read it as", "Every reviewer's grade counts here, a shared topic's once per reviewer. If the judge favours "
               "one system, the reviewers grade that system lower than the judge (Reviewer lower) more often than the other."], [],
              ["Agree with judge (column)", "yes", "partly", "no"], ["", agree["yes"], agree["partly"], agree["no"]], [],
              ["Preferred answer", "Preferences given", "Same as the judge's (the reading they saw)"],
              ["", pref_n, _pct(pref_same, pref_n)], [],
              ["Reviewers with each other (shared topics)", "Pairs compared", "Same"],
              [f"Key point grades: {show['wiki']}", pair_kp["wiki"][1], _pct(*pair_kp["wiki"])],
              [f"Key point grades: {show['rag']}", pair_kp["rag"][1], _pct(*pair_kp["rag"])],
              ["Preferred answer", pair_pref[1], _pct(*pair_pref)]]
    for i, r in enumerate(lines, 1):
        _put(summary, i, r)
        summary.cell(row=i, column=1).font = HEAD_FONT
    summary.cell(row=1, column=1).font = Font(bold=True, size=14)
    for c, w in enumerate([58, 20, 18, 22, 18, 16, 18], 1):
        summary.column_dimensions[get_column_letter(c)].width = w

    _compare_sheet(wb.create_sheet("Reviewers compared"), seen, shared, owners, show, cmp_rows, cmp_prefs, pair_kp, pair_pref)
    _table(wb.create_sheet("By reviewer"), ["Reviewer", "System", "Key points compared with the judge", "Same grade"],
           [10, 22, 18, 12], [[rv, show[s], v["n"], _pct(v["same"], v["n"])] for (rv, s), v in sorted(per_rv.items())])
    head = ["Topic", "Code", "Title", "Reviewers", "Shared"]
    for label in ("Standard-only coverage", "Coverage"):
        head += [f"{label}: judge, Wiki %", f"{label}: reviewers, Wiki %", f"{label}: judge, RAG %",
                 f"{label}: reviewers, RAG %", f"{label} gap: judge", f"{label} gap: reviewers"]
    _table(wb.create_sheet("By topic"), head + ["Judge's preference", "Reviewers' preferences", "Fully graded by", "Comments"],
           [7, 8, 30, 10, 8] + [13] * 12 + [16, 22, 14, 40], by_topic)
    _table(wb.create_sheet("By key point"),
           ["Reviewer", "Topic", "Shared", "Key point", "Kind", "Judge: Wiki", "Reviewer: Wiki", "Judge: RAG", "Reviewer: RAG",
            "Agree with judge", "Comment"], [10, 7, 8, 10, 12, 12, 14, 12, 14, 14, 40], by_kp)
    return _save(wb)


def _compare_sheet(ws, seen, shared, owners, show, rows, prefs, pair_kp, pair_pref):
    """The reviewers against each other on the shared topics: % agreement, then each key point's grades and each topic's
    preference side by side."""
    rvs = [rv for rv in seen if any(rv in owners[n] for n in shared if n in owners)]
    top = [["Reviewers with each other on the shared topics", f"topics {', '.join(map(str, sorted(shared))) or 'none'}"],
           ["", "Pairs compared", "Same"],
           [f"Key point grades: {show['wiki']}", pair_kp["wiki"][1], _pct(*pair_kp["wiki"])],
           [f"Key point grades: {show['rag']}", pair_kp["rag"][1], _pct(*pair_kp["rag"])],
           ["Preferred answer", pair_pref[1], _pct(*pair_pref)],
           ["Read it as", "Each pair of reviewers who graded the same item counts once (with 2 reviewers, one pair)."], []]
    for i, r in enumerate(top, 1):
        _put(ws, i, r)
        ws.cell(row=i, column=1).font = HEAD_FONT
    start = len(top) + 1
    head = ["Topic", "Key point", "Kind"]
    for s in SYSTEMS:
        head += [f"Reviewer {rv}: {show[s]}" for rv in rvs] + [f"Same: {show[s]}"]
    _put(ws, start, head)
    for c in range(1, len(head) + 1):
        ws.cell(row=start, column=c).font = HEAD_FONT
    for i, r in enumerate(rows, start + 1):
        _put(ws, i, r)
    end = start + max(len(rows), 1)
    ws.auto_filter.ref = f"A{start}:{get_column_letter(len(head))}{end}"
    ws.freeze_panes = f"A{start + 1}"
    p0 = end + 2
    _put(ws, p0, ["Topic (preferred answer)", *[f"Reviewer {rv}" for rv in rvs], "Same"])
    for c in range(1, len(rvs) + 3):
        ws.cell(row=p0, column=c).font = HEAD_FONT
    for i, r in enumerate(prefs, p0 + 1):
        _put(ws, i, r)
    for c, w in enumerate([44, 16, 14] + [16] * (2 * len(rvs) + 2), 1):
        ws.column_dimensions[get_column_letter(c)].width = w
