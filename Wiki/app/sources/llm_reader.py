"""The LLM reader: a PDF's structure (headings, paragraphs, their labels and kinds, page furniture) marked by a model
(PARSER_MODEL), with the text taken word for word from the PDF's own text layer. The model is shown each page's text
lines (with their font size and weight) and only marks lines; it never writes text, so the text cannot change. What it
marks is checked: a label is kept only where the paragraph's text starts with it; a mark on a line that does not exist
is ignored and counted. The paragraphs then go through the same steps as the PDF reader's (kinds the schema leaves out,
its citation forms, headings and page labels), so the upload is written from them in the same way."""
import asyncio
import re

import pymupdf

from .. import llm, prompts
from ..config import get_settings
from . import docx_reader, extract
from .models import Chunk
from .text import clean, split_long

OWN_TEXT = "text"  # the reader's kind for the document's own text (a kind the schema's Paragraph kinds does not list)
# a table's or figure's own label at the start of a line, as the Word reader reads one, printed bare or in brackets
# ("Table 1.2: ...", "[Table 1.2] ...", "[Figure 1.1 description] ...")
CAPTION = re.compile(r"^\[?" + docx_reader.CAPTION.pattern.lstrip("^"))
CAPTION_WORDS = 15  # a bare label opens a caption line only in a line this short (as the Word reader reads a caption)


def caption_of(line: str) -> str | None:
    """The table's or figure's label a line holds, where it is that table's or figure's own label line: the label in
    brackets at its start, or a short line opening with it (not a sentence of the text that names the table)."""
    m = CAPTION.match(line)
    return m.group(1) if m and (line.startswith("[") or len(line.split()) <= CAPTION_WORDS) else None


def page_lines(page: pymupdf.Page, number: int) -> list[dict]:
    """The page's text lines in reading order: {id, text, size, bold}."""
    out = []
    for block in page.get_text("dict", sort=True)["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            size = round(max(s["size"] for s in spans), 1)
            bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
            out.append({"id": f"{number}.{len(out) + 1}", "page": number, "text": text, "size": size, "bold": bold})
    return out


def _listing(lines: list[dict]) -> str:
    return "\n".join(f"{x['id']} | {x['size']}{' bold' if x['bold'] else ''} | {x['text']}" for x in lines)


def _parts(segments: list[tuple[str, int]], max_words: int) -> list[tuple[str, int]]:
    """A paragraph's segments (its opening text and each list item or table row, with the page it starts on) packed in
    order into parts of at most max_words words, split only between segments (a segment over the limit on its own is
    split between sentences, as the PDF reader splits a long paragraph)."""
    out: list[tuple[str, int]] = []
    buf, n, page = [], 0, None
    for text, pg in segments:
        for piece in split_long(text, max_words) if len(text.split()) > max_words else [text]:
            w = len(piece.split())
            if buf and n + w > max_words:
                out.append((clean(" ".join(buf)), page))
                buf, n, page = [], 0, None
            buf.append(piece)
            n += w
            page = pg if page is None else page
    if buf:
        out.append((clean(" ".join(buf)), page))
    return out


def build(lines: list[dict], marks: list[dict], kinds: set[str], trail: list[tuple[int, str]] | None = None,
          open_chunk: Chunk | None = None, max_words: int = 500) -> tuple[list[Chunk], list[tuple[int, str]], dict, Chunk | None]:
    """The new chunks the marks make of the lines (word for word), the heading trail where they end, what was checked,
    and the paragraph they end with (which the next pages' unmarked first line continues). A list or table is part of
    the paragraph that introduces it; a paragraph over max_words is split into parts between its items. open_chunk: the
    paragraph the pages before ended with: an unmarked first line here continues it."""
    by_id = {m["line"]: m for m in marks if m.get("line")}
    ids = {x["id"] for x in lines}
    report = {"marks_unknown_line": sum(1 for k in by_id if k not in ids), "labels_not_printed": 0, "kinds_unknown": 0,
              "lines_dropped": 0, "headings": 0, "paragraphs": 0, "items": 0, "split_paragraphs": 0, "dropped": [],
              "drops_kept": [], "heading_texts": []}
    trail = list(trail or [])
    new: list[Chunk] = []
    # the element being read: a heading's lines, or a paragraph's segments (its text, then each item) with their pages
    cur = {"heading": False, "chunk": open_chunk, "segs": []} if open_chunk else None
    tail: list[Chunk | None] = [None]  # the last chunk (or last part) of the paragraph closed last

    def close():
        nonlocal cur
        if cur and cur["heading"]:
            level, text = cur["level"], clean(" ".join(cur["lines"]))
            report["heading_texts"].append({"level": level, "text": text})
            while trail and trail[-1][0] >= level:
                trail.pop()
            trail.append((level, text))
        elif cur:
            c = cur["chunk"]
            segs = ([(c.content, c.page)] if c.content else []) + [(clean(" ".join(t)), pg) for t, pg in cur["segs"] if t]
            parts = _parts(segs, max_words) or [("", c.page)]
            c.content = parts[0][0]
            tail[0] = c
            if len(parts) > 1:
                report["split_paragraphs"] += 1
                at = new.index(c) + 1 if c in new else 0
                more = [Chunk(para_ref=c.para_ref, source_type=c.source_type, page=pg, heading=c.heading, content=t,
                              part=c.part + i, heading_path=c.heading_path) for i, (t, pg) in enumerate(parts[1:], start=1)]
                for m in more:  # each part of the paragraph is cited as the paragraph is
                    m.caption = getattr(c, "caption", None)
                new[at:at] = more
                tail[0] = more[-1]
        cur = None

    def paragraph(page: int, label: str | None, kind: str, first: str) -> dict:
        c = Chunk(para_ref=label, source_type=kind, page=page, heading=trail[-1][1] if trail else None, content="",
                  heading_path=tuple(trail))
        new.append(c)
        captioned(c, first)
        return {"heading": False, "chunk": c, "segs": [([first] if first else [], page)]}

    def captioned(c: Chunk, line: str) -> None:  # the first table's or figure's label line the paragraph holds
        if not getattr(c, "caption", None) and (cap := caption_of(line)):
            c.caption = cap

    for n, x in enumerate(lines):
        m = by_id.get(x["id"]) or {}
        role = m.get("role")
        if role == "drop" and (cap := caption_of(x["text"])) and cap not in (
                lines[n + 1]["text"] if n + 1 < len(lines) else ""):
            # a table's or figure's own label is text, not furniture, unless the next line prints it again: kept as a
            # paragraph, which the table's rows or the figure's text then follow
            report["drops_kept"].append({"page": x["page"], "text": x["text"]})
            role = "paragraph"
        if role == "drop":  # page furniture: this line only
            report["lines_dropped"] += 1
            report["dropped"].append({"page": x["page"], "text": x["text"]})
        elif role == "heading":
            close()
            report["headings"] += 1
            cur = {"heading": True, "level": max(1, int(m.get("level") or 1)), "lines": [x["text"]]}
        elif role == "paragraph":
            close()
            report["paragraphs"] += 1
            label, text = (m.get("label") or "").strip(), x["text"]
            if label and not text.startswith(label):  # a label is kept only where the text is printed with it
                report["labels_not_printed"] += 1
                label = ""
            if label:
                text = text[len(label):].lstrip(" .\t")
            kind = (m.get("kind") or "").strip()
            if kind and kind not in kinds:
                report["kinds_unknown"] += 1
                kind = ""
            cur = paragraph(x["page"], label or None, kind or OWN_TEXT, text)
        elif role == "item" and cur and not cur["heading"]:  # a list item or table row of the paragraph being read
            report["items"] += 1
            cur["segs"].append(([x["text"]], x["page"]))
            captioned(cur["chunk"], x["text"])
        elif cur is None or role == "item":  # text before any mark, or a list right under a heading: a paragraph
            close()
            report["paragraphs"] += 1
            cur = paragraph(x["page"], None, OWN_TEXT, x["text"])
        elif cur["heading"]:  # a heading's next line
            cur["lines"].append(x["text"])
        else:  # a paragraph's (or its last item's) next line
            if not cur["segs"]:
                cur["segs"].append(([], x["page"]))
            cur["segs"][-1][0].append(x["text"])
            captioned(cur["chunk"], x["text"])
    ends_in_paragraph = bool(cur) and not cur["heading"]
    close()
    ends_in = tail[0] if ends_in_paragraph else None  # where split, the next pages continue its last part
    return [c for c in new if c.content or c.para_ref], trail, report, ends_in


def kinds_listed(chk) -> list[tuple[str, str]]:
    """The kinds of passage the model is offered: the schema's Paragraph kinds (the reader's name and the schema's), then
    the kinds it leaves out; none where the schema gives neither list."""
    return ([(k, v) for k, v in ((chk.kinds if chk else None) or {}).items()]
            + [(k, "left out") for k in ((chk.kinds_left_out if chk else None) or [])])


async def read(name: str, data: bytes, chk, title: str | None = None, pages: range | None = None,
               batch: int = 10) -> tuple[list[Chunk], dict]:
    """The PDF's chunks as the model marks them, batch pages per call, and the reader's record (model, calls, checks,
    token use). pages: 1-based page numbers to read (all where None)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    numbers = list(pages or range(1, doc.page_count + 1))
    kinds = kinds_listed(chk)
    usage = llm.track_usage()
    model = llm.use("parser")
    by_batch = [numbers[i:i + batch] for i in range(0, len(numbers), batch)]
    lines_of = [[ln for n in b for ln in page_lines(doc[n - 1], n)] for b in by_batch]

    async def mark(i: int) -> list[dict]:  # the batches are marked at once; trails are joined in order after
        b = by_batch[i]
        if not lines_of[i]:
            return []
        out = await llm.generate_json(prompts.READER_SYSTEM, prompts.reader_prompt(
            title or extract._title_from(name), f"{b[0]}-{b[-1]}", kinds, [], _listing(lines_of[i])), prompts.READER_SCHEMA)
        return out.get("marks") or []

    marks = await llm.gather_limited(mark(i) for i in range(len(by_batch)))
    chunks, trail, last, report = [], [], None, {}
    for i in range(len(by_batch)):
        got, trail, rep, last = build(lines_of[i], marks[i], {k for k, _ in kinds}, trail, last, get_settings().chunk_max_words)
        chunks += got
        for k, v in rep.items():
            report[k] = report.get(k, [] if isinstance(v, list) else 0) + v
    calls = [u for u in usage if u.get("step") == "json"]
    record = {"model": model, "pages": len(numbers), "calls": len(calls), "lines": sum(len(x) for x in lines_of), **report,
              "input_tokens": sum(u.get("input_tokens") or 0 for u in calls),
              "output_tokens": sum(u.get("output_tokens") or 0 for u in calls),
              "thinking_tokens": sum(u.get("thinking_tokens") or 0 for u in calls)}
    return chunks, record


def locations(chunks: list[Chunk]) -> list[str | None]:
    """Each chunk's label where the document is cited by its locations (a schema with no page-label form for text
    printed without a paragraph label): its own printed label where it has one; else, as the Word reader labels a
    passage, the full path of the headings it sits under (a numbered heading places itself), with the label of the
    table or figure whose label line it holds, wherever in it that line is ("> Table 1.2"); text under no heading, read page by page, is "page <n>". A part of a
    split paragraph has its paragraph's label."""
    out: list[str | None] = []
    for i, c in enumerate(chunks):
        if c.para_ref:
            out.append(c.para_ref)
            continue
        if c.part and i and chunks[i - 1].heading_path == c.heading_path and not chunks[i - 1].para_ref:
            out.append(out[-1])
            continue
        if not c.heading_path:
            out.append(f"page {c.page}")
            continue
        loc = docx_reader._location([h for _, h in c.heading_path])
        cap = getattr(c, "caption", None) or caption_of(c.content or "")
        out.append(f"{loc} > {cap}" if cap else loc)
    return out


def extracted(name: str, chunks: list[Chunk], record: dict, max_words: int, page_count: int, title: str | None = None,
              example_re=None, left_out: list[str] | None = None, label_forms: dict[str, str] | None = None,
              asides: dict | None = None) -> extract.Extracted:
    """The upload as the PDF reader gives one (text blocks "[<label>] <text>", sections, headings, kinds, page labels),
    from the chunks read: through the same steps, so the rest of the upload treats it alike."""
    before = list(chunks)
    chunks = extract._kept(chunks, left_out or [], label_forms or {}, asides)
    kept = {id(c) for c in chunks}
    record = {**record, "left_out": [{"page": c.page, "kind": c.source_type, "text": c.content} for c in before
                                     if id(c) not in kept]}  # by the schema's rules (kinds left out, no-content length)
    heads = extract._example_heads(chunks, example_re)
    by_page = bool(label_forms)  # the schema cites text printed without a paragraph label by its page label
    labels = [c.para_ref for c in chunks] if by_page else locations(chunks)
    labels = [lab or f"p{c.page}" for lab, c in zip(labels, chunks)]
    blocks = [f"[{lab}] {extract._with_head(c.content, h)}" for lab, c, h in zip(labels, chunks, heads)]
    meta = {"pages": page_count, "parser": "llm", "reader": record,
            "kinds": [c.source_type for c in chunks],
            "headings": [(c.heading or "").strip() for c in chunks],
            "outline": extract._outline(chunks),
            "para_kinds": {c.para_ref: c.source_type for c in chunks if c.para_ref},
            "heading_paths": [[list(x) for x in c.heading_path] for c in chunks],
            "page_labels": extract._page_labels(chunks) if by_page else sorted(
                {lab for lab, c in zip(labels, chunks) if not c.para_ref and not c.heading_path})}
    if by_page:
        for c in chunks:  # text printed without a paragraph label: its kind under its page label, as it is cited
            if not c.para_ref:
                meta["para_kinds"].setdefault(f"p{c.page}", c.source_type)
    else:  # a location whose passages are all of one kind has that kind (as the Word reader records it)
        kinds: dict[str, set[str]] = {}
        for lab, c in zip(labels, chunks):
            if not c.para_ref:
                kinds.setdefault(lab, set()).add(c.source_type)
        meta["para_kinds"].update({lab: next(iter(ks)) for lab, ks in kinds.items() if len(ks) == 1})
    return extract.Extracted(title or extract._title_from(name), "pdf", "\n\n".join(blocks), extract._pack(blocks, max_words), meta)


async def from_pdf(name: str, data: bytes, max_words: int, chk, title: str | None = None) -> extract.Extracted:
    """An upload read by the LLM reader, as from_upload gives one; its record (model, checks, what was left out, token
    use) in meta["reader"], and a warning line saying how it was read."""
    chunks, record = await read(name, data, chk, title=title)
    opts = extract.schema_options(chk)
    ex = extracted(name, chunks, record, max_words, record["pages"], title, opts["example_re"], opts["left_out"],
                   opts["label_forms"], opts["asides"])
    r = ex.meta["reader"]
    ex.meta["warnings"] = [f"Read by the LLM reader ({r['model']}): {len(chunks) - len(r['left_out'])} paragraphs under "
                           f"{r['headings']} headings; {len(r['left_out'])} passage(s) left out by the schema's rules, "
                           f"{r['lines_dropped']} line(s) of page furniture dropped"
                           + (f", {len(r['drops_kept'])} table or figure label line(s) kept" if r.get("drops_kept") else "")
                           + "."]
    return ex
