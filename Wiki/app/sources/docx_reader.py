"""Read a Word (.docx) paper into labelled passages, for uploads of Word files only.

Each passage is labelled with its location: the full path of the headings it sits under, joined by " > " (a
numbered heading, "4.2 Staging", places itself and stands alone). Text before the first heading is "Cover"; a
document control or revision history table (its header row names at least two of the wiki schema's document control
headers) is "Document control"; a table adds its own caption label ("> Table 3"). The location is only ever the
location: what kind of passage it is (table, footnote, note, comment) is kept apart from it, in the reader's record of
each passage, and a footnote or comment says so in its own first word. A footnote or comment takes the location of
the passage that carries its marker. A table of contents is left out.

The paper's title is read from the paper itself, never from the file's properties (a title entered at upload comes
before it): the cover line printed largest (a short line, not the client's own name); where the cover's lines are all
one size, a line styled as the title, else the first title line (not a sentence, not "Label: value"), else the first
heading.
"""
import io
import re

from .text import clean

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")  # "4.2 Staging", "3. Scope": the heading's number places it
CAPTION = re.compile(r"^((?:Table|Figure)\s+\d+(?:\.\d+)*)\b")  # a table's or figure's own label
LEAD = {"footnote": "Footnote", "note": "Note", "comment": "Comment"}  # a passage's own first word, where it lacks one


def _heading_level(p) -> int | None:
    """A paragraph's heading level from its style ("Heading 2" -> 2), or None for body text."""
    name = (p.style.name if p.style is not None else "") or ""
    m = re.match(r"(?i)^heading\s*(\d+)$", name.strip())
    if m:
        return int(m.group(1))
    lvl = p._p.find(f"{W}pPr/{W}outlineLvl")  # a custom style that Word treats as a heading
    if lvl is not None and (v := lvl.get(f"{W}val")) is not None and v.isdigit() and int(v) < 9:
        return int(v) + 1
    return None


def _style(p) -> str:
    return ((p.style.name if p.style is not None else "") or "").strip().lower()


def _notes(doc, part_name: str, tag: str) -> dict[str, str]:
    """Footnote or comment text by its id, read from the document's footnotes or comments part."""
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/" + part_name):
            from lxml import etree
            root = etree.fromstring(rel.target_part.blob)
            out = {}
            for n in root.iter(f"{W}{tag}"):
                nid = n.get(f"{W}id")
                text = clean(" ".join("".join(t.text or "" for t in p.iter(f"{W}t")) for p in n.iter(f"{W}p")))
                if nid and text and not (nid.lstrip("-").isdigit() and int(nid) <= 0):  # ids 0 and -1: separators
                    out[nid] = text
            return out
    return {}


def _location(path: list[str]) -> str:
    """The location of text under these headings: a numbered heading places itself; otherwise the full path."""
    if not path:
        return "Cover"
    return path[-1] if NUMBERED.match(path[-1]) else " > ".join(path)


def _is_control(rows: list[list[str]], heads: list[str]) -> bool:
    """A document control table: its header row names at least two of the schema's document control headers."""
    head = " ".join(rows[0]).casefold() if rows else ""
    return sum(1 for w in heads if re.search(rf"\b{re.escape(w.casefold())}\b", head)) >= 2


def _title_line(text: str) -> bool:
    """A cover line that can be the paper's title: a few words, not a sentence, not "Label: value"."""
    return len(text.split()) <= 15 and not re.search(r"[.:;,]$", text) and not re.match(r"^[^:]{1,30}:\s", text)


def _size(p) -> float:
    """A paragraph's largest text size in points, from its runs or else its style (0 when none is set)."""
    sizes = [r.font.size.pt for r in p.runs if r.font.size]
    style = p.style
    while not sizes and style is not None:
        sizes = [style.font.size.pt] if style.font.size else []
        style = style.base_style
    return max(sizes, default=0.0)


def read(data: bytes, control_headers: list[str] | None = None, client: str = "") -> tuple[str, list[str], dict]:
    """The paper as (title, labelled blocks, meta). Each block is "[<location>] <text>"; meta["kinds"] says, block by
    block, what kind of passage it is. control_headers: the schema's document control headers (none: no table is
    read as document control). client: who issued the paper, as recorded at upload: a cover line naming them is not
    the title."""
    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(io.BytesIO(data))
    footnotes, comments = _notes(doc, "footnotes", "footnote"), _notes(doc, "comments", "comment")
    blocks, kinds, paths, headings = [], [], [], []
    path: list[tuple[int, str]] = []  # (level, heading) from the top down
    last_caption = ""
    styled, cover, first_heading = "", [], ""  # the title candidates: styled, cover lines (text, size, title line), heading

    def add(text: str, kind: str = "", label: str | None = None):
        loc = label or _location([h for _, h in path])
        lead = LEAD.get(kind, "")
        if lead and not re.match(rf"(?i)^{lead}\b", text):
            text = f"{lead}: {text}"
        blocks.append(f"[{loc}] {text}")
        kinds.append(kind)  # running text has none: its example labels, if any, route it
        paths.append([[lvl, h] for lvl, h in path])
        headings.append(path[-1][1] if path else "")

    for el in doc.element.body.iterchildren():
        if el.tag == f"{W}p":
            p = Paragraph(el, doc)
            text = clean(p.text)
            if _style(p).startswith("toc") or not text and not el.findall(f".//{W}footnoteReference"):
                continue  # a table of contents line, or an empty paragraph
            if not path and text and not styled and _style(p) == "title":
                styled = text
            if (lvl := _heading_level(p)) is not None and text:
                first_heading = first_heading or text
                path = [x for x in path if x[0] < lvl] + [(lvl, text)]
                last_caption = ""
                continue
            if CAPTION.match(text) and ("caption" in _style(p) or len(text.split()) <= 15):
                last_caption = CAPTION.match(text).group(1)
            kind = "note" if "note" in _style(p) or re.match(r"(?i)^note\s*\d*\s*[:.–-]", text) else ""
            if text:
                if not path and len(text.split()) <= 15 and text.casefold() != client.strip().casefold():
                    cover.append((text, _size(p), _title_line(text)))
                add(text, kind)
            loc = _location([h for _, h in path])
            for ref in el.iter(f"{W}footnoteReference"):  # a footnote: where its marker is
                if (t := footnotes.get(ref.get(f"{W}id"))):
                    add(t, "footnote", loc)
            for ref in el.iter(f"{W}commentReference"):
                if (t := comments.get(ref.get(f"{W}id"))):
                    add(t, "comment", loc)
        elif el.tag == f"{W}tbl":
            t = Table(el, doc)
            rows = []
            for r in t.rows:
                cells, tcs = [], []
                for c in r.cells:  # a merged cell repeats across the row: once
                    if any(c._tc is x for x in tcs):
                        continue
                    tcs.append(c._tc)
                    cells.append(clean(c.text))
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            if _is_control(rows, control_headers or []):
                add("\n".join(" | ".join(r) for r in rows), "table", "Document control")
            else:
                loc = _location([h for _, h in path])
                add("\n".join(" | ".join(r) for r in rows), "table", f"{loc} > {last_caption}" if last_caption else None)
            last_caption = ""

    sizes = {s for _, s, _ in cover}
    if len(sizes) > 1:  # the cover's lines differ in size: the largest is the title
        title = next(x for x, s, _ in cover if s == max(sizes))
    else:
        title = styled or next((x for x, _, line in cover if line), "") or first_heading
    labels = {}
    for b, k in zip(blocks, kinds):
        lab = re.match(r"^\[([^\]]+)\]", b).group(1)
        labels.setdefault(lab, set()).add(k)
    meta = {
        "parser": "docx",
        "kinds": kinds,
        "heading_paths": paths,
        "headings": headings,
        "outline": list(dict.fromkeys(" > ".join(h for _, h in p) for p in paths if p)),
        # a location whose passages are all of one kind other than running text has that kind
        "para_kinds": {lab: next(iter(ks)) for lab, ks in labels.items() if len(ks) == 1 and next(iter(ks))},
    }
    return title, blocks, meta
