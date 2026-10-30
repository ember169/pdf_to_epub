"""Deterministic PDF fixture generator.

Usage: python tests/fixtures/make_fixtures.py [OUT_DIR]

Each fixture has a `Spec` describing what a correct conversion must contain, so tests
stay in sync with the generator.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle

W, H = A4
LOREM = [
    "The quick brown fox jumps over the lazy dog while the river quietly winds through the valley below.",
    "Every morning the villagers gathered at the market to trade grain, wool and stories about distant travellers.",
    "A careful reader notices that small details often carry the weight of the whole narrative in unexpected ways.",
    "Engineers measured the bridge twice because the first estimate disagreed with the surveyor's handwritten notes.",
    "Winter arrived early that year and the lake froze over before the last of the apples had been picked.",
    "She wrote the letter three times, each version shorter than the last, until only the essential sentence remained.",
]


@dataclass
class Spec:
    name: str
    body: list[str] = field(default_factory=list)       # phrases that must appear in the XHTML text
    headings: list[str] = field(default_factory=list)   # must appear inside h1-h6
    absent: list[str] = field(default_factory=list)     # running header/footer text that must be dropped
    ocr: bool = False                                   # needs tesseract
    error: bool = False                                 # conversion must raise ConversionError
    min_chapters: int = 1


def _canvas(path: Path) -> Canvas:
    return Canvas(str(path), pagesize=A4, invariant=1, pageCompression=0)


def _wrap(c: Canvas, text: str, x: float, y: float, width: float, font="Times-Roman", size=11, lead=14) -> float:
    """Draw wrapped text, return new y."""
    words, line = text.split(), ""
    for w in words:
        trial = f"{line} {w}".strip()
        if c.stringWidth(trial, font, size) > width:
            c.setFont(font, size)
            c.drawString(x, y, line)
            y -= lead
            line = w
        else:
            line = trial
    if line:
        c.setFont(font, size)
        c.drawString(x, y, line)
        y -= lead
    return y


def _para(c, text, y, x=72, width=W - 144, **kw) -> float:
    return _wrap(c, text, x, y, width, **kw) - 8


def single_column(path: Path) -> Spec:
    c = _canvas(path)
    c.setTitle("Single Column Sample")
    c.setAuthor("Test Author")
    y = H - 100
    c.setFont("Helvetica-Bold", 24); c.drawString(72, y, "Chapter One: Beginnings"); y -= 40
    for t in LOREM[:3]:
        y = _para(c, t * 2, y)
    c.setFont("Helvetica-Bold", 16); c.drawString(72, y - 6, "A Closer Look"); y -= 34
    for t in LOREM[3:5]:
        y = _para(c, t * 2, y)
    c.setFont("Helvetica-Bold", 13); c.drawString(72, y - 6, "Minor Observations"); y -= 30
    y = _para(c, LOREM[5] * 2, y)
    c.showPage()
    y = H - 100
    c.setFont("Helvetica-Bold", 24); c.drawString(72, y, "Chapter Two: Continuations"); y -= 40
    for t in LOREM:
        y = _para(c, t * 2, y)
    c.showPage(); c.save()
    return Spec("single_column",
                body=[LOREM[0], LOREM[2], LOREM[5]],
                headings=["Chapter One: Beginnings", "A Closer Look", "Minor Observations", "Chapter Two: Continuations"],
                min_chapters=2)


def two_column(path: Path) -> Spec:
    c = _canvas(path)
    col_w = (W - 144 - 24) / 2
    left = ["LEFTCOL " + t for t in LOREM[:3]]
    right = ["RIGHTCOL " + t for t in LOREM[3:]]
    c.setFont("Helvetica-Bold", 22); c.drawString(72, H - 80, "Two Column Article")
    for x, paras in ((72, left), (72 + col_w + 24, right)):
        y = H - 130
        for t in paras:
            y = _para(c, t * 2, y, x=x, width=col_w, size=10, lead=13)
    c.showPage(); c.save()
    # reading order: all left-column text before any right-column text
    return Spec("two_column", body=[f"LEFTCOL {LOREM[0]}"[:60], f"RIGHTCOL {LOREM[3]}"[:60]],
                headings=["Two Column Article"])


def header_footer(path: Path) -> Spec:
    c = _canvas(path)
    for p in range(1, 7):
        c.setFont("Times-Italic", 9)
        c.drawString(72, H - 40, "RUNNING HEADER Annual Report")
        c.drawCentredString(W / 2, 30, f"Page {p}")
        c.drawRightString(W - 72, 30, "FOOTER Confidential")
        y = H - 100
        if p == 1:
            c.setFont("Helvetica-Bold", 22); c.drawString(72, y, "Annual Report"); y -= 40
        for i in range(4):
            y = _para(c, f"Section {p}.{i}: " + LOREM[(p + i) % 6] * 2, y)
        c.showPage()
    c.save()
    return Spec("header_footer", body=[LOREM[1]], headings=["Annual Report"],
                absent=["RUNNING HEADER", "FOOTER Confidential", "Page 3"])


def hyphenated(path: Path) -> Spec:
    c = _canvas(path)
    y = H - 100
    c.setFont("Helvetica-Bold", 20); c.drawString(72, y, "Hyphenation"); y -= 40
    lines = ["The committee reached an extraor-", "dinary agreement on the unbelievable", "responsibil-",
             "ity of every participant in the project, and the", "documenta-", "tion was filed promptly."]
    # three paragraphs each broken across lines with a trailing hyphen
    paras = [["The committee reached an extraor-", "dinary agreement after long discussion of the", "matter at hand."],
             ["Everyone accepted responsibil-", "ity for the outcome, and the final documenta-", "tion was filed promptly."]]
    c.setFont("Times-Roman", 11)
    for para in paras:
        for ln in para:
            c.drawString(72, y, ln); y -= 14
        y -= 10
    c.showPage(); c.save()
    return Spec("hyphenated", body=["extraordinary agreement", "responsibility for the outcome", "documentation was filed"],
                headings=["Hyphenation"])


def footnotes(path: Path) -> Spec:
    c = _canvas(path)
    y = H - 100
    c.setFont("Helvetica-Bold", 20); c.drawString(72, y, "Notes and Footnotes"); y -= 40
    y = _para(c, "The treaty was signed in a small town near the coast. " + LOREM[0] + " The signing ceremony was brief.", y)
    c.setFont("Times-Roman", 7); c.drawString(72 + 300, y + 22, "1")
    y = _para(c, LOREM[1] + " Historians still debate the exact date.", y)
    c.setStrokeColor(colors.black); c.line(72, 110, 200, 110)
    c.setFont("Times-Roman", 8)
    c.drawString(72, 98, "1 FOOTNOTETEXT The treaty text survives only in a later copy held by the archive.")
    c.showPage(); c.save()
    return Spec("footnotes", body=["The treaty was signed in a small town", "FOOTNOTETEXT"], headings=["Notes and Footnotes"])


def lists(path: Path) -> Spec:
    c = _canvas(path)
    y = H - 100
    c.setFont("Helvetica-Bold", 20); c.drawString(72, y, "Shopping Lists"); y -= 36
    y = _para(c, "Things we need before the expedition leaves on Friday morning:", y)
    items = ["Waterproof tents for the whole group", "Three weeks of dried provisions", "A reliable satellite phone"]
    for it in items:
        c.setFont("Times-Roman", 11); c.drawString(86, y, "•"); c.drawString(104, y, it); y -= 16
    y -= 12
    y = _para(c, "The order of the stages is then:", y)
    for n, it in enumerate(["Gather the equipment", "Drive to the trailhead", "Climb to base camp"], 1):
        c.setFont("Times-Roman", 11); c.drawString(86, y, f"{n}."); c.drawString(108, y, it); y -= 16
    c.showPage(); c.save()
    return Spec("lists", body=["Waterproof tents for the whole group", "Drive to the trailhead"], headings=["Shopping Lists"])


def table(path: Path) -> Spec:
    c = _canvas(path)
    y = H - 100
    c.setFont("Helvetica-Bold", 20); c.drawString(72, y, "Quarterly Figures"); y -= 36
    y = _para(c, "The table below summarises revenue by region for the last financial year.", y)
    data = [["Region", "Revenue", "Growth"], ["Northland", "1200", "4%"], ["Southland", "980", "7%"], ["Eastland", "1430", "2%"]]
    t = Table(data, colWidths=[140, 100, 100])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    tw, th = t.wrapOn(c, W, H)
    t.drawOn(c, 72, y - th)
    y -= th + 30
    _para(c, "Figures are rounded to the nearest thousand units.", y)
    c.showPage(); c.save()
    return Spec("table", body=["Northland", "Southland", "Eastland", "rounded to the nearest thousand"], headings=["Quarterly Figures"])


def _png(w=400, h=240) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (240, 240, 250))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 20):
        d.line([(i, 0), (w - i, h)], fill=(40 + i % 200, 90, 160), width=3)
    d.rectangle([10, 10, w - 10, h - 10], outline=(0, 0, 0), width=4)
    buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()


def image(path: Path) -> Spec:
    from reportlab.lib.utils import ImageReader
    c = _canvas(path)
    y = H - 100
    c.setFont("Helvetica-Bold", 20); c.drawString(72, y, "Illustrated Page"); y -= 36
    y = _para(c, "Text before the picture. " + LOREM[2], y)
    c.drawImage(ImageReader(io.BytesIO(_png())), 72, y - 240, width=400, height=240)
    y -= 270
    _para(c, "Text after the picture. " + LOREM[4], y)
    c.showPage(); c.save()
    return Spec("image", body=["Text before the picture.", "Text after the picture."], headings=["Illustrated Page"])


def scanned(path: Path) -> Spec:
    """Text rendered into a raster image; page has no text layer."""
    src = path.with_suffix(".src.pdf")
    c = _canvas(src)
    y = H - 100
    c.setFont("Helvetica-Bold", 28); c.drawString(72, y, "Scanned Document"); y -= 50
    for t in ["This page was scanned from paper and has no text layer at all.",
              "Optical character recognition must recover these words reliably."]:
        y = _para(c, t, y, size=16, lead=22)
    c.showPage(); c.save()
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    doc = pdfium.PdfDocument(str(src))
    pil = doc[0].render(scale=300 / 72).to_pil().convert("L")
    doc.close()
    src.unlink()
    buf = io.BytesIO(); pil.save(buf, "PNG")
    out = _canvas(path)
    out.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, width=W, height=H)
    out.showPage(); out.save()
    return Spec("scanned", body=["Optical character recognition", "no text layer"], headings=[], ocr=True)


def encrypted(path: Path) -> Spec:
    tmp = path.with_suffix(".plain.pdf")
    c = _canvas(tmp); _para(c, "Secret contents. " + LOREM[0], H - 100); c.showPage(); c.save()
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(tmp))
    w.encrypt(user_password="user", owner_password="owner", algorithm="AES-256")
    with open(path, "wb") as f:
        w.write(f)
    tmp.unlink()
    return Spec("encrypted", error=True)


def corrupt(path: Path) -> Spec:
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ngarbage \x00\x01\x02 not a real pdf\n")
    return Spec("corrupt", error=True)


BUILDERS: dict[str, Callable[[Path], Spec]] = {
    f.__name__: f for f in (single_column, two_column, header_footer, hyphenated, footnotes, lists,
                            table, image, scanned, encrypted, corrupt)
}


def build(name: str, out_dir: Path) -> tuple[Path, Spec]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.pdf"
    return path, BUILDERS[name](path)


def build_all(out_dir: Path) -> dict[str, tuple[Path, Spec]]:
    return {n: build(n, out_dir) for n in BUILDERS}


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
    for n, (p, _) in build_all(out).items():
        print(p)
