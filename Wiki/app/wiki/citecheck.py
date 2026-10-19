"""Check every source citation on written pages against the clauses of the source it names.

A citation [[source-slug|label]] cites a clause when one of the source's paragraph labels (as the reader stored them:
"[5.5.17] ...", "[IE4] (Illustrative example) ...", "[IG A.1] ...", "[Appendix A: credit loss] ...") appears in the label.
- the clause is in the source named: the citation is left alone;
- it is not, but it is in exactly one other source of the wiki: the citation is corrected to name that source;
- it is in no source, or in more than one other: the citation is left alone and flagged.
A bare number ("15") is never corrected, only flagged: many sources have a paragraph 15, so it says too little to move.
"""
import re
from collections import Counter
from uuid import UUID

from ..db import get_pool

CITE_RE = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?\|([^\]]+)\]\]")
LABEL_RE = re.compile(r"^\[([^\]\n]+)\]", re.M)
RANGE_RE = re.compile(r"\s*[–-]\s*")
STANDARD_NAME = re.compile(r"\b(?:IFRS|IAS|IFRIC|SIC)\s*\d+\b")  # "IFRS 9 5.5.17": the 9 is a Standard's name, not a clause
FILLER = re.compile(r"\([^)]*\)|\b(?:paragraphs?|paras?|and|to|also)\b|[\s,;:.\u2013\-–]+", re.I)  # left when a label is only clauses


def _norm(label: str) -> str:
    label = re.sub(r"\bApp(?:endix)?\s*([A-Z])\s*:\s*", r"Appendix \1: ", label, flags=re.I)
    label = re.sub(r"(\d[A-Z]{0,2})([a-z]{1,2})\b", r"\1(\2)", label)  # "3a", "11Aa-e": sub-paragraphs 3(a), 11A(a)-(e)
    return STANDARD_NAME.sub(" ", " ".join(label.split())).strip()


def _matcher(text: str) -> re.Pattern | None:
    """One pattern matching any of the source's paragraph labels (each end of a range label too) as a whole clause."""
    labels = set()
    for lab in LABEL_RE.findall(text or ""):
        lab = _norm(lab)
        labels.add(lab)
        if not lab.lower().startswith("appendix"):
            for x in (x for x in RANGE_RE.split(lab) if x):
                labels.add(x)
                parts = x.split(".")  # a section number (5.5 of 5.5.17, B5.5 of B5.5.17) is in the source too
                labels.update(".".join(parts[:k]) for k in range(2, len(parts)))
    labels = sorted((x for x in labels if x), key=len, reverse=True)
    if not labels:
        return None
    return re.compile(r"(?<![\w.])(?:" + "|".join(map(re.escape, labels)) + r")(?![\w]|\.\d)", re.I)


async def sources(wiki_id: UUID) -> dict[str, re.Pattern]:
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, text from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    return {r["slug"]: m for r in rows if (m := _matcher(r["text"]))}


def _covered(key: str, pat: re.Pattern) -> bool:
    """Whether the label is only clauses of this source (ranges, sub-paragraph letters and 'paragraphs' aside)."""
    return bool(pat.search(key)) and not FILLER.sub("", pat.sub("", key))


def check(content: str, matchers: dict[str, re.Pattern]) -> tuple[str, Counter, Counter]:
    """The page text with wrongly attributed citations corrected; Counters of (from, to, label) fixes and of
    (source, label, reason) flags."""
    fixed, flagged = Counter(), Counter()

    def one(m: re.Match) -> str:
        slug, anchor, label = m.group(1), m.group(2) or "", m.group(3)
        if slug not in matchers:
            return m.group(0)  # not a source page (or one the wiki does not hold): not a citation to check
        key = _norm(label)
        if not re.search(r"\d", key):
            return m.group(0)  # no clause number ("IFRS 9", "Appendix A"): the citation names the source as a whole
        para = re.sub(r"^p(?=[A-Z]{0,4}\d)", "", key)  # "p35A", "pB8E": paragraphs 35A, B8E (or a page label such as p93: both are tried)
        if matchers[slug].search(key) or matchers[slug].search(para):
            return m.group(0)
        others = [s for s, pat in matchers.items() if s != slug and _covered(key, pat)]
        if not others and para != key:
            others, key = [s for s, pat in matchers.items() if s != slug and _covered(para, pat)], para
        if len(others) == 1 and re.fullmatch(r"(?:paragraphs?\s*)?\d+(?:\([^)]*\))*", key, re.I):
            flagged[(slug, label, f"bare number, not in this source (it is in {others[0]})")] += 1
            return m.group(0)
        if len(others) == 1:
            fixed[(slug, others[0], label)] += 1
            return f"[[{others[0]}{anchor}|{label}]]"
        flagged[(slug, label, "not in any source" if not others else "in several sources: " + ", ".join(sorted(others)))] += 1
        return m.group(0)

    return CITE_RE.sub(one, content or ""), fixed, flagged


async def check_ops(wiki_id: UUID, ops: list) -> dict:
    """Check and correct the citations of the pages about to be written; a report for the job."""
    matchers = await sources(wiki_id)
    report = {"corrected": [], "flagged": []}
    if not matchers:
        return report
    for o in ops:
        if not o.content_md:
            continue
        o.content_md, fixed, flagged = check(o.content_md, matchers)
        if fixed:
            moves = Counter()
            for (a, b, _), n in fixed.items():
                moves[(a, b)] += n
            report["corrected"].append({"page": o.slug, "count": sum(fixed.values()),
                                        "moves": [{"from": a, "to": b, "count": n} for (a, b), n in moves.items()],
                                        "labels": sorted({lab for (_, _, lab) in fixed})[:50]})
        for (src, lab, reason), n in flagged.items():
            report["flagged"].append({"page": o.slug, "source": src, "label": lab, "reason": reason, "count": n})
    return report
