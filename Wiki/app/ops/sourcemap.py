"""Source map (read only): which sections of each source a page draws on, and which pages each section of a source
informs. Built from what is stored; changes nothing.

A source's sections are its passages' heading paths, in document order, as the reader recorded them (meta
heading_paths); a passage under no heading is a section of its own, named by its label. A page draws on a section
where the citation group ending one of its sentences (checks.closing_links) cites a label of a passage in that section;
a link inside a sentence is a pointer, not a citation, and does not count."""
import re

from ..db import get_pool
from ..wiki import checks, store
from .ingest import _drop_title, _ref
from .pagecheck import BASE

RANGE = re.compile(r"\s*[–-]\s*")  # "B11D(a)-(e)", "B5.5.1–B5.5.6": a range is read as its first label
PAGE_NUMBER = re.compile(r"p(?:age)?\s*(\d+)", re.I)  # the PDF reader's page label (checks.PAGE_LABEL), its number kept


def shown(section: str, c: checks.Checks | None) -> str:
    """How a section is shown. A section named by the reader's page label reads "Page 74"; one named in a citation
    form the schema gives for text without a paragraph label (e.g. "ED:<clause>") is shown as what follows the form's
    prefix, with the schema's name for that kind in brackets ("Page 79 (editorial note)"). Any other name as it is."""
    for kind, form in (c.unlabelled_forms if c else {}).items():
        tag = form.split("<", 1)[0]
        if "<" in form and tag and section.startswith(tag) and section != tag:
            return f"{shown(section[len(tag):], None)} ({kind})"
    m = PAGE_NUMBER.fullmatch(section)
    return f"Page {m.group(1)}" if m else section


def sections(text: str, heading_paths: list | None) -> tuple[list[str], dict[str, str]]:
    """A source's sections in document order, and each passage label's section."""
    passages = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]  # as the reader stored them
    hp = heading_paths if heading_paths and len(heading_paths) == len(passages) else [[] for _ in passages]
    paths = _drop_title([[h for _, h in p] for p in hp])
    order, of_label, label = [], {}, ""
    for para, path in zip(passages, paths):
        label = _ref(para) or label  # a passage with no label of its own continues the one before it
        if not label:
            continue
        name = " > ".join(path) or label
        of_label.setdefault(label, name)
        if name not in order:
            order.append(name)
    return order, of_label


def section_of(label: str, of_label: dict[str, str]) -> str | None:
    """The section a cited label sits in: the label itself, then without its sub-item letters (5.5.17(a)), then a
    range's first label, then the longest label the citation begins with ("X > Figure 2" where the reader labelled only
    "X"). None where the source has no such location."""
    for lab in (label, BASE(label), BASE(RANGE.split(label)[0])):
        if lab in of_label:
            return of_label[lab]
    starts = [x for x in of_label if label.startswith(x) and not label[len(x):len(x) + 1].isalnum()]
    return of_label[max(starts, key=len)] if starts else None


def cited(content_md: str) -> list[set[tuple[str, str]]]:
    """Per sentence (or list part, table cell), the (source, label) pairs its closing citation group cites."""
    out = []
    for line in (content_md or "").split("\n"):
        line = line.strip().lstrip("-*• ").strip()
        if not line or line.startswith("#"):
            continue
        for unit in checks.units(line):
            pairs = {(m.group(1), lab.strip()) for m in checks.closing_links(unit) if m.group(1).startswith("source-")
                     for lab in (m.group(2) or "").split(",") if lab.strip()}
            if pairs:
                out.append(pairs)
    return out


async def _sources(wiki_id, slugs: list[str] | None = None) -> dict[str, dict]:
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            "select slug, title, text, meta->'heading_paths' as hp from wiki.sources where wiki_id = %s"
            + (" and slug = any(%s)" if slugs is not None else "") + " order by created_at",
            (wiki_id, slugs) if slugs is not None else (wiki_id,))).fetchall()
    return {r["slug"]: {"title": r["title"], "sections": sections(r["text"], r["hp"])} for r in rows}


async def page_map(wiki_id, content_md: str, c: checks.Checks | None = None) -> list[dict]:
    """For each source the page cites: its sections the page draws on, in the source's order, with the number of the
    page's sentences citing each; and any cited location the source does not have."""
    units = cited(content_md)
    srcs = await _sources(wiki_id, sorted({s for u in units for s, _ in u}))
    out = []
    for slug, info in srcs.items():
        order, of_label = info["sections"]
        count, missing = {}, {}
        for u in units:
            secs = set()
            for s, lab in u:
                if s == slug:
                    if sec := section_of(lab, of_label):
                        secs.add(sec)
                    else:
                        missing[lab] = missing.get(lab, 0) + 1
            for sec in secs:
                count[sec] = count.get(sec, 0) + 1
        out.append({"slug": slug, "title": info["title"],
                    "sections": [{"section": sec, "name": shown(sec, c), "sentences": count[sec]} for sec in order if sec in count],
                    "not_in_source": [{"label": k, "sentences": v} for k, v in missing.items()]})
    return out


async def source_contents(wiki_id, source_slug: str, c: checks.Checks | None = None) -> dict | None:
    """A source's sections in document order, each with the pages that draw on it (and how many of their sentences
    cite it); then the sections no page draws on; then any cited location the source does not have. None where the
    slug is not a source of the wiki. The source's own page is left out: it describes the source, it is not informed by it."""
    srcs = await _sources(wiki_id, [source_slug])
    if source_slug not in srcs:
        return None
    order, of_label = srcs[source_slug]["sections"]
    pages = [p for p in await store.list_pages(wiki_id, with_content=True) if p["slug"] != source_slug]
    by_sec: dict[str, dict[str, int]] = {}
    missing: dict[str, set[str]] = {}
    for p in pages:
        for u in cited(p["content_md"]):
            secs = set()
            for s, lab in u:
                if s == source_slug:
                    if sec := section_of(lab, of_label):
                        secs.add(sec)
                    else:
                        missing.setdefault(lab, set()).add(p["slug"])
            for sec in secs:
                by_sec.setdefault(sec, {})[p["slug"]] = by_sec.get(sec, {}).get(p["slug"], 0) + 1
    title = {p["slug"]: p["title"] for p in pages}
    pages_of = lambda d: [{"slug": sl, "title": title[sl], "sentences": n} for sl, n in sorted(d.items(), key=lambda x: title[x[0]])]
    return {"slug": source_slug, "title": srcs[source_slug]["title"],
            "sections": [{"section": sec, "name": shown(sec, c), "pages": pages_of(by_sec[sec])} for sec in order if sec in by_sec],
            "unused": [{"section": sec, "name": shown(sec, c)} for sec in order if sec not in by_sec],
            "not_in_source": [{"label": k, "pages": [{"slug": sl, "title": title[sl]} for sl in sorted(v)]} for k, v in missing.items()]}
