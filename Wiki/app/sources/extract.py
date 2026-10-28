"""Turn uploaded files / URLs into plain text + sections for note extraction."""
import io
import re
from dataclasses import dataclass

import httpx
import pymupdf
import trafilatura

from . import docx_reader, pdf_ifrs
from .text import clean, split_long

TEXT_EXT = (".txt", ".md", ".markdown")
SUPPORTED_EXT = (".pdf", ".docx") + TEXT_EXT


@dataclass
class Extracted:
    title: str
    kind: str
    text: str
    sections: list[str]
    meta: dict


def _pack(blocks: list[str], max_words: int) -> list[str]:
    """Pack text blocks into sections of roughly max_words, never splitting a block unless it alone is too long."""
    sections, buf, n = [], [], 0
    for b in blocks:
        for piece in split_long(b, max_words):
            w = len(piece.split())
            if buf and n + w > max_words:
                sections.append("\n\n".join(buf))
                buf, n = [], 0
            buf.append(piece)
            n += w
    if buf:
        sections.append("\n\n".join(buf))
    return sections


def _blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def _title_from(name: str) -> str:
    return re.sub(r"\.[a-z0-9]+$", "", name, flags=re.I).replace("_", " ").strip()


def _outline(chunks) -> list[str]:
    """Numbered headings in document order (e.g. "6.4 Qualifying criteria for hedge accounting")."""
    out: list[str] = []
    for c in chunks:
        h = (c.heading or "").strip()
        if re.match(r"^[A-Z]?\d+(\.\d+)*\s", h) and h not in out:
            out.append(h)
    return out


# How each kind of paragraph from a document published with a Standard is marked in the text the wiki is built from
KIND_LABELS = {
    "example": "Illustrative example",
    "implementation_guidance": "Implementation guidance",
    "basis_for_conclusions": "Basis for Conclusions",
    "dissenting_opinion": "Dissenting opinion",
}
UNRECOGNISED_IFRS = ("This PDF looks like an IFRS publication, but its paragraph numbering was not recognised: "
                     "the text was kept page by page, without paragraph numbers.")
NOT_IFRS = "This PDF does not have the IFRS layout: the text was kept page by page, without paragraph numbers."


def _example_heads(chunks, example_re) -> list[str]:
    """Each chunk's example heading: its own heading when that carries one of the wiki schema's example labels
    ("Example 1—<title>"). A chunk under some other heading gets none: the reader cannot tell a sub-heading of the same
    example ("Fact pattern") from the start of something new, and a wrong name is worse than none."""
    return [h if example_re and c.source_type != "footnote" and (h := (c.heading or "").strip()) and example_re.search(h)
            else "" for c in chunks]  # a footnote is not part of the example it is printed in


def _with_head(content: str, head: str) -> str:
    return f"{head}: {content}" if head and not content.startswith(head) else content


def from_pdf(name: str, data: bytes, max_words: int, example_re=None, stub_re=None, footnote_form=None) -> Extracted:
    doc = pymupdf.open(stream=data, filetype="pdf")
    meta = {"pages": doc.page_count, **{k: v for k, v in (doc.metadata or {}).items() if v}}
    chunks, layout = pdf_ifrs.parse_document(doc, stub_re=stub_re, footnote_form=footnote_form, example_re=example_re)
    if layout == "standard":
        # Binding text only, labelled by paragraph number so notes can cite it
        chunks = [c for c in chunks if c.source_type in ("standard", "appendix_a", "appendix_b", "footnote")]
        heads = _example_heads(chunks, example_re)
        blocks = [f"[{c.para_ref or 'p' + str(c.page)}] {_with_head(c.content, h if not (stub_re and stub_re.match(c.content)) else "")}" for c, h in zip(chunks, heads)]
        meta["parser"] = "ifrs"
        meta["headings"] = [(c.heading or "").strip() for c in chunks]  # one per block, for routing to schema sections
        meta["outline"] = _outline(chunks)
        meta["para_kinds"] = {c.para_ref: c.source_type for c in chunks if c.para_ref}
        meta["heading_paths"] = [[list(x) for x in c.heading_path] for c in chunks]  # one per block, top heading first
    elif layout == "accompanying":
        # Parts B and C: numbered paragraphs, each marked with its kind (never presented as a requirement)
        chunks = [c for c in chunks if c.source_type in KIND_LABELS or c.source_type == "footnote"]
        heads = _example_heads(chunks, example_re)
        blocks = [f"[{c.para_ref}] " + (f"({KIND_LABELS[c.source_type]}) " if c.source_type in KIND_LABELS else "")
                  + _with_head(c.content, h if not (stub_re and stub_re.match(c.content)) else "") for c, h in zip(chunks, heads)]
        meta["parser"] = "ifrs_accompanying"
        meta["headings"] = [(c.heading or "").strip() for c in chunks]
        meta["kinds"] = [c.source_type for c in chunks]
        meta["para_kinds"] = {c.para_ref: c.source_type for c in chunks if c.para_ref}
        meta["heading_paths"] = [[list(x) for x in c.heading_path] for c in chunks]
        meta["outline"] = _outline(chunks)
    else:
        blocks = [f"[page {i}]\n{p.get_text()}" for i, p in enumerate(doc, start=1) if p.get_text().strip()]
        meta["parser"] = "pdf"
        meta["warnings"] = [UNRECOGNISED_IFRS if pdf_ifrs.looks_like_ifrs(doc) else NOT_IFRS]
    text = "\n\n".join(blocks)
    return Extracted(_title_from(name), "pdf", text, _pack(blocks, max_words), meta)


def from_docx(name: str, data: bytes, max_words: int, control_headers: list[str] | None = None) -> Extracted:
    """A Word paper as labelled passages: each with its location (heading path, "Cover", "Document control"); what
    kind of passage each is (table, footnote, note, comment) is kept apart, in meta (see docx_reader)."""
    title, blocks, meta = docx_reader.read(data, control_headers)
    return Extracted(title or _title_from(name), "docx", "\n\n".join(blocks), _pack(blocks, max_words), meta)


def from_text(name: str, data: bytes, max_words: int, title: str | None = None) -> Extracted:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    kind = "markdown" if name.lower().endswith((".md", ".markdown")) else "text"
    if not title and kind == "markdown":
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else None
    return Extracted(title or _title_from(name), kind, text, _pack(_blocks(text), max_words), {})


async def from_url(url: str, max_words: int) -> Extracted:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; llm-wiki/0.1; +https://github.com/)", "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        ex = from_pdf(url.rsplit("/", 1)[-1] or "document.pdf", resp.content, max_words)
        ex.kind = "url"
        return ex
    html = resp.text
    text = trafilatura.extract(html, output_format="markdown", include_tables=True, include_links=False) or ""
    if not text.strip():
        raise ValueError("Could not extract readable text from URL")
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else None) or url
    return Extracted(title, "url", text, _pack(_blocks(text), max_words), {"url": url, "content_type": ctype})


def opening_text(name: str, data: bytes, pages: int = 3, chars: int = 6000) -> str:
    """The first pages of an upload as plain text (with a PDF's own title, author and subject), so the document's
    issuer, edition and part can be read from its title page."""
    if name.lower().endswith(".pdf"):
        doc = pymupdf.open(stream=data, filetype="pdf")
        info = "\n".join(f"{k}: {v}" for k, v in (doc.metadata or {}).items() if k in ("title", "author", "subject") and v)
        text = "\n\n".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))
        return (f"[PDF properties]\n{info}\n\n" if info else "") + text[:chars]
    return from_upload(name, data, 3000).text[:chars]


def from_upload(name: str, data: bytes, max_words: int, example_re=None, stub_re=None, footnote_form=None,
                control_headers: list[str] | None = None) -> Extracted:
    """example_re: the wiki schema's example labels, so the issuer's example headings are kept with their paragraphs.
    stub_re: its stub forms, so a stub inside the text is read as its own paragraph.
    footnote_form: its citation form for a footnote, so footnotes are kept under their paragraph."""
    low = name.lower()
    if low.endswith(".pdf"):
        return from_pdf(name, data, max_words, example_re, stub_re, footnote_form)
    if low.endswith(".docx"):
        return from_docx(name, data, max_words, control_headers)
    if low.endswith(TEXT_EXT):
        return from_text(name, data, max_words)
    raise ValueError(f"Unsupported file type. Supported: {', '.join(SUPPORTED_EXT)}")
