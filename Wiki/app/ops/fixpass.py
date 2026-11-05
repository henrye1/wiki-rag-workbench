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
    chk = await citecheck.schema_checks(wiki_id)
    doc_names = checks.document_name_re(chk)
    return {"matchers": {r["slug"]: m for r in rows if (m := citecheck._matcher(r["text"], doc_names))}, "doc_names": doc_names,
            "checks": chk,
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
    text = citecheck.names_unlinked(text, ctx.get("doc_names"))[0]
    _, _, flagged = citecheck.check(text, ctx["matchers"], ctx.get("doc_names"), ctx.get("checks"))
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
    claim. may_grow is accepted for callers' sake: a rewrite's length is not limited."""
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
            out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(schema, prompts.fix_page_prompt(
                slug=slug, title=title, content_md=text or "(nothing yet)", failures=failures, linkable=linkable,
                source_paragraphs=sources_text or "(none)")), out_schema)
            new = parse(out["content_md"])
            after = check(new)
            lost = [] if may_shrink else sorted(c for c in checks.cites(text) - checks.cites(new) if clause(c))
            n_old, n_new = len(text.split()), len(new.split())
            keep = bool(new.strip()) and len(after) < len(failures) and not lost and ok(text, new)
            rec |= {"kept": keep, "fixed": len(failures) - len(after) if keep else 0, "still": after, "words": [n_old, n_new],
                    **({"lost_citations": lost} if lost else {})}
            if keep:
                text = new
            log.info("page %s %s check, round %s: %s failures, %s fixed, rewrite %s", slug, kind, rnd,
                     len(failures), len(failures) - len(after), "kept" if keep else "discarded")
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


PARA_FAILURE = re.compile(r"^Paragraph (.+?) (?:has lettered or numbered parts|states the condition)")  # checks.section_failures
SENTENCE_FAILURE = re.compile(r"^The sentence citing (.+?) \(\"")  # its opener, from checks.section_failures


def _failing_paragraphs(failures: list[str]) -> dict[str, list[str]]:
    """The paragraphs the failures name (a part, a condition or an opener missing from its write-up) -> its failures."""
    out: dict[str, list[str]] = {}
    for f in failures:
        if m := PARA_FAILURE.match(f):
            out.setdefault(m.group(1), []).append(f)
        elif (m := SENTENCE_FAILURE.match(f)) and "," not in m.group(1):  # a sentence citing one paragraph
            out.setdefault(re.sub(r"(?:\s*\([^)]*\))+$", "", m.group(1).strip()), []).append(f)
    return out


def _quote_failing(text: str, failures: list[str], check, quote, rounds: list) -> str:
    """The schema's last step after the two returns: each paragraph whose write-up still fails is written as its own
    words, quoted in full, with its opener and citation (quote: the page's text with that done, or None where it cannot
    be). Kept when that paragraph's failures go and nothing else starts failing. No AI call."""
    for ref, fails in _failing_paragraphs(failures).items():
        new = quote(text, ref)
        rec = {"round": "quote", "paragraph": ref, "failures": fails}
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
