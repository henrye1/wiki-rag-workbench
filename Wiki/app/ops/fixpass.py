"""The check-and-fix pass shared by ingest and re-check: check a page, send it back with the list of failures (at most
twice), keep a rewrite only when it is better, then quote in full what still fails. The words the checks look for come from the schema (wiki/checks.py)."""
import logging
import re
from uuid import UUID

from .. import llm, prompts
from ..db import get_pool
from ..wiki import checks, citecheck, store

log = logging.getLogger(__name__)
LABEL_RE = re.compile(r"^\[([^\]\n]+)\]", re.M)
SOURCE_SLUG = "source-"  # a source page's slug opens with this (the schema's Slugs and links: source-<source-name>)


async def cite_context(wiki_id: UUID, section_names: list[str]) -> dict:
    """What the citation checks compare against: each source's paragraph labels, and the wiki's own source and section
    names (a citation naming one of those cites no clause)."""
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, title, text, meta from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    names = set(section_names)
    for r in rows:
        names.add(r["title"])
        names.update(v for v in ((r["meta"] or {}).get("document") or {}).values() if v)
    texts = {r["slug"]: {} for r in rows}
    for r in rows:
        for b in re.split(r"\n\s*\n", r["text"] or ""):
            if m := LABEL_RE.match(b.strip()):
                texts[r["slug"]].setdefault(m.group(1), []).append(b.strip())
    doc_names = await citecheck.document_names(wiki_id)
    return {"matchers": {r["slug"]: m for r in rows if (m := citecheck._matcher(r["text"], doc_names))}, "doc_names": doc_names,
            "labels": {r["slug"]: set(LABEL_RE.findall(r["text"] or "")) for r in rows},
            "texts": {sl: {k: "\n\n".join(v) for k, v in t.items()} for sl, t in texts.items()},
            "titles": {r["slug"]: ((r["meta"] or {}).get("document") or {}).get("part") or r["title"] for r in rows},
            "names": names}


def normalise_labels(text: str, ctx: dict) -> str:
    """A citation whose label is not one its source holds, but ends with one it does ("<words> 6.5.8" ends with 6.5.8),
    is written with that label, as the schema's citation form is: the longest such ending, sub-paragraph letters kept.
    The labels are the source's own, in the schema's citation forms; no word is matched."""
    labels = ctx["labels"]
    bare = lambda x: re.sub(r"(?:\s*\([^)]*\))+$", "", x).strip()

    def fix(m):
        src, lab = m.group(1), (m.group(2) or "").strip()
        if src not in labels or not lab or lab in labels[src] or bare(lab) in labels[src]:
            return m.group(0)
        words = lab.split()
        for k in range(1, len(words)):
            cand = " ".join(words[k:])
            if cand in labels[src] or bare(cand) in labels[src]:
                return f"[[{src}|{cand}]]"
        return m.group(0)
    return store.LINK_RE.sub(fix, text)


def resolve_sources(text: str, ctx: dict, prefer: str | None = None) -> str:
    """A citation naming a source page the wiki does not have (a slug the writer made up) names the source that holds
    its label: the one preferred (the source being uploaded) where it holds it, else the only one that does. Left as it
    is where no source, or more than one, holds it."""
    labels = ctx["labels"]

    def fix(m):
        slug, lab = m.group(1), (m.group(2) or "").strip()
        if slug in labels or not lab or not slug.startswith(SOURCE_SLUG):
            return m.group(0)
        have = [sl for sl, labs in labels.items() if checks.is_location(lab, labs)]
        to = prefer if prefer in have else have[0] if len(have) == 1 else None
        return f"[[{to}|{lab}]]" if to else m.group(0)
    return store.LINK_RE.sub(fix, text)


def names_no_location(text: str, ctx: dict, chk: checks.Checks | None = None) -> str:
    """A source citation whose label is no location its source holds and has no clause number (the source naming
    itself, "this IFRS"; a heading's words) becomes its label as plain text: it is not a citation. A citation in one of
    the schema's citation forms (a defined term, an editorial note: their form's opening words), or with a number in
    its label, stays, for the citation checks to judge."""
    labels = ctx["labels"]
    forms = [chk.defined_term_form, *chk.unlabelled_forms.values()] if chk else []
    opens = [f.split("<", 1)[0] for f in forms if f and "<" in f and not f.startswith("<")]

    def one(m):
        slug, lab = m.group(1), (m.group(2) or "").strip()
        if slug not in labels or not lab or re.search(r"\d", lab) or checks.is_location(lab, labels[slug]) \
                or any(lab.casefold().startswith(o.casefold()) for o in opens):
            return m.group(0)
        return lab
    return store.LINK_RE.sub(one, text or "")


def is_clause(cite: str, ctx: dict) -> bool:
    """A citation (slug|clause) of a paragraph its source holds, not of a page, a name or a label the source lacks."""
    slug, _, label = cite.partition("|")
    return label in ctx["labels"].get(slug, set())


def earlier_cites(before: str, ctx: dict) -> set[str]:
    """The source paragraphs a page cited before it is rewritten (slug|clause): citations of a paragraph a source
    holds, not of a source's name."""
    return {c for c in checks.cites(before) if c.split("|", 1)[1] not in ctx["names"]
            and c.split("|", 1)[1] in ctx["labels"].get(c.split("|", 1)[0], set())}


def kept_failures(text: str, earlier: set[str]) -> list[str]:
    """The paragraphs a page cited before a rewrite that it no longer cites."""
    return [f"Before this rewrite the page cited paragraph {c.split('|', 1)[1]} of [[{c.split('|', 1)[0]}]]; it no "
            "longer does. Keep what the page said about it, with its citation." for c in sorted(earlier - checks.cites(text))]


WORD = re.compile(r"[a-z0-9][a-z0-9%.-]{2,}")
NOT_A_LABEL = re.compile(r"^The citation \[\[([^\]|]+)\|([^\]]+)\]\] does not name a paragraph")


def _words_of(text: str) -> set[str]:
    return set(WORD.findall(re.sub(r"\[\[[^\]]*\]\]|^\[[^\]\n]+\]", " ", text.casefold(), flags=re.M)))


def _where_it_rests(text: str, slug: str, label: str, ctx: dict) -> str:
    """For a citation of a location its source lacks (e.g. "Cover" in a paper with no text before its first heading):
    the source's location whose text shares the most words with the sentences that carry it, named so the fix can
    cite it. Empty when no location shares enough of their words."""
    cite = f"[[{slug}|{label}]]"
    said = set().union(*[_words_of(s) for line in text.split("\n") for s in checks.sentences(checks.BULLET.sub("", line))
                         if cite in s] or [set()])  # the sentence that carries it, cut as the page checks cut it
    if len(said) < 4:
        return ""
    best, score = "", 0
    for lab, body in ctx["texts"].get(slug, {}).items():
        n = len(said & _words_of(body))
        if n > score:
            best, score = lab, n
    if score < max(3, len(said) * 0.3):
        return ""
    return (f' This source has no location "{label}". The sentence rests on the passage under "{best}" ("'
            + " ".join(re.sub(r"^\[[^\]\n]+\]\s*", "", ctx["texts"][slug][best]).split()[:20]) + f' ..."): cite [[{slug}|{best}]].')


def cite_failures(text: str, ctx: dict, chk: checks.Checks | None) -> list[str]:
    """Citations the citation check would flag, and citations that cite something other than a clause. A citation of
    a location its source lacks names the location the sentence rests on, where one is clear. A citation that is only
    a document's name is not sent back: it is put back as plain text before the page is saved (citecheck.names_unlinked)."""
    text = names_no_location(citecheck.names_unlinked(text, ctx.get("doc_names"))[0], ctx, chk)
    _, _, flagged = citecheck.check(text, ctx["matchers"], ctx.get("doc_names"))
    out = [f'The citation [[{src}|{label}]] does not match a paragraph of that source ({reason}); cite the paragraph '
           "it states, by its own label." for (src, label, reason) in flagged]
    labels = [f + _where_it_rests(text, m.group(1), m.group(2), ctx) if (m := NOT_A_LABEL.match(f)) else f
              for f in checks.label_failures(text, ctx["labels"], chk)]
    return list(dict.fromkeys(out + checks.citation_failures(text, ctx["labels"], ctx["names"], chk) + labels))


def move_claims(slug: str, text: str, home, holds, record: list, names: set[str] = frozenset()) -> tuple[str, dict[str, list[str]]]:
    """A page the schema says holds no claims: each sentence on it that cites a source paragraph moves, word for word,
    to the page that holds that paragraph (home: slug|clause -> page slug, or None); where that page already cites it
    (holds: page slug -> its citations) the sentence is dropped. A sentence with no page to go to stays. Returns the
    page's text and, per page, the sentences to add to it."""
    clauses = lambda x: {c for c in checks.cites(x) if c.split("|", 1)[1] not in names}
    target = lambda x: next((t for t in map(home, sorted(clauses(x))) if t), None)
    found = checks.take_claims(text, names=names)[1]
    rest, taken = checks.take_claims(text, lambda x: target(x) is not None, names)
    moves: dict[str, list[str]] = {}
    for x in taken:
        if not clauses(x) <= holds(target(x)):
            moves.setdefault(target(x), []).append(x)
    stayed = [x for x in found if x not in taken]
    if found:
        record.append({"page": slug, "kind": "no claims", "found": len(found), "still": len(stayed),
                       "moved": {t: len(xs) for t, xs in moves.items()},
                       "dropped_already_there": len(taken) - sum(map(len, moves.values())),
                       "stayed": [" ".join(x.split()[:20]) for x in stayed]})
        log.info("page %s holds no claims: %s found, %s moved, %s already on their page, %s stayed", slug, len(found),
                 sum(map(len, moves.values())), len(taken) - sum(map(len, moves.values())), len(stayed))
    return rest, moves


async def fix_rounds(*, schema: str, slug: str, title: str, text: str, check, sources_text: str, linkable: str, parse,
                     kind: str, record: list, out_schema=prompts.PAGE_SCHEMA, ok=lambda old, new: True,
                     may_shrink: bool = False, may_grow: bool = False, clause=lambda cite: True, quote=None) -> str:
    """Check the page; if anything fails, send it back with the list, at most twice. A rewrite is kept when it has fewer
    failures, loses no citation of a source paragraph (clause tells one from a broken link, which a fix may repair;
    may_shrink when a failure asks for something to be taken out) and passes ok. A paragraph whose write-up still fails
    after the second return is then quoted in full (quote, where the caller gives one): the quote itself becomes the
    claim. may_grow is accepted for callers' sake: a rewrite's length is not limited. sources_text: the source text the
    writer is shown, or a function of the page's text and its failures giving it (a paragraph a failure names as well as
    the page's own)."""
    shown = sources_text if callable(sources_text) else (lambda x, fails: sources_text)
    rounds = []
    initial = check(text)
    if any(f.startswith(checks.REPEAT) for f in initial):  # the same text twice: its later copies go, word for word
        text, n = checks.drop_repeats(text)
        rounds.append({"round": "repeats", "failures": [f for f in check(text) if f.startswith(checks.REPEAT)] or ["repeats"],
                       "kept": True, "fixed": n, "still": [f for f in check(text) if f.startswith(checks.REPEAT)]})
    for rnd in (1, 2):
        failures = check(text)
        if not failures:
            break
        rec = {"round": rnd, "failures": failures}
        try:
            # the paragraphs (blocks) of the page the failures name are rewritten, each on its own; what names no
            # paragraph (a failure of the page as a whole) is sent back with the whole page, as before
            text, rec_blocks = await _fix_blocks(schema=schema, slug=slug, title=title, text=text, failures=failures,
                                                 check=check, shown=shown, linkable=linkable, parse=parse,
                                                 out_schema=out_schema, ok=ok, may_shrink=may_shrink, clause=clause)
            rec |= rec_blocks
            if rest := [f for f in check(text) if f in rec_blocks.get("unplaced", [])]:
                out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(schema, prompts.fix_page_prompt(
                    slug=slug, title=title, content_md=text or "(nothing yet)", failures=rest, linkable=linkable,
                    source_paragraphs=shown(text, rest) or "(none)")), out_schema)
                before = check(text)
                new = parse(out["content_md"])
                after = check(new)
                lost = [] if may_shrink else sorted(c for c in checks.cites(text) - checks.cites(new) if clause(c))
                keep = bool(new.strip()) and len(after) < len(before) and not lost and ok(text, new)
                rec["page"] = {"kept": keep, "failures": len(rest), "words": [len(text.split()), len(new.split())],
                               **({"lost_citations": lost} if lost else {})}
                if keep:
                    text = new
            after = check(text)
            rec |= {"kept": len(after) < len(failures), "fixed": max(len(failures) - len(after), 0), "still": after}
            log.info("page %s %s check, round %s: %s failures, %s paragraphs rewritten, %s kept, %s left", slug, kind, rnd,
                     len(failures), rec.get("paragraphs", 0), rec.get("paragraphs_kept", 0), len(after))
        except Exception as e:
            log.warning("page %s %s check, round %s failed: %s", slug, kind, rnd, e)
            rec["error"] = f"{type(e).__name__}: {e}"
        rounds.append(rec)
    if rounds and quote and (left := check(text)):  # still failing after the two returns: the quote becomes the claim
        text = _quote_failing(text, left, check, quote, rounds)
    if rounds:
        left = check(text)
        record.append({"page": slug, "kind": kind, "found": len(initial), "still": len(left), "left": left,
                       "rounds": rounds})
    return text


BLOCKS = re.compile(r"\n\s*\n")
SAID = re.compile(r'\("(.+?)\.\.\."\)')  # checks.section_failures: the opening words of the sentence that fails
QUOTED_TEXT = re.compile(r'"([^"\n]{15,}?)(?: \.\.\.)?"')  # any other failure quoting the page's text


def failure_blocks(blocks: list[str], failure: str) -> set[int]:
    """The paragraphs (blocks) of a page a failure is about: the one holding the sentence it quotes, the ones holding a
    citation it names, or, for a paragraph's lettered parts or conditions, the ones whose closing citations name that
    paragraph (of the source the failure names). None where the failure names no place on the page."""
    if (m := SAID.search(failure)) and (got := {i for i, b in enumerate(blocks) if m.group(1) in b}):
        return got  # (a quote that is not the page's, such as a source passage a suggestion quotes, falls through)
    if m := PARA_FAILURE.match(failure):
        base = lambda x: re.sub(r"(?:\s*\([^)]*\))+$", "", x.strip())
        return {i for i, b in enumerate(blocks) for c in checks.closing_links(b)
                if c.group(2) and base(c.group(2)) == m.group(1) and (m.group(2) is None or c.group(1) == m.group(2))}
    links = set(re.findall(r"\[\[[^\]]+\]\]", failure))
    if links and (got := {i for i, b in enumerate(blocks) if any(x in b for x in links)}):
        return got
    return {i for i, b in enumerate(blocks) for q in QUOTED_TEXT.findall(failure) if q in b}


LOST_ITEMS = re.compile(r"; ([^;]*?) do not appear on the page\.$|states the condition\(s\) (.+?), which")


def _failure_key(f: str) -> tuple[str, int]:
    """A failure as what it is about and how much it finds missing: a paragraph's parts or conditions (its label,
    source and kind of check; the number of items left out), else the failure itself (one)."""
    if (m := PARA_FAILURE.match(f)) and (n := LOST_ITEMS.search(f)):
        what = "parts" if n.group(1) is not None else "conditions"
        return f"{m.group(1)}|{m.group(2)}|{what}", len((n.group(1) or n.group(2)).split(","))
    return f, 1


def _worse(before: list[str], after: list[str], shared: set[str]) -> bool:
    """Whether a paragraph's rewrite makes the page worse: a failure that was not there before, or a failure it shares
    with other paragraphs (shared) now finding more missing. A shared failure that finds less missing, or the same, is
    not worse; one that is gone is better."""
    was = {}
    for f in before:
        k, n = _failure_key(f)
        was[k] = max(was.get(k, 0), n)
    shared_keys = {_failure_key(f)[0] for f in shared}
    for f in after:
        k, n = _failure_key(f)
        if k not in was or (k in shared_keys and n > was[k]) or (k not in shared_keys and f not in before):
            return True
    return False


def _for_part(sources: str, part: str, fails: list[str]) -> str:
    """Of the source text a page is shown, the passages one paragraph of it needs: those it cites and those its failures
    name (all of it where none of them is there)."""
    base = lambda x: re.sub(r"(?:\s*\([^)]*\))+$", "", x.strip())
    want = {base(c.split("|", 1)[1]) for c in checks.cites(part)} | {lab for lab, _ in named_paragraphs(fails)} | {
        lab for lab, _ in _failing_paragraphs(fails)}
    got = [b for b in BLOCKS.split(sources or "") if (m := LABEL_RE.match(b.strip())) and base(m.group(1)) in want]
    return "\n\n".join(got) if got else sources


async def _fix_blocks(*, schema, slug, title, text, failures, check, shown, linkable, parse, out_schema, ok, may_shrink,
                      clause) -> tuple[str, dict]:
    """One fix round, paragraph by paragraph: each paragraph a failure names is sent back on its own with its failures.
    A paragraph's rewrite is kept when its own failures are gone, nothing else starts failing, it loses no citation of
    a source paragraph and the page passes ok. Returns the page and the round's record; "unplaced": the failures that
    name no paragraph."""
    blocks = [b for b in BLOCKS.split(text or "") if b.strip()]
    mine: dict[int, list[str]] = {}
    unplaced = []
    for f in failures:
        at = failure_blocks(blocks, f)
        if not at:
            unplaced.append(f)
        for i in at:
            mine.setdefault(i, []).append(f)
    if not mine:
        return text, {"unplaced": unplaced}

    async def one(i: int):
        try:
            out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(schema, prompts.fix_part_prompt(
                slug=slug, title=title, part_md=blocks[i], failures=mine[i], linkable=linkable,
                source_paragraphs=_for_part(shown(blocks[i], mine[i]), blocks[i], mine[i]) or "(none)")), out_schema)
            return i, parse(out["content_md"])
        except Exception as e:
            log.warning("page %s: rewrite of a paragraph failed: %s", slug, e)
            return i, None

    kept = 0
    now = check(text)
    shared = {f for f in failures if sum(f in fs for fs in mine.values()) > 1}  # failures pointing to several paragraphs
    for i, new in sorted(await llm.gather_limited(one(i) for i in mine)):
        if not new or not new.strip():
            continue
        trial = blocks[:i] + [new.strip()] + blocks[i + 1:]
        cand = "\n\n".join(trial)
        after = check(cand)
        lost = [] if may_shrink else [c for c in checks.cites(blocks[i]) - checks.cites(new) if clause(c)]
        own = set(mine[i]) - shared
        if not (own & set(after)) and not _worse(now, after, shared) and not lost and ok("\n\n".join(blocks), cand):
            blocks, now, kept = trial, after, kept + 1
    return "\n\n".join(blocks), {"paragraphs": len(mine), "paragraphs_kept": kept, "unplaced": unplaced}


OF_SOURCE = r"(?: of \[\[([^\]|]+)\]\])?"  # checks.section_failures names the paragraph's source after its label
PARA_FAILURE = re.compile(r"^Paragraph (.+?)" + OF_SOURCE + r" (?:has lettered or numbered parts|states the condition)")
SENTENCE_FAILURE = re.compile(r"^The sentence citing (.+?)" + OF_SOURCE + r" \(\"")  # its opener, from checks.section_failures


def named_paragraphs(failures: list[str]) -> set[tuple[str, str | None]]:
    """The paragraphs the sentence failures name, each as (label, its source): what the sentence cites."""
    out = set()
    for f in failures:
        if m := SENTENCE_FAILURE.match(f):
            out |= {(re.sub(r"(?:\s*\([^)]*\))+$", "", x.strip()), m.group(2)) for x in m.group(1).split(",")}
    return out


def _failing_paragraphs(failures: list[str]) -> dict[tuple[str, str | None], list[str]]:
    """The paragraphs the failures name (a part, a condition or an opener missing from its write-up), each as (label,
    its source) -> its failures."""
    out: dict[tuple[str, str | None], list[str]] = {}
    for f in failures:
        if m := PARA_FAILURE.match(f):
            out.setdefault((m.group(1), m.group(2)), []).append(f)
        elif (m := SENTENCE_FAILURE.match(f)) and len(labs := {re.sub(r"(?:\s*\([^)]*\))+$", "", x.strip())
                                                           for x in m.group(1).split(",")}) == 1:  # one paragraph
            out.setdefault((labs.pop(), m.group(2)), []).append(f)
    return out


def _quote_failing(text: str, failures: list[str], check, quote, rounds: list) -> str:
    """The schema's last step after the two returns: each paragraph whose write-up still fails is written as its own
    words, quoted in full, with its opener and citation (quote: the page's text with that done, or None where it cannot
    be; quote(text, label, source, failures): the source as the failures name it, and the failures, which tell which of
    the label's passages fails). Kept when that paragraph's failures go and nothing else starts failing. No AI call."""
    for (ref, src), fails in _failing_paragraphs(failures).items():
        new = quote(text, ref, src, fails)
        rec = {"round": "quote", "paragraph": ref, "source": src, "failures": fails}
        if new is None:
            rounds.append(rec | {"kept": False, "reason": "no quote could be written for it"})
            continue
        before, after = check(text), check(new)
        keep = not (set(fails) & set(after)) and not (set(after) - set(before))
        rec |= {"kept": keep, "fixed": len(before) - len(after) if keep else 0, "still": after}
        if keep:
            text = new
        log.info("page: paragraph %s quoted in full: %s", ref, "kept" if keep else "discarded")
        rounds.append(rec)
    return text
