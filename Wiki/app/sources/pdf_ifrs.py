"""Layout-aware parser for IFRS Foundation annotated standards (e.g. IFRS 9 PDF).

Layout facts it relies on:
- Paragraph numbers (1.1, 5.5.3, B5.5.17) sit in the left margin in the body (Swift) font.
- Body text is indented further right than the margin.
- Editorial material ([Refer:], [Note:], [Link], IFRIC boxes, E-footnotes) uses HelveticaLTPro-BoldCond.
- Headings use HelveticaLTPro Bold/Oblique at >= 9.5pt.
- Running header/footer use HelveticaLTPro-Roman 9pt.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from .models import ACCOMPANYING_TYPES, Chunk
from .text import clean, split_long

PARA_RE = re.compile(r"^(?:B[A-Z]\.|B|C|BCZ?|IE|IG)?\d+(?:\.\d+)*[A-Z]{0,2}$")  # B[A-Z]. = lettered sections of Appendix B (BA.1)
# Documents published with a Standard (Parts B and C of the IFRS bound volumes), numbered by prefix:
# IE = illustrative example, IG = implementation guidance, BC/BCZ/BCIN/BCE/... = Basis for Conclusions, DO = dissenting opinion
ACCOMPANYING_RE = re.compile(r"^(IE|IG|BC[A-Z]{0,3}|DO)(?:\d+|\.\d+)(?:\.\d+)*[A-Z]{0,2}$")
ACCOMPANYING_KINDS = {"IE": "example", "IG": "implementation_guidance", "DO": "dissenting_opinion"}  # BC... -> basis_for_conclusions
# Implementation guidance numbers its questions in their headings ("A.1 Practice of settling net: ..."), not in the margin
IG_HEADING_RE = re.compile(r"^([A-G])\.(\d+)\s+\S")
IG_TITLE_RE = re.compile(r"^Guidance on implementing\b", re.I)  # its title; the note under it says the guidance is not part of the Standard
IG_INTRO = "IG introduction"
RANGE_DASH = ("\u2013", "\u2014", "-")  # "BC2.17A–" continued by "BC2.17H" on the next line: a range of deleted paragraphs
EDITORIAL_BRACKETS = re.compile(r"\[(?:Refer|Note|Link|now)\b[^\]]*\]", re.I)
MARGIN_MAX_X = 150
HEADER_Y, FOOTER_Y = 110, 720


@dataclass
class _Para:
    ref: str | None
    section: str
    page: int
    heading: str | None
    body: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    path: tuple = ()
    footnotes: list[list[str]] = field(default_factory=list)  # footnotes printed under this paragraph, each its lines


# A numbered heading ("6.4 Qualifying criteria ...", "Chapter 6 Hedge accounting"): its level is its number's depth
NUMBERED_HEADING = re.compile(r"^(?:[A-Z][a-z]+\s+)?(\d+(?:\.\d+)*)\s+[A-Z]")


def _style(font: str, size: float) -> tuple:
    return (round(size, 1), "Bold" in font and "Obliq" not in font)


def _label_size(doc: pymupdf.Document) -> float:
    """The size paragraph labels are set in: the most common size of numbers in the margin, in the IFRS margin font."""
    sizes = Counter(round(s["size"], 1) for page in doc for row in _lines(page) for s in row
                    if s["bbox"][0] < MARGIN_MAX_X and s["font"].startswith("Swift")
                    and (PARA_RE.match(t := s["text"].strip().rstrip("".join(RANGE_DASH))) or ACCOMPANYING_RE.match(t)))
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _is_footnote_mark(text: str, font: str, size: float, x: float, label_size: float) -> bool:
    """A number in the margin set smaller than the paragraph labels: a footnote, not a paragraph."""
    return bool(label_size) and x < MARGIN_MAX_X and font.startswith("Swift") and text.isdigit() and round(size, 1) < label_size - 0.4


def _heading_styles(doc: pymupdf.Document) -> dict[tuple, int]:
    """Rank of each heading style in the document: larger first, then bold before italic (1 = top)."""
    styles = set()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip() and _is_heading(s["font"], s["size"]):
                        styles.add(_style(s["font"], s["size"]))
    return {st: i + 1 for i, st in enumerate(sorted(styles, key=lambda st: (-st[0], not st[1])))}


def _level(text: str, style_rank: int, path: list) -> int:
    """A numbered heading sits at its number's depth; an unnumbered one under the last numbered heading above it,
    at its style's rank."""
    if m := NUMBERED_HEADING.match(text):
        return len(m.group(1).split("."))
    base = max((lvl for lvl, _, numbered in path if numbered), default=0)
    return base + style_rank


def _example_kind(heading: str, example_re) -> str | None:
    """The label word of an example title ("Example 7—..." -> "example", "Scenario 1" -> "scenario"): the heading
    starts with one of the wiki schema's example labels. None for any other heading."""
    m = example_re.match(heading) if example_re else None
    return m.group(0).split()[0].casefold() if m else None


def _next_heading(doc: pymupdf.Document, example_re) -> dict[tuple, str]:
    """For each heading (page, y of its first line): the next heading in the document. A heading followed by the
    next title of an example's kind introduces that example (or a group of them); it does not belong to the one before."""
    if not example_re:
        return {}
    heads, prev = [], None
    for pno, page in enumerate(doc, start=1):
        for row in _lines(page):
            s = row[0]
            if not _is_heading(s["font"], s["size"]):
                continue
            y, text = row[0]["bbox"][1], " ".join(x["text"].strip() for x in row)
            if prev and prev[0] == pno and prev[2:] == (s["font"], s["size"]) and 0 <= y - prev[1] < 14:
                prev = (pno, y, s["font"], s["size"])  # the heading runs on to a second line
                continue
            heads.append(((pno, y), text))
            prev = (pno, y, s["font"], s["size"])
    return {k: heads[n + 1][1] for n, (k, _) in enumerate(heads[:-1])}


def _is_editorial(font: str, size: float = 8.5, x: float = 999) -> bool:
    # BoldCond = [Refer]/[Note]/IFRIC boxes; small Helvetica Bold left of body = IFRIC box sub-headings
    return "BoldCond" in font or (font == "HelveticaLTPro-Bold" and size < 9 and x < 175)


def _is_heading(font: str, size: float) -> bool:
    return font.startswith("HelveticaLTPro") and not _is_editorial(font) and "Roman" not in font and size >= 9.4


def looks_like_ifrs(doc: pymupdf.Document) -> bool:
    hits = 0
    for page in doc.pages(0, min(doc.page_count, 40)):
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["bbox"][0] < MARGIN_MAX_X and s["font"].startswith("Swift") and PARA_RE.match(s["text"].strip()):
                        hits += 1
    return hits >= 10


def _lines(page: pymupdf.Page):
    """Yield lines as lists of spans, ordered top->bottom, left->right. Margin labels sort first on their row."""
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["text"].strip():
                    spans.append(s)
    spans.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
    rows: list[list[dict]] = []
    for s in spans:
        if rows and abs(s["bbox"][1] - rows[-1][0]["bbox"][1]) <= 3:
            rows[-1].append(s)
        else:
            rows.append([s])
    for r in rows:
        yield sorted(r, key=lambda s: s["bbox"][0])


def _section_for_heading(text: str, current: str) -> str:
    t = text.lower()
    if t.startswith("international financial reporting standard"):
        return "standard"
    if t == "appendix a":
        return "appendix_a"
    if t == "appendix b":
        return "appendix_b"
    if t == "appendix c":
        return "appendix_c"
    if t.startswith("approval by the board") or t.startswith("basis for conclusions") or t.startswith("dissenting"):
        return "back_matter"
    return current


def _join(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out.endswith("-") and p[:1].islower():
            out += p
        else:
            out += (" " if out else "") + p
    return clean(out)


LABEL_IN_TEXT = PARA_RE.pattern.strip("^$")


def _split_stubs(ref: str | None, body: str, stub_re) -> list[tuple[str | None, str]]:
    """A paragraph's text with each stub printed inside it under its own label ("... 12–12A [Deleted]") taken out
    as its own paragraph; text after a stub stays with the paragraph. A paragraph that opens with a stub is only the
    stub: text after it (a heading or contents line run on) is unlabelled text of its own."""
    if not body or not stub_re:
        return [(ref, body)] if body else []
    if ref and (lead := stub_re.match(body)) and body[lead.end():].strip():
        return [(ref, lead.group(0))] + _split_stubs(None, body[lead.end():].strip(), stub_re)
    dash = "".join(RANGE_DASH)
    rx = re.compile(rf"(?:(?<=\s)|^)({LABEL_IN_TEXT}(?:[{dash}]{LABEL_IN_TEXT})?)\s+(?=(?:{stub_re.pattern}))", stub_re.flags)
    own, out, at = [], [], 0
    for m in rx.finditer(body):
        stub = stub_re.match(body, m.end())
        if not stub or m.start() < at:
            continue
        own.append(body[at:m.start()])
        out.append((m.group(1).replace("\u2014", "\u2013").replace("-", "\u2013"), stub.group(0)))
        at = stub.end()
    own.append(body[at:])
    text = " ".join(x.strip() for x in own if x.strip())
    return ([(ref, text)] if text else []) + out


def accompanying_kind(ref: str) -> str:
    m = ACCOMPANYING_RE.match(ref.rstrip("".join(RANGE_DASH)))
    prefix = m.group(1) if m else ""
    return ACCOMPANYING_KINDS.get(prefix, "basis_for_conclusions" if prefix.startswith("BC") else "intro")


def parse_document(doc: pymupdf.Document, max_words: int = 500, stub_re=None, footnote_form=None,
                   example_re=None) -> tuple[list[Chunk], str]:
    """Read an IFRS PDF. A Standard (Part A) is read exactly as parse() always has; a document published with it
    (illustrative examples, implementation guidance, Basis for Conclusions: Parts B and C) by its own paragraph numbers.

    Returns (chunks, layout): layout is "standard", "accompanying", or "" when no numbered paragraphs were recognised.
    A short accompanying document can have too few numbered paragraphs for looks_like_ifrs(); it is still recognised
    by its numbering (IE, IG, BC..., DO in the IFRS margin font), but never read as a Standard.
    stub_re: the wiki schema's stub forms (what a deleted or left-out paragraph says), each read as its own paragraph.
    footnote_form: the schema's citation form for a footnote, which keeps footnotes (see parse).
    """
    chunks = parse(doc, max_words, stub_re=stub_re, footnote_form=footnote_form, example_re=example_re) if looks_like_ifrs(doc) else []
    if any(c.source_type == "standard" for c in chunks):
        return chunks, "standard"
    acc = parse(doc, max_words, accompanying=True, stub_re=stub_re, footnote_form=footnote_form, example_re=example_re)
    if any(c.source_type in ACCOMPANYING_TYPES for c in acc):
        return acc, "accompanying"
    return chunks, ""


def parse(doc: pymupdf.Document, max_words: int = 500, accompanying: bool = False, stub_re=None,
          footnote_form: str | None = None, example_re=None) -> list[Chunk]:
    """accompanying=False reads a Standard (Part A); True reads a document published with one (Parts B and C).
    footnote_form: how the wiki's schema cites a footnote ("ED:<clause>"): each footnote is kept, labelled in that form
    with the paragraph whose text carries its marker (or, with no marker found, the one it is printed under); without it
    footnotes are left out."""
    section = "intro"
    heading: str | None = None
    heading_buf: list[str] = []
    heading_key: tuple = ()
    ranks = _heading_styles(doc)
    path: list = []  # [(level, heading, numbered)], top down: the headings the current text sits under
    title_size = 0.0  # while set: headings this large are the document's title, not a heading of its text
    paras: list[_Para] = []
    cur = _Para(None, section, 1, None)
    last_label: tuple = ()  # (page, y) of last margin label, to join multi-line defined terms
    label_size = _label_size(doc)
    footnote: tuple = ()  # (page, size) while reading a footnote: its lines are the footnote's, not paragraph text
    hold: tuple | None = None  # (level, label word) of an example's title, while the headings of its style sit under it
    next_heading = _next_heading(doc, example_re)  # (page, y) of a heading -> the heading after it
    marked: dict[str, _Para] = {}  # footnote number -> the paragraph whose text carries its marker
    note_to: _Para | None = None  # the paragraph the footnote being read belongs to

    def flush():
        nonlocal cur
        if cur.body or cur.notes or cur.footnotes:
            paras.append(cur)

    for pno, page in enumerate(doc, start=1):
        for row in _lines(page):
            y = row[0]["bbox"][1]
            for s in row:
                text, font, size, x = s["text"].strip(), s["font"], s["size"], s["bbox"][0]
                if "Roman" in font and size >= 8.9 and (y < HEADER_Y or y > FOOTER_Y):
                    continue  # running header/footer
                if size < 6:
                    if text.isdigit() and x >= MARGIN_MAX_X:
                        marked[text] = cur  # a footnote marker in the text: the footnote belongs to this paragraph
                    continue  # superscript footnote and E-footnote markers
                if _is_footnote_mark(text, font, size, x, label_size):
                    footnote = (pno, round(size, 1))
                    note_to = marked.pop(text, None) or cur  # no marker found: the paragraph it is printed under
                    note_to.footnotes.append([])
                    continue
                if footnote and footnote[0] == pno and round(size, 1) <= footnote[1]:
                    note_to.footnotes[-1].append(text)  # the footnote runs on to the end of its page, in its own small type
                    continue
                footnote = ()
                if _is_heading(font, size):
                    prev = heading_key
                    heading_key = (pno, y, font, size)
                    continued = bool(prev and prev[0] == pno and prev[2:] == (font, size) and 0 <= y - prev[1] < 14)
                    heading_buf = heading_buf + [text] if continued else [text]
                    new_section = section if accompanying else _section_for_heading(text, section)
                    is_title = not accompanying and not continued and _section_for_heading(text, "") == "standard"
                    part_starts = new_section != section
                    if part_starts:
                        flush()
                        section = new_section
                        cur = _Para(None, section, pno, None)
                    if is_title:  # the Standard's own title (wherever it is printed) is no heading of its text
                        path, title_size = [], round(size, 1)
                    elif part_starts:  # an appendix starts its own headings, under its own heading
                        path, title_size = [(1, " ".join(heading_buf), False)], 0.0
                    elif title_size and round(size, 1) >= title_size:
                        pass  # more of the title (its subtitle lines)
                    elif continued:
                        if path:  # the heading runs over two lines
                            path[-1] = (path[-1][0], " ".join(heading_buf), path[-1][2])
                    else:
                        title_size = 0.0
                        lvl = _level(text, ranks.get(_style(font, size), len(ranks) + 1), path)
                        # an example's title stays on the path over the headings of its style that follow it ("Example 7"
                        # over its "Scenario 1"), until the next title with the same label word ("Example 8"), a heading
                        # that introduces the next example (an example title follows it) or a higher heading
                        kind = _example_kind(text, example_re)
                        # only a plain heading introduces the next example; a labelled one ("Scenario 2") is its example's
                        opens = not kind and _example_kind(next_heading.get((pno, y), ""), example_re) == (hold or (0, None))[1]
                        if hold and (lvl < hold[0] or (lvl == hold[0] and (kind == hold[1] or opens))):
                            hold = None
                        if hold and lvl == hold[0]:
                            lvl += 1
                        elif kind and not hold:
                            hold = (lvl, kind)
                        path = [p for p in path if p[0] < lvl] + [(lvl, text, bool(NUMBERED_HEADING.match(text)))]
                    heading = " ".join(heading_buf)
                    if accompanying:
                        m = IG_HEADING_RE.match(text) if len(heading_buf) == 1 else None
                        if m:  # a guidance question starts here: label it IG A.1, IG B.2, ...
                            flush()
                            cur = _Para(f"IG {m.group(1)}.{m.group(2)}", "implementation_guidance", pno, heading, path=tuple((l, h) for l, h, _ in path))
                        elif IG_TITLE_RE.match(text) and len(heading_buf) == 1:
                            # the guidance's title: the note under it (that the guidance accompanies, but is not part of, the
                            # Standard) is kept as its own block; a contents list under an earlier copy of the title is dropped
                            if cur.ref != IG_INTRO:
                                flush()
                            cur = _Para(IG_INTRO, "implementation_guidance", pno, heading, path=tuple((l, h) for l, h, _ in path))
                        elif cur.ref and cur.ref.startswith("IG ") and len(heading_buf) > 1 and cur.heading == " ".join(heading_buf[:-1]):
                            cur.heading = heading  # the heading runs over two lines
                            cur.path = tuple((l, h) for l, h, _ in path)
                        elif stub_re and stub_re.search(" ".join(cur.body)):
                            flush()  # a stub holds only its own note: text after the next heading is not part of it
                            cur = _Para(None, section, pno, heading, path=tuple((l, h) for l, h, _ in path))
                    continue
                title_size = 0.0  # text after the title: later headings are headings of the text
                if accompanying:
                    margin_label = x < MARGIN_MAX_X and font.startswith("Swift") and ACCOMPANYING_RE.match(text.rstrip("".join(RANGE_DASH)))
                    if margin_label and cur.ref and cur.ref.endswith(RANGE_DASH) and last_label and last_label[0] == pno and 0 < y - last_label[1] < 14:
                        cur.ref = f"{cur.ref}{text}"  # second half of a range label, e.g. BC2.17A–BC2.17H
                        last_label = (pno, y)
                        continue
                    if margin_label:
                        flush()
                        cur = _Para(text, accompanying_kind(text), pno, heading, path=tuple((l, h) for l, h, _ in path))
                        last_label = (pno, y)
                        continue
                    is_label = False
                else:
                    is_label = (
                        section in ("standard", "appendix_a", "appendix_b", "appendix_c")
                        and x < MARGIN_MAX_X
                        and font.startswith("Swift")
                        and (PARA_RE.match(text.rstrip("".join(RANGE_DASH))) or (section == "appendix_a" and "Bold" in font))
                    )
                if is_label:
                    if section == "appendix_a" and last_label and last_label[0] == pno and 0 < y - last_label[1] < 13:
                        cur.ref = f"{cur.ref} {text}"
                    elif cur.ref and cur.ref.endswith(RANGE_DASH) and last_label and last_label[0] == pno and 0 < y - last_label[1] < 14:
                        cur.ref = f"{cur.ref.rstrip(''.join(RANGE_DASH))}\u2013{text}"  # second half of a range label: 44LL–44MM
                    else:
                        flush()
                        cur = _Para(text, section, pno, heading, path=tuple((l, h) for l, h, _ in path))
                    last_label = (pno, y)
                    continue
                if _is_editorial(font, size, x):
                    cur.notes.append(text)
                else:
                    cur.body.append(text)
    flush()

    chunks: list[Chunk] = []
    for p in paras:
        ref = p.ref
        if p.section == "appendix_a" and ref:
            ref = f"Appendix A: {ref}"
        body = EDITORIAL_BRACKETS.sub("", _join(p.body))
        body = clean(body)
        for r, text in _split_stubs(ref, body, stub_re):
            kind = p.section if r or not accompanying else "intro"  # unlabelled text in a document published with one
            for i, part in enumerate(split_long(text, max_words)):
                chunks.append(Chunk(r, kind, p.page, p.heading, part, i, p.path))
        for lines in p.footnotes:  # under its paragraph, in the schema's form for text without a paragraph label
            if footnote_form and ref and (text := clean(_join(lines))):
                chunks.append(Chunk(footnote_form.replace("<clause>", ref), "footnote", p.page, p.heading, text, 0, p.path))
        notes = _join(p.notes)
        if notes and len(notes.split()) > 5:
            for i, part in enumerate(split_long(notes, max_words)):
                chunks.append(Chunk(ref, "note", p.page, p.heading, part, i, p.path))
    return chunks
