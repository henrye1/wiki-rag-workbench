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
    part_forms: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    authority: list[str] = field(default_factory=list)
    source_parts: dict[str, str] = field(default_factory=dict)  # part as the schema names it -> what is checked
    missing: list[str] = field(default_factory=list)  # lists the schema does not give: their checks are off


LISTS = {  # attribute -> how the schema names the list (its label up to the first word that differs)
    "kinds": "paragraph kinds", "openers": "openers", "linking": "linking words", "part_forms": "lettered part forms",
    "conditions": "condition phrases", "authority": "authority forms", "source_parts": "source-page parts",
}


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
        else:
            setattr(c, attr, QUOTED.findall(value))
    return c


def _template(text: str, wild: str) -> str:
    """A schema phrase as a pattern: "<...>" placeholders and "..." match any short run of words."""
    out = re.escape(text)
    out = re.sub(r"<[^>]*>", lambda _: wild, out.replace(r"\<", "<").replace(r"\>", ">"))
    return out.replace(re.escape("..."), r".+?")


def _opener_res(c: Checks) -> dict[str, re.Pattern]:
    link = "|".join(map(re.escape, c.linking))
    lead = rf"(?:(?:{link})\s+)?" if link else ""
    return {kind: re.compile(rf"^{lead}(?:" + "|".join(_template(o, r"[^,.\]]{1,60}?") for o in ops) + r")", re.I)
            for kind, ops in c.openers.items() if ops}


def _part_re(c: Checks) -> re.Pattern | None:
    """The schema's lettered-part forms ("(a)", "(i)") as one pattern: a run of letters or digits stands for any."""
    if not c.part_forms:
        return None
    pats = {re.sub(r"\\?[A-Za-z]+|\d+", lambda m: "[a-z]{1,5}" if m.group(0).lstrip("\\").islower() else
                   "[A-Z]{1,5}" if m.group(0).lstrip("\\").isalpha() else r"\d{1,3}", re.escape(f)) for f in c.part_forms}
    return re.compile(r"(?:^|(?<=[\s:;\u2013\u2014]))(" + "|".join(sorted(pats)) + r")(?=\s)")


def cites(text: str) -> set[str]:
    """The source citations on a page, as slug|clause (sub-paragraph letters aside: 5.5.17(a) is a citation of 5.5.17)."""
    return {f"{m.group(1)}|{re.sub(r'(?:\s*\([^)]*\))+$', '', m.group(2).strip())}" for m in store.LINK_RE.finditer(text)
            if m.group(1).startswith("source-") and m.group(2)}


def _label(para: str) -> str:
    m = re.match(r"^\[([^\]]+)\]", para)
    return m.group(1).strip() if m else ""


def section_failures(content: str, given: list[str], kinds: dict[str, str], source_slug: str, c: Checks, covers) -> list[str]:
    """Where a written page breaks the schema's checks for its own paragraphs: a lettered part or a condition phrase of
    a paragraph missing near its citation, and a sentence citing a non-Standard paragraph without the schema's opener."""
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
        if part_re and len(parts := list(dict.fromkeys(part_re.findall(body)))) >= 2:
            if lost := [x for x in parts if x not in near]:
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
                labels = [m.group(2) for m in store.LINK_RE.finditer(s) if m.group(1) == source_slug and m.group(2)]
                if not labels or not s[:1].isupper():  # no citation, or a list item continuing a lead-in sentence
                    continue
                found = {c.kinds.get(kinds.get(re.sub(r"\(.*$", "", lab).strip(), "")) for lab in labels}
                if len(found) == 1 and (k := found.pop()) in openers and not openers[k].match(s):
                    failures.append(f"The sentence citing {', '.join(labels)} (\"{s[:90]}...\") comes from {k} but does not "
                                    f"open with the schema's opener for {k} ({', '.join(c.openers[k])}).")
    return failures


def authority_sentences(text: str, c: Checks) -> list[str]:
    """The source's own sentences in one of the schema's authority forms."""
    out = []
    for form in c.authority:
        pat = re.compile(r"(?:^\[[^\]]+\]\s*)?([^.\n\[\]]*" + _template(form, r".+?") + r"[^\n]*?\.)(?=\s|$)", re.M | re.I)
        out += [m.group(1).strip() for m in pat.finditer(text)]
    return list(dict.fromkeys(out))


def source_failures(content: str, *, fields: dict[str, str], authority: list[str], informed: set[str],
                    sections: set[str], source_slug: str, c: Checks) -> tuple[list[str], list[str]]:
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
            if not any(m.group(1) == source_slug and m.group(2) and re.search(r"\d", m.group(2))
                       and not re.fullmatch(r"p(?:age)?\s*\d+", m.group(2).strip())  # the reader's page label, not a paragraph
                       for m in store.LINK_RE.finditer(content)):
                failures.append(f"The page lacks {part}: no line states a claim of this source with its paragraph citation.")
        else:  # recorded fields named in the entry
            names = [n.strip() for n in re.split(r",|\band\b", what) if n.strip()]
            for n in names:
                value = (fields or {}).get(n, "").strip()
                if not value:
                    skipped.append(f"{part}: no {n} recorded for this source")
                elif _words(value) not in text:
                    failures.append(f'The page lacks {part}: it does not give the {n} as recorded ("{value}").')
    return failures, skipped
