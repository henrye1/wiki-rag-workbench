"""Export a chat from the Ask screen: the chosen messages, with the chosen side(s), each answer with its sources (RAG
citations) or pages read (wiki). Formats: Markdown, Word, Excel, and a print-ready page for PDF (the browser's Save as
PDF, so every character and emoji prints as shown). One reading of the answers' Markdown serves Word and the PDF page."""
import html
import io
import re
from datetime import datetime

from docx import Document
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font

SIDE_LABEL = {"rag": "RAG", "wiki": "Wiki"}
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")
INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)")
SHIFT = 3  # an answer's own headings sit below the message (2) and side (3) headings


# ---------- the export's content ----------

def slugify(s: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))[:80] or "page"


def humanize(slug: str) -> str:
    s = slug.strip().replace("-", " ")
    return s[:1].upper() + s[1:]


def plain_links(text: str, titles: dict[str, str] | None = None) -> str:
    """Wiki links read as on screen: [[slug|label]] as the label, a bare [[slug]] as the page's title (else the slug made
    readable); Markdown links keep their text."""
    titles = titles or {}
    text = WIKI_LINK.sub(lambda m: (m.group(2) or "").strip() or titles.get(slugify(m.group(1))) or humanize(m.group(1)), text or "")
    return MD_LINK.sub(lambda m: m.group(1), text)


def sources_line(side: str, p: dict) -> str:
    if side == "rag":
        refs = list(dict.fromkeys(str(s.get("para_ref") or s.get("chunk_id")) for s in p.get("sources") or []))
        return f"Sources: {', '.join(refs)}" if refs else ""
    pages = p.get("pages") or []
    names = [("Saved answer: " if x.get("saved") else "") + str(x.get("title") or x.get("slug")) + ("" if x.get("cited", True) else " (read, not cited)")
             for x in pages]
    return f"Pages read: {'; '.join(names)}" if names else ""


def build(chat: dict, messages: list[dict], sides: list[str]) -> dict:
    """The export as data: the chat's title and, per message, its heading and each chosen side's answer and sources."""
    items, n = [], 0
    for m in messages:
        summary = m.get("kind") == "summary"
        if not summary:
            n += 1
        parts = []
        for s in sides:
            p = m.get(s)
            if not p:
                continue
            where = m.get("rag_collection") if s == "rag" else m.get("wiki_slug")
            titles = {x.get("slug"): x.get("title") for x in p.get("pages") or [] if x.get("slug") and x.get("title")}
            answer = plain_links(p.get("answer") or "", titles).strip()
            if not answer:
                answer = f"(No answer: {p.get('error') or 'nothing was returned'})"
            parts.append({"side": s, "label": f"{SIDE_LABEL[s]} · {where}" if where else SIDE_LABEL[s], "answer": answer,
                          "sources": sources_line(s, p)})
        items.append({"heading": m["question"] if summary else f"Q{n}. {m['question']}", "question": m["question"],
                      "summary": summary, "number": None if summary else n, "parts": parts,
                      "missing": [SIDE_LABEL[s] for s in sides if not m.get(s)]})
    return {"title": chat.get("title") or "Chat", "date": datetime.now().strftime("%d %b %Y, %H:%M"),
            "sides": " and ".join(SIDE_LABEL[s] for s in sides), "items": items}


def filename(title: str, ext: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", title).strip().replace(" ", "-")[:80] or "chat"
    return f"{stem}.{ext}"


# ---------- Markdown ----------

def shift_headings(md: str, by: int = SHIFT) -> str:
    return re.sub(r"(?m)^(#{1,6})(\s)", lambda m: "#" * min(6, len(m.group(1)) + by) + m.group(2), md)


def to_markdown(doc: dict) -> str:
    out = [f"# {doc['title']}", "", f"_Exported {doc['date']} · {len(doc['items'])} message(s) · {doc['sides']}_", ""]
    for it in doc["items"]:
        out += [f"## {it['heading']}", ""]
        for p in it["parts"]:
            out += [f"### {p['label']}", "", shift_headings(p["answer"]), ""]
            if p["sources"]:
                out += [f"_{p['sources']}_", ""]
        if it["missing"] and not it["parts"]:
            out += [f"_Not asked on {' or '.join(it['missing'])}._", ""]
    return "\n".join(out).rstrip() + "\n"


# ---------- reading an answer's Markdown into blocks (for Word and the PDF page) ----------

def blocks(md: str) -> list[tuple]:
    """('h', level, text) · ('p', text) · ('ul'|'ol', [items]) · ('table', [rows]) · ('quote', text) · ('code', text) · ('hr',)"""
    lines, out, i = md.replace("\r\n", "\n").split("\n"), [], 0
    para: list[str] = []

    def flush():
        if para:
            out.append(("p", "\n".join(x.strip() for x in para)))  # line breaks kept: answers put a label on its own line
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(("code", "\n".join(code)))
        elif not s:
            flush()
        elif m := re.match(r"^(#{1,6})\s+(.*)$", s):
            flush()
            out.append(("h", len(m.group(1)), m.group(2).strip().rstrip("#").strip()))
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush()
            out.append(("hr",))
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?[\s:\-|]+\|?$", lines[i + 1].strip()) and "-" in lines[i + 1]:
            flush()
            rows = [s]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(("table", [[c.strip() for c in r.strip("|").split("|")] for r in rows]))
            continue
        elif re.match(r"^([-*+])\s+", s) or re.match(r"^\d+[.)]\s+", s):
            flush()
            kind = "ol" if re.match(r"^\d+[.)]\s+", s) else "ul"
            items = []
            while i < len(lines) and (m := re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", lines[i])):
                items.append(m.group(1).strip())
                i += 1
            out.append((kind, items))
            continue
        elif s.startswith(">"):
            flush()
            out.append(("quote", s.lstrip("> ").strip()))
        else:
            para.append(s)
        i += 1
    flush()
    return out


def runs(text: str) -> list[tuple[str, str]]:
    """Inline pieces: ('b'|'i'|'code'|'', text)."""
    out = []
    for piece in INLINE.split(text):
        if not piece:
            continue
        if piece[:2] in ("**", "__") and piece[-2:] == piece[:2] and len(piece) > 4:
            out.append(("b", piece[2:-2]))
        elif piece[0] == "`" and piece[-1] == "`" and len(piece) > 2:
            out.append(("code", piece[1:-1]))
        elif piece[0] in "*_" and piece[-1] == piece[0] and len(piece) > 2:
            out.append(("i", piece[1:-1]))
        else:
            out.append(("", piece))
    return out


# ---------- Word ----------

def _docx_runs(par, text: str, size: float | None = None, italic: bool = False, grey: bool = False):
    for li, line in enumerate(text.split("\n")):
        if li:
            par.add_run().add_break()
        _docx_line(par, line, size, italic, grey)


def _docx_line(par, text: str, size: float | None, italic: bool, grey: bool):
    for kind, t in runs(text):
        r = par.add_run(t)
        r.bold = kind == "b" or None
        r.italic = kind == "i" or italic or None
        if kind == "code":
            r.font.name = "Consolas"
        if size:
            r.font.size = Pt(size)
        if grey:
            r.font.color.rgb = RGBColor(0x55, 0x5B, 0x66)


def _docx_blocks(d, md: str, shift: int):
    for b in blocks(md):
        if b[0] == "h":
            d.add_heading(level=min(9, b[1] + shift)).add_run(plain_runs(b[2]))
        elif b[0] == "p":
            _docx_runs(d.add_paragraph(), b[1])
        elif b[0] in ("ul", "ol"):
            for item in b[1]:
                _docx_runs(d.add_paragraph(style="List Bullet" if b[0] == "ul" else "List Number"), item)
        elif b[0] == "table":
            rows = b[1]
            cols = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=cols)
            t.style = "Table Grid"
            for ri, r in enumerate(rows):
                for ci in range(cols):
                    cell = t.cell(ri, ci)
                    cell.text = ""
                    _docx_runs(cell.paragraphs[0], r[ci] if ci < len(r) else "", size=9.5)
                    if ri == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        elif b[0] == "quote":
            _docx_runs(d.add_paragraph(style="Quote"), b[1])
        elif b[0] == "code":
            r = d.add_paragraph().add_run(b[1])
            r.font.name, r.font.size = "Consolas", Pt(9)
        elif b[0] == "hr":
            d.add_paragraph("─" * 40)


def plain_runs(text: str) -> str:
    return "".join(t for _, t in runs(text))


def to_docx(doc: dict) -> bytes:
    d = Document()
    d.styles["Normal"].font.name, d.styles["Normal"].font.size = "Calibri", Pt(10.5)
    d.add_heading(doc["title"], level=0)
    _docx_runs(d.add_paragraph(), f"Exported {doc['date']} · {len(doc['items'])} message(s) · {doc['sides']}", size=9, grey=True)
    for it in doc["items"]:
        d.add_heading(it["heading"], level=1)
        for p in it["parts"]:
            d.add_heading(p["label"], level=2)
            _docx_blocks(d, p["answer"], shift=2)
            if p["sources"]:
                _docx_runs(d.add_paragraph(), p["sources"], size=9, italic=True, grey=True)
        if it["missing"] and not it["parts"]:
            _docx_runs(d.add_paragraph(), f"Not asked on {' or '.join(it['missing'])}.", italic=True, grey=True)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------- Excel ----------

def _cell(text: str) -> str:
    text = ILLEGAL_CHARACTERS_RE.sub("", text or "")
    return text if len(text) <= 32000 else text[:32000] + " … (cut: longer than an Excel cell holds)"


def to_xlsx(doc: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Chat"
    head = ["#", "Question", "Side", "Answer", "Sources / pages read"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for it in doc["items"]:
        num = "Summary" if it["summary"] else it["number"]
        if not it["parts"]:
            ws.append([num, _cell(it["question"]), ", ".join(it["missing"]), "(not asked)", ""])
        for p in it["parts"]:
            ws.append([num, _cell(it["question"]), p["label"], _cell(p["answer"]), _cell(p["sources"])])
    for col, width in zip("ABCDE", (9, 50, 22, 100, 50)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- print-ready page (PDF) ----------

def _html_inline(text: str) -> str:
    return "<br>".join(_html_line(line) for line in text.split("\n"))


def _html_line(text: str) -> str:
    out = []
    for kind, t in runs(text):
        t = html.escape(t)
        out.append({"b": f"<strong>{t}</strong>", "i": f"<em>{t}</em>", "code": f"<code>{t}</code>"}.get(kind, t))
    return "".join(out)


def _html_blocks(md: str, shift: int) -> str:
    out = []
    for b in blocks(md):
        if b[0] == "h":
            lvl = min(6, b[1] + shift)
            out.append(f"<h{lvl}>{_html_inline(b[2])}</h{lvl}>")
        elif b[0] == "p":
            out.append(f"<p>{_html_inline(b[1])}</p>")
        elif b[0] in ("ul", "ol"):
            out.append(f"<{b[0]}>" + "".join(f"<li>{_html_inline(x)}</li>" for x in b[1]) + f"</{b[0]}>")
        elif b[0] == "table":
            head, *body = b[1]
            out.append("<table><thead><tr>" + "".join(f"<th>{_html_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_html_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table>")
        elif b[0] == "quote":
            out.append(f"<blockquote>{_html_inline(b[1])}</blockquote>")
        elif b[0] == "code":
            out.append(f"<pre>{html.escape(b[1])}</pre>")
        elif b[0] == "hr":
            out.append("<hr>")
    return "\n".join(out)


PRINT_CSS = """
body { font: 11pt/1.45 Calibri, 'Segoe UI', Arial, sans-serif; color: #1f2328; max-width: 820px; margin: 24px auto; padding: 0 16px; background: #fff; }
h1 { font-size: 22pt; margin: 0 0 4px; } h2 { font-size: 15pt; margin: 28px 0 8px; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }
h3 { font-size: 12.5pt; margin: 18px 0 6px; color: #0b5cad; } h4, h5, h6 { font-size: 11.5pt; margin: 14px 0 4px; }
.meta, .src { color: #57606a; font-size: 9.5pt; } .src { font-style: italic; }
table { border-collapse: collapse; margin: 8px 0; width: 100%; font-size: 10pt; } th, td { border: 1px solid #d0d7de; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #f6f8fa; } pre { background: #f6f8fa; padding: 8px; white-space: pre-wrap; font-size: 9pt; } code { font-family: Consolas, monospace; }
blockquote { border-left: 3px solid #d0d7de; margin: 8px 0; padding-left: 10px; color: #57606a; }
.bar { position: sticky; top: 0; background: #fff; padding: 8px 0; border-bottom: 1px solid #d0d7de; margin-bottom: 16px; }
.bar button { font: inherit; padding: 6px 14px; cursor: pointer; }
.item { break-inside: auto; } h2, h3 { break-after: avoid; }
@media print { .bar { display: none; } body { margin: 0; max-width: none; } }
"""


def to_print_html(doc: dict) -> bytes:
    body = [f"<h1>{html.escape(doc['title'])}</h1>",
            f"<p class='meta'>Exported {html.escape(doc['date'])} · {len(doc['items'])} message(s) · {html.escape(doc['sides'])}</p>"]
    for it in doc["items"]:
        body.append(f"<div class='item'><h2>{html.escape(it['heading'])}</h2>")
        for p in it["parts"]:
            body.append(f"<h3>{html.escape(p['label'])}</h3>{_html_blocks(p['answer'], SHIFT)}")
            if p["sources"]:
                body.append(f"<p class='src'>{html.escape(p['sources'])}</p>")
        if it["missing"] and not it["parts"]:
            body.append(f"<p class='src'>Not asked on {html.escape(' or '.join(it['missing']))}.</p>")
        body.append("</div>")
    page = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(doc['title'])}</title><style>{PRINT_CSS}</style></head><body>"
            "<div class='bar'><button onclick='print()'>Save as PDF / Print</button> "
            "<span class='meta'>In the print dialog choose “Save as PDF”.</span></div>"
            + "\n".join(body) + "<script>addEventListener('load', () => setTimeout(() => print(), 300));</script></body></html>")
    return page.encode("utf-8")
