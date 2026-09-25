from fpdf import FPDF
from fpdf.enums import XPos, YPos

_REPLACE = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
            "·": "-", "…": "...", "→": "->", "✓": "v", "⚠": "!", "−": "-"}


def _t(s) -> str:
    """Core PDF fonts are Latin-1 only; map common punctuation and drop the rest."""
    s = "".join(_REPLACE.get(ch, ch) for ch in str(s))
    return s.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 8, f"Page {self.page_no()} - not proof of identity; requires human review", align="C")


def _line(pdf: FPDF, text: str, size: int = 10, style: str = "", fill: tuple | None = None):
    pdf.set_font("Helvetica", style, size)
    if fill:
        pdf.set_fill_color(*fill)
    pdf.multi_cell(0, 5, _t(text), fill=bool(fill), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def render(doc: dict) -> bytes:
    pdf = _PDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    _line(pdf, doc["title"], 16, "B")
    if doc.get("warning"):
        _line(pdf, doc["warning"], 10, "B", (255, 243, 205))
    _line(pdf, doc["notice"], 9, "", (238, 238, 255))
    for sec in doc["sections"]:
        pdf.ln(3)
        _line(pdf, sec["title"], 12, "B")
        for b in sec["blocks"]:
            if "p" in b:
                _line(pdf, b["p"])
            elif "list" in b:
                for it in b["list"]:
                    if isinstance(it, str):
                        _line(pdf, f"- {it}")
                    else:
                        _line(pdf, f"- {it['text']}")
                        for link in it.get("links", []):
                            _line(pdf, f"    {link['url']}", 8)
            else:
                t = b["table"]
                rows = t["rows"] or [["None"] + [""] * (len(t["headers"]) - 1)]
                pdf.set_font("Helvetica", "", 8)
                with pdf.table(first_row_as_headings=any(t["headers"]), line_height=4) as table:
                    if any(t["headers"]):
                        r = table.row()
                        for h in t["headers"]:
                            r.cell(_t(h))
                    for row in rows:
                        r = table.row()
                        for cell in row:
                            r.cell(_t(cell)[:600])
    return bytes(pdf.output())
