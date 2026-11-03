"""Page checks after writing. Every word they look for is read from the wiki schema's "## Checks" section; this module
holds only the mechanics (find a citation, look for the schema's words near it, compare with the source paragraph).

A list the schema does not give switches its check off (the caller logs it); nothing here supplies a default.
"""
import re
from dataclasses import dataclass, field

from . import store

QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]+)[\"\u201d]")
SECTION = re.compile(r"^## Checks\s*$(.*?)(?=^## |\Z)", re.M | re.S)
ITEM = re.compile(r"^- ([^:\n]+):\s*(.+)$", re.M)
_flat = lambda x: " ".join(re.sub(r"[\u2018\u2019\u201c\u201d\"']", "", x).split()).casefold()
_words = lambda x: " ".join(re.findall(r"\w+", store.LINK_RE.sub(" ", x).casefold()))  # links and punctuation aside


@dataclass
class Checks:
    kinds: dict[str, str] = field(default_factory=dict)  # reader's paragraph kind -> the schema's name for it
    openers: dict[str, list[str]] = field(default_factory=dict)  # schema's kind name -> its openers
    linking: list[str] = field(default_factory=list)
    lead_in_words: int | None = None  # any lead-in of up to this many words ending in a comma may come before an opener
    part_forms: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    authority: list[str] = field(default_factory=list)
    source_parts: dict[str, str] = field(default_factory=dict)  # part as the schema names it -> what is checked
    max_takeaways: int | None = None
    examples_section: int | None = None  # the section the issuer's labelled examples are routed to
    example_labels: list[str] = field(default_factory=list)
    routed_kinds: list[str] = field(default_factory=list)  # the schema's kind names routed to the examples section
    split: dict[int, str] = field(default_factory=dict)  # section number -> what its subtopic pages are grouped by
    defined_term_form: str = ""  # how a defined term is cited, e.g. a prefix followed by <term>
    page_size_limit: int | None = None  # words: a section page over this is split by the source's headings
    resplit_margin: float = 0.0  # after writing, a page is split again only if this share (0.1 = 10%) over the limit
    subtopic_minimum: int | None = None  # words: a smaller group is joined to its neighbour under the same parent
    join_related: bool = False  # a small group joins its most related group under the same parent, not the one before
    slug_words: int | None = None  # words of an unnumbered heading used in a subtopic slug
    slug_main: bool = False  # a page holding several headings takes its slug from the one holding most of its words
    guidance_kinds: list[str] = field(default_factory=list)  # the schema's kind names filed with their requirement
    summary_heads: int | None = None  # a subtopic summary: the first requirement claim under this many largest headings
    summary_lead: str = ""  # a subtopic summary opens with this, then the source headings its title does not name
    summary_sep: str = ""  # between those headings
    summary_max: int | None = None  # characters: a subtopic summary is no longer, headings first
    page_summary: bool = False  # every other page's summary: what it holds (terms, listed lines, sections, headings)
    page_summary_lead: str = ""  # it opens with this
    page_summary_sep: str = ""  # between those items
    page_summary_max: int | None = None  # characters: no longer, items first
    unlabelled_forms: dict[str, str] = field(default_factory=dict)  # kind of text without a paragraph label -> its citation form
    no_claim_pages: list[str] = field(default_factory=list)  # pages that hold no claims: slugs, or a kind of page
    no_claim_index: bool = False  # the list names a split section's index page among them
    stub_forms: list[str] = field(default_factory=list)  # what a deleted or left-out paragraph says instead of its text
    skipped_headings: list[str] = field(default_factory=list)  # a passage under one of these is skipped like a stub
    document_names: list[str] = field(default_factory=list)  # forms of a document's name, never a clause in a citation
    control_headers: list[str] = field(default_factory=list)  # header words that mark a document control table
    empty_text: str = ""  # the whole body of a section page that holds no claims
    absence: list[str] = field(default_factory=list)  # phrases that say something is not stated
    absence_allowed: str = ""  # where those phrases are allowed, as the schema's label says it ("... source page ...")
    papers_apart: bool = False  # a page keeps each paper's text under its own headings; a split stays within one paper
    overview_empty: str = ""  # the word the overview lists a section with when its page holds no claims
    section_slug: str = ""  # the pattern a section page's slug is built from, e.g. <nn>-<section name>
    kinds_left_out: list[str] | None = None  # reader kinds never stored or written up (None: the schema has no such list)
    range_ends: bool = False  # a citation of a range cites only the two paragraphs it names
    also_recorded: dict[int, str] = field(default_factory=dict)  # section number -> what is also recorded on its page
    concept_terms: bool = False  # a concept page for each defined term
    concept_heading_pages: int | None = None  # a concept page for each major heading whose lines sit on this many pages
    concept_line: str = ""  # a concept line's form, its placeholders in order: citation, source heading, page, title
    concept_defined: str = ""  # a term's page opens with this line, its placeholders: the terms page, the citation
    concept_match: dict = field(default_factory=dict)  # how a term is found in a sentence
    concept_slug: str = ""  # a concept page's slug pattern, e.g. <framework>-concept-<term>
    concept_slug_words: int | None = None  # words of an unnumbered heading used in its concept slug
    concept_summary_lead: str = ""
    concept_summary_sep: str = ""
    concept_summary_max: int | None = None
    missing: list[str] = field(default_factory=list)  # lists the schema does not give: their checks are off


LISTS = {  # attribute -> how the schema names the list (its label up to the first word that differs)
    "kinds": "paragraph kinds", "openers": "openers", "linking": "linking words", "part_forms": "lettered part forms",
    "conditions": "condition phrases", "authority": "authority forms", "source_parts": "source-page parts",
    "max_takeaways": "key takeaways", "examples_section": "examples section", "example_labels": "example labels",
    "routed_kinds": "kinds routed to the examples section", "split": "split sections",
    "defined_term_form": "defined-term citation form",
    "unlabelled_forms": "citation forms for text without a paragraph label", "page_size_limit": "page size limit",
    "subtopic_minimum": "subtopic page minimum", "slug_words": "subtopic slug", "no_claim_pages": "pages that hold no claims",
    "stub_forms": "stub forms", "skipped_headings": "skipped headings", "document_names": "document names", "control_headers": "document control headers",
    "empty_text": "empty section text", "absence": "absence phrases", "papers_apart": "papers kept apart",
    "overview_empty": "overview lines", "section_slug": "section slug",
    "guidance_kinds": "guidance filed with its requirement", "summary_heads": "subtopic summary",
    "join_related": "subtopic join", "slug_main": "joined subtopic slug", "page_summary": "page summary",
    "kinds_left_out": "kinds left out", "range_ends": "range citations", "also_recorded": "also recorded",
    "concept_terms": "concept pages", "concept_line": "concept lines", "concept_match": "concept term match",
    "concept_slug": "concept slug", "concept_summary_lead": "concept summary",
}
PLACEHOLDER = re.compile(r"<[^<>]+>")


NUMBER_WORDS = {w: n for n, w in enumerate("one two three four five six seven eight nine ten".split(), start=1)}


def _mapping(value: str) -> dict[str, str]:
    """ "a = x; b = y" -> {a: x, b: y} """
    out = {}
    for item in value.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip().strip('"').casefold()] = v.strip()
    return out


def load(schema_md: str) -> Checks | None:
    """The schema's Checks section, or None when it has none."""
    m = SECTION.search(schema_md or "")
    if not m:
        return None
    items = {k.strip().casefold(): v for k, v in ITEM.findall(m.group(1))}
    get = lambda label: next((v for k, v in items.items() if k.startswith(label)), None)
    label_of = lambda label: next((k for k in items if k.startswith(label)), "")
    c = Checks()
    for attr, label in LISTS.items():
        value = get(label)
        if value is None:
            c.missing.append(label)
            continue
        if attr == "kinds":
            c.kinds = {k: v.strip().strip('"').casefold() for k, v in _mapping(value).items()}
        elif attr == "openers":
            c.openers = {k: QUOTED.findall(v) for k, v in _mapping(value).items()}
        elif attr == "source_parts":
            c.source_parts = {k: v.casefold() for k, v in _mapping(value).items()}
        elif attr == "unlabelled_forms":
            c.unlabelled_forms = {k: (QUOTED.findall(v) or [v.strip()])[0] for k, v in _mapping(value).items()}
        elif attr == "defined_term_form":
            c.defined_term_form = (QUOTED.findall(value) or [""])[0]
        elif attr == "split":
            c.split = {int(k): re.split(r"\.\s+(?=[A-Z])", v, maxsplit=1)[0] for k, v in _mapping(value).items()
                       if k.strip().isdigit()}  # each up to the sentence after the list
        elif attr == "routed_kinds":
            c.routed_kinds = [x.strip().strip('"').casefold() for x in value.split(",") if x.strip()]
        elif attr == "linking":
            c.linking = QUOTED.findall(value)
            if m := re.search(r"\bup to (\w+) words?\b", value):
                c.lead_in_words = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1).casefold())
        elif attr == "control_headers":  # "a · b · c" (or quoted words)
            c.control_headers = QUOTED.findall(value) or [x.strip() for x in value.split("\u00b7") if x.strip()]
        elif attr in ("stub_forms", "skipped_headings"):  # "a · b · c. What is done with them.": up to the sentence after
            forms = [x.strip() for x in value.split("\u00b7")]
            forms[-1] = re.split(r"\.\s+(?=[A-Z])", forms[-1], maxsplit=1)[0]
            setattr(c, attr, [x for x in forms if x])
        elif attr == "empty_text":
            c.empty_text = (QUOTED.findall(value) or [""])[0]
        elif attr == "absence":  # the phrases; where they are allowed is in the label's brackets
            c.absence = QUOTED.findall(value)
            c.absence_allowed = (re.findall(r"\(([^)]*)\)", label_of(label)) or [""])[0]
        elif attr == "papers_apart":
            c.papers_apart = True
        elif attr == "overview_empty":  # "... a link to the section's page if it holds claims, or the word "Empty" ..."
            c.overview_empty = (QUOTED.findall(value) or [""])[0]
        elif attr == "section_slug":
            c.section_slug = value.strip()
        elif attr == "no_claim_pages":  # up to the first full stop: page slugs, and kinds of page such as index pages
            c.no_claim_pages = [x.strip() for x in value.split(".")[0].split(",") if x.strip()]
            c.no_claim_index = any(re.search(r"\bindex\b", x, re.I) for x in c.no_claim_pages)
        elif attr in ("join_related", "slug_main"):  # a setting: on only with the schema's value for it
            setattr(c, attr, value.strip().rstrip(".").casefold() == {"join_related": "most related", "slug_main": "largest heading"}[attr])
        elif attr == "guidance_kinds":  # "a, b. What is done with them.": the kind names up to the first full stop
            c.guidance_kinds = [x.strip().casefold() for x in value.split(".")[0].split(",") if x.strip()]
        elif attr in ("max_takeaways", "examples_section", "page_size_limit", "subtopic_minimum", "slug_words", "summary_heads"):
            n = re.search(r"\d+", value)
            setattr(c, attr, int(n.group(0)) if n else None)
            if attr == "page_size_limit" and (m := re.search(r"(\d+(?:\.\d+)?)\s*%\s+over", value)):
                c.resplit_margin = float(m.group(1)) / 100
            if attr == "summary_heads":  # "<lead>" ... headings ... separated by "<sep>"; at most <n> characters
                quoted = QUOTED.findall(value)
                c.summary_lead, c.summary_sep = (quoted + ["", ""])[:2] if len(quoted) >= 2 else ("", "")
                n = re.search(r"\bat most (\d+) characters\b", value, re.I)
                c.summary_max = int(n.group(1)) if n else None
        elif attr == "kinds_left_out":  # "a, b": the reader's kind names, up to the first full stop
            c.kinds_left_out = [x.strip().strip('"') for x in value.split(".")[0].split(",") if x.strip()]
        elif attr == "range_ends":
            c.range_ends = bool(re.search(r"\bonly the two\b", value))
        elif attr == "also_recorded":  # "11 = what; 02 = what": section number -> what is also recorded there
            c.also_recorded = {int(k): v.strip().rstrip(".") for k, v in _mapping(value).items() if k.strip().isdigit()}
        elif attr == "concept_terms":  # each defined term; each major heading "... where its lines sit on at least <n> pages"
            c.concept_terms = bool(re.search(r"\bdefined term\b", value, re.I))
            n = re.search(r"\bat least (\d+) pages\b", value)
            c.concept_heading_pages = int(n.group(1)) if n and re.search(r"\bmajor heading\b", value, re.I) else None
        elif attr == "concept_line":  # "... written <form>, under ..."; a term's page "...: <defined line>."
            if m := re.search(r"\bwritten (.+?\]\]),", value):
                c.concept_line = m.group(1)
            if m := re.search(r"definition:\s*(.+?)\.?$", value):
                c.concept_defined = m.group(1).strip()
        elif attr == "concept_match":
            c.concept_match = {"words": bool(re.search(r"\bwhole words\b", value)), "case": not re.search(r"\bignoring case\b", value),
                               "longest": bool(re.search(r"\blongest\b", value)), "endings": QUOTED.findall(value)}
        elif attr == "concept_slug":  # "<pattern>; for a heading ... otherwise its first <n> words"
            c.concept_slug = value.split(";")[0].strip()
            n = re.search(r"\bfirst (\d+) words\b", value)
            c.concept_slug_words = int(n.group(1)) if n else None
        elif attr == "concept_summary_lead":  # "<lead>" ... separated by "<sep>". At most <n> characters
            quoted = QUOTED.findall(value)
            c.concept_summary_lead, c.concept_summary_sep = (quoted + ["", ""])[:2] if len(quoted) >= 2 else ("", "")
            n = re.search(r"\bat most ([\d,]+) characters\b", value, re.I)
            c.concept_summary_max = int(n.group(1).replace(",", "")) if n else None
        elif attr == "page_summary":  # "<lead>" ... items ... separated by "<sep>"; at most <n> characters
            quoted = QUOTED.findall(value)
            c.page_summary_lead, c.page_summary_sep = (quoted + ["", ""])[:2] if len(quoted) >= 2 else ("", "")
            n = re.search(r"\bat most ([\d,]+) characters\b", value, re.I)
            c.page_summary_max = int(n.group(1).replace(",", "")) if n else None
            c.page_summary = bool(c.page_summary_lead)

        else:
            setattr(c, attr, QUOTED.findall(value))
    return c


NUMBER = r"(?:\d+[A-Z]?|[A-Z])"  # the schema's <n>: a number or a letter
LIST_LABEL = re.compile(r"^[^*:\n\[]{1,80}\*\*\s*[:\u2013\u2014-]\s*")  # a bold list label before the sentence itself


def _template(text: str, wild: str, named: dict[str, str] | None = None) -> str:
    """A schema phrase as a pattern: <n> matches a number or a letter; a placeholder naming one of the Checks lists
    (<example label>: any of the Example labels) matches any item of that list; other "<...>" placeholders and "..."
    match any short run of words."""
    out = re.escape(text)
    pick = lambda name: NUMBER if name == "n" else (named or {}).get(name.replace("\\ ", " ").casefold(), wild)
    out = re.sub(r"<([^>]*)>", lambda m: f"({pick(m.group(1))})", out.replace(r"\<", "<").replace(r"\>", ">"))
    return out.replace(re.escape("..."), r".+?")


def _named(c: Checks) -> dict[str, str]:
    """The Checks lists of phrases a placeholder can name, by the singular of the list's name ("example labels" ->
    "example label"), each as one pattern of its items."""
    out = {}
    for attr, label in LISTS.items():
        items = getattr(c, attr, None)
        if label.endswith("s") and isinstance(items, list) and items and all(isinstance(x, str) for x in items):
            pats = (_template(x, r"[^,.\]\n]{1,60}?").replace(r"\ ", r"\s+") for x in items)
            out[label[:-1]] = "(?:" + "|".join(re.sub(r"\((?!\?)", "(?:", x) for x in pats) + ")"  # one group: the whole item
    return out


def _opener_res(c: Checks) -> dict[str, re.Pattern]:
    link = "|".join(map(re.escape, c.linking))
    leads = ([rf"(?:{link})\s+"] if link else []) + (  # the listed words, or any lead-in of up to n words and a comma
        [rf"(?:[^\s,.;:\[\]]+\s+){{0,{c.lead_in_words - 1}}}[^\s,.;:\[\]]+,\s+"] if c.lead_in_words else [])
    lead = f"(?:{'|'.join(leads)})?" if leads else ""
    named = _named(c)
    return {kind: re.compile(rf"^{lead}(?:" + "|".join(_template(o, r"[^,.\]\n]{1,150}?", named) for o in ops) + r")", re.I)
            for kind, ops in c.openers.items() if ops}


ROMAN = r"(?=[ivxlcdm])m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"


def _series(token: str) -> str:
    """What one of the schema's part forms stands for: "i" a roman numeral (i, ii, iv, ...), another letter a letter of
    the alphabet (a, b, ... aa), digits a number; upper case for an upper-case form."""
    if token.isdigit():
        return r"\d{1,3}"
    if token.lower() == "i":
        return ROMAN.upper() if token.isupper() else ROMAN
    return (r"[A-Z]{1,2}" if token.isupper() else r"[a-z]{1,2}") if len(token) == 1 else re.escape(token)


def _part_re(c: Checks) -> re.Pattern | None:
    """The schema's lettered-part forms ("(a)", "(i)") as one pattern: each form stands for its series (letters,
    roman numerals, numbers), so a word in brackets is not a part."""
    if not c.part_forms:
        return None
    pats = {re.sub(r"\\?[A-Za-z]+|\d+", lambda m: _series(m.group(0).lstrip("\\")), re.escape(f)) for f in c.part_forms}
    return re.compile(r"(?:^|(?<=[\s:;\u2013\u2014]))(" + "|".join(sorted(pats)) + r")(?=\s)")


def stub_re(c: Checks | None) -> re.Pattern | None:
    """The schema's stub forms as one pattern: "<...>" and "..." stand for any words inside the note, and a form that
    closes a bracket runs to that bracket (a form "[A ... B]" also matches "[A ... B and more.]")."""
    if not c or not c.stub_forms:
        return None
    pats = []
    for f in c.stub_forms:
        closes = f.endswith("]")
        pat = _template(f[:-1] if closes else f, r"[^\[\]]{0,400}?").replace(r"\ ", r"\s+")
        pats.append(pat + (r"[^\[\]]{0,200}?\]" if closes else ""))
    return re.compile("(?:" + "|".join(pats) + ")", re.I)


LABEL_TOKEN = re.compile(r"\S*\d\S*")  # a paragraph number or a range of them (30A–30C)


def is_stub(text: str, c: Checks | None) -> bool:
    """A paragraph (or lettered part) that says only one of the schema's stub forms: nothing to write up or check."""
    rx = stub_re(c)
    body = re.sub(r"^\[[^\]]+\]\s*(?:\([^)]*\)\s*)?", "", text.strip())  # its label, and a kind such as (example)
    if not rx or not rx.search(body):
        return False
    return not re.search(r"[A-Za-z]{3,}", LABEL_TOKEN.sub(" ", rx.sub(" ", body)))


def is_skipped(text: str, path: list[str], c: Checks | None) -> bool:
    """A passage not written up and not checked: a stub, or under one of the schema's skipped headings (any heading on
    its path, matched whole, case aside)."""
    heads = {h.casefold() for h in (c.skipped_headings if c else [])}
    return is_stub(text, c) or any(h.strip().casefold() in heads for h in path)


def document_name_re(c: Checks | None) -> re.Pattern | None:
    """The schema's document names ("IFRS <n>") as one pattern: a name, not a clause, inside a citation label."""
    if not c or not c.document_names:
        return None
    return re.compile(r"\b(?:" + "|".join(_template(x, NUMBER).replace(r"\ ", r"\s*") for x in c.document_names) + r")\b")


def example_item(path: list[str], text: str, c: Checks | None) -> str | None:
    """The labelled example a paragraph belongs to: the outermost heading on its path that carries one of the schema's
    example labels (the example's title, over its scenarios), else the first label in its own text."""
    rx = example_label_re(c) if c else None
    if not rx:
        return None
    for h in path:
        if m := rx.search(h):
            return m.group(0)
    m = rx.search(re.sub(r"^\[[^\]]+\]\s*", "", text))
    return m.group(0) if m else None


def footnote_form(c: Checks | None) -> str | None:
    """How the schema cites a footnote: the citation form for text without a paragraph label of the kind the schema
    names the reader's footnotes (e.g. editorial note = "ED:<clause>")."""
    return (c.unlabelled_forms.get(c.kinds.get("footnote", "")) or None) if c else None


def label_forms(c: Checks | None) -> dict[str, str]:
    """Each reader kind the schema cites in a form of its own when printed without a paragraph label (e.g. note ->
    "ED:<clause>", intro -> "<page label>")."""
    return {k: f for k, v in (c.kinds.items() if c else []) if (f := c.unlabelled_forms.get(v))}


def example_label_re(c: Checks) -> re.Pattern | None:
    """The schema's example labels ("Example <n>") as one pattern; <n> stands for a number or a capital letter."""
    if not c.example_labels:
        return None
    pats = [re.escape(x).replace(re.escape("<n>"), "<n>").replace("<n>", NUMBER) for x in c.example_labels]
    return re.compile(r"\b(?:" + "|".join(p.replace(r"\ ", r"\s+") for p in pats) + r")\b")


def routed_to_examples(c: Checks | None, reader_kind: str) -> bool:
    """Whether the schema routes paragraphs of this reader kind to the examples section."""
    return bool(c and reader_kind and c.kinds.get(reader_kind) in c.routed_kinds)


def cites(text: str) -> set[str]:
    """The source citations on a page, as slug|clause (sub-paragraph letters aside: 5.5.17(a) is a citation of 5.5.17)."""
    return {f"{m.group(1)}|{re.sub(r'(?:\s*\([^)]*\))+$', '', m.group(2).strip())}" for m in store.LINK_RE.finditer(text)
            if m.group(1).startswith("source-") and m.group(2)}


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
# a line break the reply left out: a sentence's end run straight into the next ("in progress.The document"), outside a link
SENTENCE_RUN_ON = re.compile(r"(?<=[a-z0-9)][.!?])(?=[A-Z][a-z])(?![^\[\n]*\]\])")
BULLET = re.compile(r"^(\s*(?:[-*]|\d+\.)\s+)")


def _is_claim(sentence: str, names: set[str] = frozenset()) -> bool:
    """A sentence citing a source paragraph: a source link with a clause, not with the source's own name."""
    return any(m.group(1).startswith("source-") and m.group(2) and m.group(2).strip() not in names
               for m in store.LINK_RE.finditer(sentence))


def take_claims(text: str, movable=lambda sentence: True, names: set[str] = frozenset()) -> tuple[str, list[str]]:
    """A page's text without the sentences that cite a source paragraph (those movable allows), and those sentences.
    A sentence that also links a wiki page (a section listed with what it covers) stays, without its source citations.
    A line left with no words is dropped, and so is a heading left with nothing under it. names: the wiki's source and
    section names, which a link may show in place of a clause."""
    lines, taken = [], []
    is_claim = lambda x: _is_claim(x, names)
    take = lambda x: is_claim(x) and movable(x.strip())
    navigates = lambda x: any(not m.group(1).startswith("source-") for m in store.LINK_RE.finditer(x))
    uncited = lambda x: re.sub(r"\s+([.,;:])", r"\1", store.LINK_RE.sub(
        lambda m: "" if m.group(1).startswith("source-") and m.group(2) and m.group(2).strip() not in names else m.group(0), x)).strip()
    for line in text.split("\n"):
        if re.match(r"^#{1,6} ", line) or not is_claim(line):
            lines.append(line)
            continue
        lead = (BULLET.match(line) or [""])[0]
        parts = SENTENCE_END.split(line[len(lead):])
        taken += [x.strip() for x in parts if take(x)]
        rest = " ".join(uncited(x) if take(x) and navigates(x) else x for x in parts if not take(x) or navigates(x)).strip()
        if re.search(r"[A-Za-z]", store.LINK_RE.sub("x", rest)):
            lines.append(lead + rest)
    blocks = [b for b in re.split(r"\n\s*\n", "\n".join(lines)) if b.strip()]
    blocks = [b for n, b in enumerate(blocks) if not (re.fullmatch(r"#{1,6} [^\n]*", b.strip()) and (
        n + 1 == len(blocks) or re.match(r"#{1,%d} " % len(b.strip().split(" ")[0]), blocks[n + 1].strip())))]
    return "\n\n".join(blocks), taken


def listing_lines(content: str) -> list[str] | None:
    """A page whose own text (headings aside) is only lines that each point to another page, with words of their own
    before the link: those lines, in page order. None for any other page."""
    lines = [l.strip() for l in (content or "").splitlines() if l.strip() and not re.match(r"#{1,6} ", l.strip())]
    page_links = lambda x: [m for m in store.LINK_RE.finditer(x) if not m.group(1).startswith("source-")]
    points = lambda l: page_links(l) and re.search(r"[A-Za-z]", BULLET.sub("", l[:page_links(l)[0].start()]))
    return lines if lines and all(points(l) for l in lines) else None


def subtopic_summary(content: str, c: Checks | None, heads: list[str] | None = None,
                     titles: dict[str, str] | None = None) -> str | None:
    """The schema's subtopic summary: the first requirement claim (one that opens with none of the schema's openers)
    under each of the page's largest headings by words, in page order, on one line; a page with one heading gives its
    first claims, requirement claims first. heads: the source headings its paragraphs sit under that its title does not
    name, in document order; where the schema gives a lead for them, the summary opens with the lead and those
    headings, and the whole summary is kept to the schema's length, headings first. None when the schema sets no such rule or the page
    holds neither claims nor such headings. A page of lines that each point to another page holds no claims of its own:
    None (the page summary lists them). titles: page titles, naming a link that shows no label."""
    if not c or not c.summary_heads or listing_lines(content):
        return None
    claims = _summary_claims(content, c, titles or {})
    if not c.summary_lead:
        return claims
    cap = c.summary_max or 10**9
    fit = []
    for h in heads:  # whole headings, while they fit
        if len(c.summary_lead + c.summary_sep.join(fit + [h])) + 1 > cap:
            break
        fit.append(h)
    out = c.summary_lead + c.summary_sep.join(fit) + "." if fit else ""
    for x in SENTENCE_END.split(claims or ""):  # then whole claims, while they fit
        if not x.strip():
            continue
        if len(out) + 1 + len(x.strip()) > cap:
            break
        out = f"{out} {x.strip()}".strip()
    return out or None


def summary_cut(text: str, c: Checks | None) -> str:
    """A subtopic summary kept to the schema's length (where it sets one): cut at a whole word, marked as cut."""
    if not c or not c.summary_max or len(text or "") <= c.summary_max:
        return text
    return text[:c.summary_max].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def defined_terms(content: str, c: Checks | None) -> list[str]:
    """The terms a page cites in the schema's defined-term citation form, in page order."""
    prefix = c.defined_term_form.split("<", 1)[0] if c and "<" in c.defined_term_form else ""
    if not prefix:
        return []
    return list(dict.fromkeys(lab[len(prefix):].strip() for m in store.LINK_RE.finditer(content or "")
                              if m.group(1).startswith("source-") and (lab := (m.group(2) or "").strip()).startswith(prefix)))


def page_summary(content: str, c: Checks | None, *, terms: bool = False, source: bool = False,
                 titles: dict[str, str] | None = None, sections: frozenset[str] = frozenset(),
                 skip_heads: frozenset[str] = frozenset()) -> str | None:
    """The schema's page summary, for a page no other summary rule covers: its lead, then what the page holds, in page
    order: on the page that defines the wiki's terms (terms), each term it defines; on a source page (source), the
    sections it informs (the section pages it links, by their titles; sections: their slugs); on a page whose own text is only lines that each point to another page,
    each line's own words before its link (up to its last colon); otherwise its own headings (skip_heads aside). Then
    whole requirement claims while they fit, to the schema's length. None when the schema sets no such rule or the
    page holds none of these: an empty page keeps its line."""
    if not c or not c.page_summary:
        return None
    titles = titles or {}
    page_links = lambda x: [m for m in store.LINK_RE.finditer(x) if not m.group(1).startswith("source-")]
    name = lambda m: (m.group(2) or titles.get(m.group(1), m.group(1))).strip()
    lines = [l.strip() for l in (content or "").splitlines() if l.strip()]
    heads = [l for l in lines if re.match(r"#{1,6} ", l)]
    body = [l for l in lines if l not in heads]
    before = lambda l: BULLET.sub("", l[:page_links(l)[0].start()])  # a listed line's own words, before its link
    if terms:
        items = defined_terms(content, c)
    elif source:
        items = [titles.get(m.group(1), m.group(1)) for l in body for m in page_links(l) if m.group(1) in sections]
    elif listed := listing_lines(content):
        items = [" ".join(before(l).rsplit(":", 1)[0].split()).strip(" ,;:") for l in listed]
    else:
        items = [" ".join(store.LINK_RE.sub(name, h.split(" ", 1)[1]).split()) for h in heads if h not in skip_heads]
    items = [x for x in dict.fromkeys(items) if x]
    cap = c.page_summary_max or 10**9
    fit = []
    for x in items:  # whole items, while they fit
        if len(c.page_summary_lead + c.page_summary_sep.join(fit + [x])) + 1 > cap:
            break
        fit.append(x)
    out = c.page_summary_lead + c.page_summary_sep.join(fit) + "." if fit else ""
    plain = lambda x: " ".join(re.sub(r"\s+([.,;:])", r"\1", store.LINK_RE.sub(
        lambda m: "" if m.group(1).startswith("source-") else name(m), LIST_LABEL.sub("", x))).split())
    openers = list(_opener_res(c).values())
    claims = [plain(x) for l in body for x in SENTENCE_END.split(BULLET.sub("", l)) if _is_claim(x)]
    for x in (x for x in claims if not any(p.match(x) for p in openers)):  # then whole requirement claims, while they fit
        if len(out) + 1 + len(x) > cap:
            break
        out = f"{out} {x}".strip()
    return out or None


def _summary_claims(content: str, c: Checks, titles: dict[str, str] | None = None) -> str | None:
    """The claims part of the schema's subtopic summary (see subtopic_summary)."""
    titles = titles or {}
    plain = lambda x: " ".join(re.sub(r"\s+([.,;:])", r"\1", store.LINK_RE.sub(
        lambda m: "" if m.group(1).startswith("source-") else (m.group(2) or titles.get(m.group(1), m.group(1))),
        LIST_LABEL.sub("", x))).split())
    openers = list(_opener_res(c).values())
    is_req = lambda x: not any(p.match(plain(x)) for p in openers)
    parts = []  # (words, claims) under each heading, in page order
    for block in re.split(r"(?m)^(?=#{1,6} )", content):
        claims = [x.strip() for line in block.split("\n") if not re.match(r"#{1,6} ", line)
                  for x in SENTENCE_END.split(BULLET.sub("", line)) if _is_claim(x)]
        if claims:
            parts.append((len(block.split()), claims))
    if not parts:
        return None
    if len(parts) == 1:
        claims = parts[0][1]
        picked = ([x for x in claims if is_req(x)] + [x for x in claims if not is_req(x)])[: c.summary_heads]
    else:
        top = sorted(sorted(range(len(parts)), key=lambda k: -parts[k][0])[: c.summary_heads])
        picked = [next((x for x in parts[k][1] if is_req(x)), parts[k][1][0]) for k in top]
    return " ".join(plain(x) for x in picked)


def holds_no_claims(c: Checks | None, slug: str, is_index: bool = False) -> bool:
    """Whether the schema says this page holds no claims: it is named, or it is a split section's index page and the
    schema names those."""
    return bool(c) and (slug in c.no_claim_pages or (is_index and c.no_claim_index))


def absence_allowed_on(c: Checks | None, ptype: str, title: str) -> bool:
    """Whether the schema's absence phrases may stand on this page: the pages its label names, by kind of page ("the
    source page") or by title ("Overview and status"). With no such entry, every page may hold them."""
    if not (c and c.absence):
        return True
    where = c.absence_allowed.casefold()
    return f"{ptype} page" in where or bool(title) and title.casefold() in where


def absence_failures(content: str, c: Checks | None, source_text: str = "") -> list[str]:
    """Sentences that say something is not stated, not addressed or was searched for (the schema's absence phrases),
    on a page where they are not allowed. A phrase the source paragraphs themselves use is the paper's own words."""
    if not (c and c.absence):
        return []
    said = source_text.casefold()
    phrases = [p for p in c.absence if p.casefold() not in said]
    if not phrases:
        return []
    pat = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.I)
    out = []
    for line in content.split("\n"):
        if re.match(r"^#{1,6} ", line):
            continue
        out += [f'The page says "{x.strip()[:200]}". A page here records what the paper states, never what it leaves '
                "out or what was looked for; remove that sentence." for x in SENTENCE_END.split(line) if pat.search(x)]
    return out


REPEAT = "The page holds the same text twice"


def _cited_sentences(content: str) -> list[str]:
    """The page's sentences that cite a source paragraph, in order (headings aside)."""
    out = []
    for line in content.split("\n"):
        if re.match(r"^#{1,6} ", line):
            continue
        out += [x.strip() for x in SENTENCE_END.split(BULLET.sub("", line)) if _is_claim(x)]
    return out


def _same(x: str) -> str:
    return " ".join(re.sub(r"[^\w\[\]|.]+", " ", x.casefold()).split())


def heading_failures(content: str) -> list[str]:
    """A heading line that holds a source citation: a heading and the text under it run together."""
    return [f'The heading line "{" ".join(l.split()[:12])} ..." holds a citation: it is a heading and its text run '
            "together. Put the heading on its own line, and its text on the line below."
            for l in (content or "").splitlines()
            if re.match(r"#{1,6} ", l) and any(m.group(1).startswith("source-") for m in store.LINK_RE.finditer(l))]


def repeat_failures(content: str) -> list[str]:
    """A cited sentence the page holds more than once."""
    seen, out = set(), []
    for x in _cited_sentences(content):
        if (k := _same(x)) in seen:
            out.append(f'{REPEAT}: "{" ".join(x.split()[:15])} ..." appears more than once; keep it once.')
        seen.add(k)
    return list(dict.fromkeys(out))


def drop_repeats(content: str) -> tuple[str, int]:
    """The page without the later copies of a cited sentence it already holds, word for word the same; a line left
    with no words goes too, and so does a heading left with nothing under it. Returns (text, how many went)."""
    seen: set[str] = set()
    lines, dropped = [], 0
    for line in content.split("\n"):
        if re.match(r"^#{1,6} ", line) or not _is_claim(line):
            lines.append(line)
            continue
        lead = (BULLET.match(line) or [""])[0]
        kept = []
        for x in SENTENCE_END.split(line[len(lead):]):
            if _is_claim(x) and _same(x) in seen:
                dropped += 1
                continue
            if _is_claim(x):
                seen.add(_same(x))
            kept.append(x)
        rest = " ".join(kept).strip()
        if re.search(r"[A-Za-z]", store.LINK_RE.sub("x", rest)):
            lines.append(lead + rest)
    blocks = [b for b in re.split(r"\n\s*\n", "\n".join(lines)) if b.strip()]
    blocks = [b for n, b in enumerate(blocks) if not (re.fullmatch(r"#{1,6} [^\n]*", b.strip()) and (
        n + 1 == len(blocks) or re.match(r"#{1,%d} " % len(b.strip().split(" ")[0]), blocks[n + 1].strip())))]
    return ("\n\n".join(blocks), dropped) if dropped else (content, 0)


def label_failures(content: str, labels: dict[str, set[str]], c: Checks | None) -> list[str]:
    """A citation whose label is not made of paragraph labels of the source it names: a document, chapter or section
    number is not a paragraph. Ranges ("B4.1.1–B4.1.26"), lists and sub-paragraph letters ("5.5.17(a)", "(i)-(ii)")
    are read part by part; the schema's forms for defined terms and unlabelled text are labels of the source too."""
    out = []
    term = c.defined_term_form.split("<", 1)[0].strip() if c and "<" in c.defined_term_form else ""
    for m in store.LINK_RE.finditer(content):
        slug, lab = m.group(1), (m.group(2) or "").strip()
        if slug not in labels or not lab or lab in labels[slug]:
            continue
        flat = re.sub(r"\s*:\s*", ": ", lab)
        if flat in {re.sub(r"\s*:\s*", ": ", x) for x in labels[slug]}:
            continue
        if term and flat.casefold().startswith(term.casefold()):
            continue  # a defined term: its own check reads the form
        sub = r"\((?:[a-z]{1,3}|[ivxlcdm]{1,6}|\d{1,3}|[A-Z])\)"  # a sub-paragraph letter or number: (a), (iv), (2), (B)
        bare = re.sub(rf"(?:\s*{sub}(?:\s*[\u2013-]\s*{sub})?)+", "", lab)  # sub-paragraph letters and their ranges
        pieces = [x.strip() for x in re.split(r",|;|\band\b|\s*[\u2013\u2014-]\s*", bare) if x.strip()]
        if pieces and all(x in labels[slug] for x in pieces):
            continue
        out.append(f"The citation [[{slug}|{lab}]] does not name a paragraph of that source (a document, chapter or "
                   "section is not a paragraph): cite the paragraph's own label.")
    return list(dict.fromkeys(out))


def empty_sections(c: Checks | None, contents: dict[str, str]) -> set[str]:
    """Section pages the overview lists with the schema's word for an empty section rather than a link: those holding
    only the schema's empty-section text. None unless the schema has both entries (Overview lines, Empty section text)."""
    if not (c and c.overview_empty and c.empty_text):
        return set()
    return {sl for sl, md in contents.items() if (md or "").strip() == c.empty_text}


def section_slug(c: Checks | None, num: int, name: str) -> str:
    """A section page's slug from the schema's pattern (<nn> the two-digit section number, <section name> the
    section's name); empty when the schema gives no pattern."""
    if not (c and c.section_slug):
        return ""
    return store.slugify(c.section_slug.replace("<nn>", f"{num:02d}").replace("<section name>", name))


def no_claim_failures(content: str, must_link: set[str], c: Checks | None, names: set[str] = frozenset(),
                      empty: set[str] = frozenset()) -> list[str]:
    """Where a page that holds no claims breaks that: a page it must link (the overview: every section page; an index
    page: every subtopic page of its section) that it does not, and a sentence on it that cites a source paragraph.
    empty: section pages listed with the schema's word for an empty section, never linked."""
    if not c:
        return []
    linked = {m.group(1) for m in store.LINK_RE.finditer(content)}
    out = [f"The page does not list [[{s}]]; it lists every page it is the index of." for s in sorted(must_link - empty - linked)]
    out += [f'The page links [[{s}]], whose page holds no claims; list that section with "{c.overview_empty}" instead '
            "of a link." for s in sorted(empty & linked)]
    return out + [f'The sentence "{" ".join(x.split()[:15])} ..." cites a source paragraph, but this page holds no claims: '
                  "the claim belongs on the page that holds that paragraph." for x in take_claims(content, names=names)[1]]


def _label(para: str) -> str:
    m = re.match(r"^\[([^\]]+)\]", para)
    return m.group(1).strip() if m else ""


def _stub_parts(body: str, part_re: re.Pattern, c: Checks) -> set[str]:
    """The lettered parts of a paragraph whose text starts with one of the schema's stub forms."""
    rx = stub_re(c)
    if not rx:
        return set()
    marks = list(part_re.finditer(body))
    return {m.group(1) for k, m in enumerate(marks)
            if rx.match(body[m.end(): marks[k + 1].start() if k + 1 < len(marks) else len(body)].strip())}


def section_failures(content: str, given: list[str], kinds: dict[str, str], source_slug: str, c: Checks, covers,
                     labels: set[str] = frozenset(), holds=lambda ref: True) -> list[str]:
    """Where a written page breaks the schema's checks for its own paragraphs: a lettered part of a paragraph whose
    write-up the page holds (holds: a page citing it as a cross-reference is not checked for its parts) missing near its
    citation, a condition phrase missing there, and a sentence citing a non-Standard paragraph without its opener."""
    failures = []
    blocks = [b for b in re.split(r"\n\s*\n", content) if b.strip()]
    part_re = _part_re(c)
    for p in given:
        ref = _label(p)
        body = re.sub(r"^\[[^\]]+\]\s*(?:\([A-Z][^)]*\)\s*)?", "", p)
        near = "\n".join(b for b in blocks if any(
            m.group(1) == source_slug and m.group(2) and covers(m.group(2), ref) for m in store.LINK_RE.finditer(b)))
        if not near:
            continue  # not written up at all: the coverage passes deal with that
        if part_re and holds(ref) and len(parts := list(dict.fromkeys(part_re.findall(body)))) >= 2:
            stubs = _stub_parts(body, part_re, c)  # a part that is only a stub ("(c) [deleted]") is not written up
            if lost := [x for x in parts if x not in near and x not in stubs]:
                failures.append(f"Paragraph {ref} has lettered or numbered parts {', '.join(parts)}; "
                                f"{', '.join(lost)} do not appear on the page.")
        flat_body, flat_near = _flat(body), _flat(near)
        if lost := [w for w in c.conditions if re.search(rf"\b{re.escape(w.casefold())}\b", flat_body)
                    and not re.search(rf"\b{re.escape(w.casefold())}\b", flat_near)]:
            failures.append(f"Paragraph {ref} states the condition(s) {', '.join(repr(w) for w in lost)}, "
                            "which do not appear where the page writes it up.")
    openers = _opener_res(c)
    if openers and c.kinds:
        for line in content.split("\n"):
            line = line.strip().lstrip("-*\u2022 ").strip()
            if not line or line.startswith("#"):
                continue
            for s in re.split(r"(?<=\]\])[.;:]?\s+(?=[A-Z(])", line):
                cited = [m.group(2) for m in store.LINK_RE.finditer(s) if m.group(1) == source_slug and m.group(2)]
                if not cited or not s[:1].isupper():  # no citation, or a list item continuing a lead-in sentence
                    continue
                body = LIST_LABEL.sub("", s, count=1)  # "Interest rate swap**: The implementation guidance states ..."
                found = {c.kinds.get(kinds.get(re.sub(r"\(.*$", "", lab).strip(), "")) for lab in cited}
                if len(found) == 1 and (k := found.pop()) in openers:
                    m = openers[k].match(body)
                    if not m:
                        failures.append(f"The sentence citing {', '.join(cited)} (\"{s[:90]}...\") comes from {k} but does not "
                                        f"open with the schema's opener for {k} ({', '.join(c.openers[k])}).")
                    elif named := [g.strip() for g in m.groups() if g and g.strip() in labels]:
                        failures.append(f"The sentence citing {', '.join(cited)} (\"{s[:90]}...\") names its example "
                                        f"\"{named[0]}\", which is one of the source's paragraph labels, not the example's name.")
    return failures


PAGE_LABEL = re.compile(r"p(?:age)?\s*\d+", re.I)  # the PDF reader's label for a page it could not number


def citation_failures(content: str, labels: dict[str, set[str]], names: set[str], c: Checks | None) -> list[str]:
    """Citations that cite something other than a clause of the source they name: a page label of the reader, a
    document or section name (the wiki's own source and section names), or a defined term not in the schema's
    citation form."""
    failures = []
    prefix = c.defined_term_form.split("<", 1)[0] if c and "<" in c.defined_term_form else ""
    flat_names = {_flat(n) for n in names if n}
    forms = list((c.unlabelled_forms if c else {}).values())
    page_ok = any("<page label>" in f for f in forms)  # the schema lets unlabelled text be cited by its page label
    tagged = [f.split("<", 1)[0] for f in forms if "<" in f and not f.startswith("<")]  # e.g. a prefix before <clause>
    for m in store.LINK_RE.finditer(content):
        slug, lab = m.group(1), (m.group(2) or "").strip()
        if slug not in labels or not lab:
            continue
        have = {x.casefold() for x in labels[slug]}
        cite = f"[[{slug}|{lab}]]"
        if any(lab.casefold().startswith(t.casefold()) for t in tagged):
            continue  # a form the schema gives for unlabelled text; the citation check tests the clause it names
        if PAGE_LABEL.fullmatch(lab):
            if page_ok and lab in labels[slug]:
                continue  # text the reader kept without a paragraph label, cited by its page label as the schema allows
            failures.append(f"The citation {cite} cites a page label that is not a block of this source, or that the "
                            "schema does not allow: cite the paragraph's own label"
                            + (f", or use the form the schema gives ({', '.join(forms)})." if forms else "."))
        elif prefix and not lab.casefold().startswith(prefix.casefold()) and (
                f"{prefix}{(term := lab.split(':', 1)[-1].strip())}".casefold() in have):
            failures.append(f"The citation {cite} cites a defined term in the wrong form: cite it as \"{prefix}{term}\".")
        elif lab.casefold() not in have and not (prefix and lab.casefold().startswith(prefix.casefold())) and any(
                re.search(rf"(?<!\w){re.escape(_flat(lab))}(?!\w)", n) for n in flat_names):
            failures.append(f"The citation {cite} cites a document or section name, not a clause: cite the clause it rests on.")
    return list(dict.fromkeys(failures))


def detail_lines(content: str, c: Checks) -> str:
    """On a source page, each recorded detail the schema lists (e.g. issuer, edition, part) on a line of its own."""
    names = [n.strip() for what in c.source_parts.values()
             if not any(k in what for k in ("authority", "informed sections", "cited claims"))
             for n in re.split(r",|\band\b", what) if n.strip()]
    if not names:
        return content
    pat = re.compile(r"(?:\*\*)?\b(?:" + "|".join(map(re.escape, names)) + r")\b(?:\*\*)?\s*:", re.I)
    # a line break the reply left out: a sentence's end run straight into the next ("draft for review.Client:"), or a
    # detail's value run into a sentence ("Owner: Not statedThe stated purpose ...")
    content = SENTENCE_RUN_ON.sub("\n", content)
    # a detail run straight on after the value before it ("Client: Sample Bank LtdTitle: ..."), written capitalised
    content = re.sub(r"(?<=[a-z0-9).])(?=(?:\*\*)?(?:" + "|".join(re.escape(n[:1].upper() + n[1:]) for n in names) + r")(?:\*\*)?\s*:)",
                     "\n", content)
    # a label run into its text ("Key takeaways:The ..."); a detail and its value ("Status:Draft") stay together
    content = re.sub(r"(?m)^([^\n:\[\]]{1,40}:)(?=[A-Z])", lambda m: m.group(1) if pat.match(m.group(1).lstrip(" -*\u2022")) else m.group(1) + "\n", content)
    content = "\n".join(re.sub(r"(?<=[a-z])(?=[A-Z][a-z]+ [a-z])", "\n", ln) if pat.match(ln.lstrip(" -*\u2022")) else ln
                         for ln in content.split("\n"))
    out = []
    for line in content.split("\n"):
        hits = [m.start() for m in pat.finditer(line)]
        if not hits or (len(hits) < 2 and not line[:hits[0]].strip(" -*\u2022")):
            out.append(line)
            continue
        bullet = re.match(r"^\s*([-*\u2022])\s+", line)
        mark = bullet.group(1) if bullet else "-"
        lead_text = line[:hits[0]].strip(" -*\u2022")
        cuts = ([0, hits[0]] if lead_text else [0]) + hits[1:] + [len(line)]
        parts = [re.sub(r"(?:\s+[-*\u2022])?\s*[,;]?\s*$", "", line[a:b]).strip() for a, b in zip(cuts, cuts[1:])]
        out += [parts[0]] + [f"{mark} {re.sub(r'^[-*\u2022]\s+', '', p)}" for p in parts[1:] if p]
        if lead_text and not bullet:  # the sentence before the details stays a line of its own, the details become a list
            out[-len(parts):] = [parts[0]] + [f"- {re.sub(r'^[-*\u2022]\s+', '', p)}" for p in parts[1:] if p]
    return "\n".join(out)


def authority_sentences(text: str, c: Checks) -> list[str]:
    """The source's own sentences in one of the schema's authority forms."""
    out = []
    for form in c.authority:
        # the reader's own label and kind tag ("[IG introduction] (Implementation guidance) ...") are not the source's words
        pat = re.compile(r"(?:^\[[^\]]+\]\s*(?:\([A-Z][^)]*\)\s*)?)?([^.\n\[\]()]*" + _template(form, r".+?") + r"[^\n]*?\.)(?=\s|$)",
                         re.M | re.I)
        out += [m.group(1).strip() for m in pat.finditer(text)]
    return list(dict.fromkeys(out))


def source_failures(content: str, *, fields: dict[str, str], authority: list[str], informed: set[str],
                    sections: set[str], source_slug: str, c: Checks, labels: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """Where a source page lacks a part the schema's Checks list names. Each part is checked by what its entry asks
    for: recorded fields (e.g. issuer, edition, part), the authority forms, the informed sections, cited claims.
    Returns (failures, parts that could not be checked)."""
    failures, skipped = [], []
    text = _words(content)
    for part, what in c.source_parts.items():
        if "authority" in what:
            if not authority:
                skipped.append(f"{part}: the source has no sentence in the schema's authority forms")
            for a in authority:
                if _words(a) not in text:
                    failures.append(f'The page lacks {part}: "{a}" is not transcribed verbatim.')
        elif "informed sections" in what:
            linked = {m.group(1) for m in store.LINK_RE.finditer(content)}
            if missing := sorted(informed - linked):
                failures.append(f"The page lacks {part}: it does not list " + ", ".join(f"[[{x}]]" for x in missing) + ".")
            if wrong := sorted((linked & sections) - informed):
                failures.append(f"The page lists " + ", ".join(f"[[{x}]]" for x in wrong)
                                + " as sections this source informs, but no paragraph of this source is on them.")
        elif "cited claims" in what:
            # within the part itself where the page names it (the schema's name for the part, up to "as ..."), so the
            # document's facts and purpose, cited above it, are not counted as takeaways
            name = re.split(r"\s+as\s+", part)[0]
            lead = re.search(rf"(?im)^[#*\s-]*{re.escape(name)}\b[^\n]*$", content)
            scope = content[lead.start():] if lead else content
            if lead and (nxt := re.search(r"(?m)^#{1,4} ", scope[lead.end() - lead.start():])):
                scope = scope[: lead.end() - lead.start() + nxt.start()]
            claims = [s for s in re.split(r"(?<=\]\])[.;:]?\s+|\n+", scope) if any(
                m.group(1) == source_slug and m.group(2) and (m.group(2).strip() in labels or re.search(r"\d", m.group(2))
                and not re.fullmatch(r"p(?:age)?\s*\d+", m.group(2).strip()))  # a location it has; not the reader's page label
                for m in store.LINK_RE.finditer(s))]
            if not claims:
                failures.append(f"The page lacks {part}: no line states a claim of this source with its paragraph citation.")
            elif c.max_takeaways is not None and len(claims) > c.max_takeaways:
                failures.append(f"The page has {len(claims)} {part}; the schema allows at most {c.max_takeaways}. "
                                "Keep only the source's highest-ranked claims.")
        else:  # recorded fields named in the entry
            names = [n.strip() for n in re.split(r",|\band\b", what) if n.strip()]
            for n in names:
                value = (fields or {}).get(n, "").strip()
                if not value:
                    skipped.append(f"{part}: no {n} recorded for this source")
                elif _words(value) not in text:
                    failures.append(f'The page lacks {part}: it does not give the {n} as recorded ("{value}").')
    # the source page holds only the parts listed: a heading that names none of them is a section it should not have
    names = [set(re.findall(r"[a-z]{4,}", p)) - STOP for p in c.source_parts]
    extra = [h.strip() for h in re.findall(r"^#{1,4}\s+(.+)$", content, re.M)
             if not any(n & (set(re.findall(r"[a-z]{4,}", h.casefold())) - STOP) for n in names)]
    if names and extra:
        failures.append("The page has sections the schema's source page does not have: "
                        + ", ".join(f'"{h}"' for h in extra) + ". It holds only " + ", ".join(c.source_parts) + ".")
    return failures, skipped


STOP = {"what", "which", "that", "this", "with", "linked", "their", "from", "into"}
