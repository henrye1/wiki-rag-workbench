"""The saved rubric as a Word document, laid out like the Rubric review screen: per topic its version, key points
(ID, point, tag) with their approval, and the exact-match facts with theirs."""
import datetime as dt
import io

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

TAG_LABEL = {"standard": "Standard (Part A)", "supporting": "Supporting (Part B/C)", "beyond_standard": "Beyond standard"}
GREY, GREEN = RGBColor(0x60, 0x60, 0x60), RGBColor(0x2E, 0x7D, 0x32)


def _when(t) -> str:
    return t.strftime("%-d %b %Y, %H:%M") if t else ""


def _status(p, approved_at, label_none="not yet reviewed"):
    r = p.add_run(f"approved {_when(approved_at)}" if approved_at else label_none)
    r.font.size, r.font.color.rgb = Pt(9), GREEN if approved_at else GREY


def _shade(cell, hex_fill: str):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"), sh.set(qn("w:color"), "auto"), sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def build(reference_name: str, ref_sha: str, topics: list[dict], filters: str, counts: tuple[int, int, int]) -> bytes:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10)
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
    doc.add_heading("Rubric review", 0)
    p = doc.add_paragraph()
    p.add_run(f"Reference file: {reference_name}").bold = True
    p.add_run(f"\nFingerprint (SHA-256): {ref_sha}\nExported {dt.datetime.now().strftime('%-d %b %Y, %H:%M')}")
    n_topics, n_points, n_facts = counts
    p.add_run(f"\n{n_points} of {n_topics} topics' key points approved · {n_facts} fact lists approved")
    if filters:
        p.add_run(f"\nShown: {filters}").italic = True
    p = doc.add_paragraph("Tags: Standard (Part A) is the Standard's own text; Supporting (Part B/C) is application and "
                          "implementation guidance; Beyond standard is practice, regulation or opinion not in the Standard.")
    p.runs[0].font.size, p.runs[0].font.color.rgb = Pt(9), GREY

    for t in topics:
        doc.add_heading(f"{t['topic_number']}. {t['topic_title']}", 2)
        p = doc.add_paragraph()
        r = p.add_run(f"version {t.get('version') or 1}")
        r.font.size, r.font.color.rgb = Pt(9), GREY

        p = doc.add_paragraph()
        p.add_run(f"Key points ({len(t['points'])})").bold = True
        p.add_run("   ")
        _status(p, t.get("reviewed_at"))
        if t["points"]:
            tbl = doc.add_table(rows=1, cols=3)
            tbl.style, tbl.alignment = "Table Grid", WD_TABLE_ALIGNMENT.LEFT
            for cell, head in zip(tbl.rows[0].cells, ("ID", "Key point", "Tag")):
                cell.text = ""
                cell.paragraphs[0].add_run(head).bold = True
                _shade(cell, "EEEEEE")
            for kp in t["points"]:
                row = tbl.add_row().cells
                row[0].text, row[1].text = kp["id"], kp["point"]
                row[2].text = TAG_LABEL.get(kp.get("kind"), kp.get("kind") or "") + (f"\n{kp['ref']}" if kp.get("ref") else "")
            tbl.autofit = False
            widths = (Cm(1.3), Cm(12.2), Cm(3.5))  # the page is 17 cm wide between the margins
            grid = tbl._tbl.tblGrid
            for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
                gc.set(qn("w:w"), str(int(w.twips)))
            for row in tbl.rows:
                for cell, w in zip(row.cells, widths):
                    cell.width = w
        else:
            doc.add_paragraph("No key points with this tag.").runs[0].italic = True

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.add_run("Exact-match facts").bold = True
        p.add_run("   ")
        facts = t.get("facts")
        _status(p, t.get("facts_reviewed_at") if facts is not None else None, "not made yet" if facts is None else "not yet reviewed")
        if facts is None:
            q = doc.add_paragraph("The judge makes this list on the first run after the answer checks are added.")
            q.runs[0].font.size, q.runs[0].font.color.rgb = Pt(9), GREY
        for f in facts or []:
            q = doc.add_paragraph(style="List Bullet")
            q.add_run(f"{f['id']}  ").bold = True
            q.add_run(f["fact"])
            if f.get("kind") or f.get("ref"):
                r = q.add_run("  (" + ", ".join(x for x in (TAG_LABEL.get(f.get("kind"), f.get("kind")), f.get("ref")) if x) + ")")
                r.font.size, r.font.color.rgb = Pt(9), GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
