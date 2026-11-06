"""The checks a section or subtopic page must pass, the same wherever the page is written or checked again (an upload,
its later passes, a re-check). A page is checked against every source it cites: each sentence citing a paragraph opens
with the opener of that paragraph's kind; the paragraphs whose write-up the page holds keep their lettered parts and
their conditions. What a page holds is what an upload routed to it, recorded with the page (see store.held_paragraphs)."""
import re

from ..db import get_pool
from ..wiki import checks
from . import fixpass

BASE = lambda label: re.sub(r"(?:\s*\([^)]*\))+$", "", label.strip())  # 5.5.17(a) -> 5.5.17
LABEL = lambda key: key.split("#", 1)[0]  # what a page holds is a paragraph, or one passage of it: "<label>#<n>"


def key_of(by_label: dict[str, list[str]], passage: str) -> str:
    """How a page records that it holds a passage: its label, and where the label has several passages (the upload
    routes each on its own), which of them."""
    lab = re.match(r"^\[([^\]]+)\]", passage).group(1).strip()
    ps = by_label.get(lab, [passage])
    return lab if len(ps) < 2 or passage not in ps else f"{lab}#{ps.index(passage)}"


def passages(by_label: dict[str, list[str]], keys) -> list[str]:
    out = []
    for k in sorted(keys):
        ps = by_label.get(LABEL(k), [])
        out += ps if "#" not in k else ps[int(k.split("#", 1)[1]):][:1]
    return list(dict.fromkeys(out))


async def sources(wiki_id) -> dict[str, dict]:
    """source slug -> {"by_label": label -> its passages, "kinds": label -> paragraph kind}, for every source of the wiki."""
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, text, meta from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    out = {}
    for r in rows:
        by_label: dict[str, list[str]] = {}
        for b in (b.strip() for b in re.split(r"\n\s*\n", r["text"] or "")):
            if m := re.match(r"^\[([^\]]+)\]", b):
                by_label.setdefault(m.group(1).strip(), []).append(b)
        out[r["slug"]] = {"by_label": by_label, "kinds": (r["meta"] or {}).get("para_kinds") or {}}
    return out


def section_check(*, chk, covers, srcs: dict[str, dict], held: dict[str, set[str]], cite_ctx: dict, absence_allowed: bool):
    """check(text) -> the failures of a section or subtopic page's own text (its "Also recorded here" lines left out).
    srcs: as sources() gives; held: source slug -> what the page holds of it (key_of; a source not named: nothing).
    Lettered parts and conditions are checked for the passages it holds; openers for every sentence citing a source."""
    def check(x: str) -> list[str]:
        cited: dict[str, set[str]] = {}
        for c in checks.cites(x):
            sl, lab = c.split("|", 1)
            cited.setdefault(sl, set()).add(BASE(lab))
        out, texts = [], []
        for sl in sorted((set(cited) | set(held)) & set(srcs)):
            mine = passages(srcs[sl]["by_label"], held.get(sl, set()))
            texts += mine + passages(srcs[sl]["by_label"], cited.get(sl, set()))
            out += checks.section_failures(x, mine, srcs[sl]["kinds"], sl, chk, covers, cite_ctx["labels"].get(sl, set()),
                                           agenda=srcs[sl].setdefault("agenda", checks.agenda_labels(srcs[sl]["by_label"], chk)))
        if not absence_allowed:
            out += checks.absence_failures(x, chk, "\n\n".join(texts))
        return out + checks.repeat_failures(x) + checks.heading_failures(x) + fixpass.cite_failures(x, cite_ctx, chk)
    return check


def pass_on(held: dict[str, dict[str, set[str]]], page: str, pieces: dict[str, str], keep: set[str] = frozenset()):
    """A page's blocks moved, word for word, to other pages (pieces: slug -> its text now): each piece holds, of what the
    page held, what it cites; the page itself, when not one of the pieces, holds nothing. keep: sources whose holds on the
    pieces stand as they are (routed by this upload). held: page -> source -> labels, changed in place."""
    was = {s: set(v) for s, v in held.get(page, {}).items()}
    for piece, text in pieces.items():
        here = {c.split("|", 1)[0] + "|" + BASE(c.split("|", 1)[1]) for c in checks.cites(text)}
        for s, labs in was.items():
            if s in keep:
                continue
            got = {k for k in labs if f"{s}|{LABEL(k)}" in here}
            mine = held.setdefault(piece, {})
            mine[s] = got if piece == page else mine.get(s, set()) | got
    if page not in pieces:
        held[page] = {s: set() for s in was}


def held_after_split(held: dict[str, dict[str, set[str]]], report: list[dict], texts: dict[str, str]):
    """What each page holds once pages over the size limit are split (split_written's report), changed in place: each
    piece holds what the page it came from held and the piece cites; a section page that became an index holds nothing."""
    for r in report:
        if r.get("split"):
            pass_on(held, r["page"], {x: texts.get(x, "") for x in r["into"]})


def as_saved(ops: list, existing: dict[str, dict], held: dict[str, dict[str, set[str]]], *, chk, covers, srcs, cite_ctx,
             body, checked: set[str] | None = None) -> list[dict]:
    """Every section and subtopic page of a changeset as it will be saved, checked once more (a later pass may have
    changed what the checks passed), with what it holds set on its op. Returns a failing page's record (still > 0)."""
    subtopics = {o.slug for o in ops if o.type == "subtopic" and o.op != "delete"} | {
        x for x, p in existing.items() if p["type"] == "subtopic"}
    out = []
    for o in ops:
        if o.op == "delete" or o.type not in ("topic", "subtopic"):
            continue
        o.holds = as_holds(held.get(o.slug, {}))
        if any(x.startswith(o.slug + "-") for x in subtopics) or (o.slug in chk.no_claim_pages):
            continue  # an index, a page that holds no claims: checked for what they must hold where they are built
        check = section_check(chk=chk, covers=covers, srcs=srcs, held=held.get(o.slug, {}), cite_ctx=cite_ctx,
                              absence_allowed=checks.absence_allowed_on(chk, o.type, o.title))
        if checked is not None:
            checked.add(o.slug)
        if bad := check(body(o.content_md or "")):
            out.append({"page": o.slug, "kind": "page as saved", "found": len(bad), "still": len(bad), "left": bad, "rounds": []})
    return out


def as_holds(by_source: dict[str, set[str]]) -> dict[str, list[str]]:
    return {s: sorted(v) for s, v in by_source.items()}
