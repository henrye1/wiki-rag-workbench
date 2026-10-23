"""Layout-aware parser for IFRS Foundation annotated standards (e.g. IFRS 9 PDF).

Layout facts it relies on:
- Paragraph numbers (1.1, 5.5.3, B5.5.17) sit in the left margin in the body (Swift) font.
- Body text is indented further right than the margin.
- Editorial material ([Refer:], [Note:], [Link], IFRIC boxes, E-footnotes) uses HelveticaLTPro-BoldCond.
- Headings use HelveticaLTPro Bold/Oblique at >= 9.5pt.
- Running header/footer use HelveticaLTPro-Roman 9pt.
"""
import re
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
PLACEHOLDER = "not included in this edition"
RANGE_DASH = ("\u2013", "-")  # "BC2.17A–" continued by "BC2.17H" on the next line: a range of deleted paragraphs
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


# A numbered heading ("6.4 Qualifying criteria ...", "Chapter 6 Hedge accounting"): its level is its number's depth
NUMBERED_HEADING = re.compile(r"^(?:[A-Z][a-z]+\s+)?(\d+(?:\.\d+)*)\s+[A-Z]")


def _style(font: str, size: float) -> tuple:
    return (round(size, 1), "Bold" in font and "Obliq" not in font)


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


def accompanying_kind(ref: str) -> str:
    m = ACCOMPANYING_RE.match(ref.rstrip("".join(RANGE_DASH)))
    prefix = m.group(1) if m else ""
    return ACCOMPANYING_KINDS.get(prefix, "basis_for_conclusions" if prefix.startswith("BC") else "intro")


def parse_document(doc: pymupdf.Document, max_words: int = 500) -> tuple[list[Chunk], str]:
    """Read an IFRS PDF. A Standard (Part A) is read exactly as parse() always has; a document published with it
    (illustrative examples, implementation guidance, Basis for Conclusions: Parts B and C) by its own paragraph numbers.

    Returns (chunks, layout): layout is "standard", "accompanying", or "" when no numbered paragraphs were recognised.
    A short accompanying document can have too few numbered paragraphs for looks_like_ifrs(); it is still recognised
    by its numbering (IE, IG, BC..., DO in the IFRS margin font), but never read as a Standard.
    """
    chunks = parse(doc, max_words) if looks_like_ifrs(doc) else []
    if any(c.source_type == "standard" for c in chunks):
        return chunks, "standard"
    acc = parse(doc, max_words, accompanying=True)
    if any(c.source_type in ACCOMPANYING_TYPES for c in acc):
        return acc, "accompanying"
    return chunks, ""


def parse(doc: pymupdf.Document, max_words: int = 500, accompanying: bool = False) -> list[Chunk]:
    """accompanying=False reads a Standard (Part A); True reads a document published with one (Parts B and C)."""
    section = "intro"
    heading: str | None = None
    heading_buf: list[str] = []
    heading_key: tuple = ()
    ranks = _heading_styles(doc)
    path: list = []  # [(level, heading, numbered)], top down: the headings the current text sits under
    paras: list[_Para] = []
    cur = _Para(None, section, 1, None)
    last_label: tuple = ()  # (page, y) of last margin label, to join multi-line defined terms

    def flush():
        nonlocal cur
        if cur.body or cur.notes:
            paras.append(cur)

    for pno, page in enumerate(doc, start=1):
        for row in _lines(page):
            y = row[0]["bbox"][1]
            for s in row:
                text, font, size, x = s["text"].strip(), s["font"], s["size"], s["bbox"][0]
                if "Roman" in font and size >= 8.9 and (y < HEADER_Y or y > FOOTER_Y):
                    continue  # running header/footer
                if size < 6:
                    continue  # superscript E-footnote markers
                if _is_heading(font, size):
                    prev = heading_key
                    heading_key = (pno, y, font, size)
                    if prev and prev[0] == pno and prev[2:] == (font, size) and 0 <= y - prev[1] < 14:
                        heading_buf.append(text)
                        if path:  # the heading runs over two lines
                            path[-1] = (path[-1][0], " ".join(heading_buf), path[-1][2])
                    else:
                        heading_buf = [text]
                        lvl = _level(text, ranks.get(_style(font, size), len(ranks) + 1), path)
                        path = [p for p in path if p[0] < lvl] + [(lvl, text, bool(NUMBERED_HEADING.match(text)))]
                    new_section = section if accompanying else _section_for_heading(text, section)
                    if new_section != section:
                        flush()
                        section = new_section
                        path = [(1, " ".join(heading_buf), False)]  # a new part (an appendix) starts its own headings
                        cur = _Para(None, section, pno, None)
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
                        elif PLACEHOLDER in " ".join(cur.body):
                            flush()  # a placeholder holds only its own note: text after the next heading is not part of it
                            cur = _Para(None, section, pno, heading, path=tuple((l, h) for l, h, _ in path))
                    continue
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
                        and (PARA_RE.match(text) or (section == "appendix_a" and "Bold" in font))
                    )
                if is_label:
                    if section == "appendix_a" and last_label and last_label[0] == pno and 0 < y - last_label[1] < 13:
                        cur.ref = f"{cur.ref} {text}"
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
        if body:
            for i, part in enumerate(split_long(body, max_words)):
                chunks.append(Chunk(ref, p.section, p.page, p.heading, part, i, p.path))
        notes = _join(p.notes)
        if notes and len(notes.split()) > 5:
            for i, part in enumerate(split_long(notes, max_words)):
                chunks.append(Chunk(ref, "note", p.page, p.heading, part, i, p.path))
    return chunks
