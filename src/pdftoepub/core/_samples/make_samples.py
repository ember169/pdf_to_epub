"""Generate synthetic sample PDFs (reportlab) used by the core tests and for manual checks.

    python -m pdftoepub.core._samples.make_samples OUTDIR
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                Preformatted, Spacer, Table, TableStyle)

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore "
    "magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo "
    "consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
)
THE = (
    "The quick brown fox jumps over the lazy dog and the reader of this book is invited to follow the story that "
    "unfolds in the pages ahead, where every chapter adds a little more to what the author wants to say about the "
    "world and the people who live in it. This sentence exists mostly to fill lines with ordinary English words."
)


FOOTNOTES = [
    "This first note explains a point that the main text only hints at.",
    "A second remark on method, with a pointer to the literature.",
    "Third, a clarification about terminology used above.",
    "The fourth note mentions an exception to the rule.",
    "Finally a caveat regarding the data that were available.",
]


def _image_bytes(w=400, h=240) -> io.BytesIO:
    from PIL import Image as PI, ImageDraw

    im = PI.new("RGB", (w, h), (230, 240, 255))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 20):
        d.line([(i, 0), (w - i, h)], fill=(40, 80 + i % 150, 160), width=3)
    d.rectangle([5, 5, w - 6, h - 6], outline=(0, 0, 0), width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf


def styles():
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["Normal"], fontName="Times-Roman", fontSize=11, leading=14, alignment=TA_JUSTIFY,
                          spaceAfter=6)
    indent = ParagraphStyle("indent", parent=body, firstLineIndent=18, spaceAfter=0)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=24, leading=28, spaceAfter=14)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=18, spaceBefore=10, spaceAfter=6)
    quote = ParagraphStyle("quote", parent=body, leftIndent=36, rightIndent=36, fontName="Times-Italic")
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=24, bulletIndent=8, spaceAfter=2)
    code = ParagraphStyle("code", parent=ss["Code"], fontName="Courier", fontSize=9, leading=11)
    return dict(body=body, indent=indent, h1=h1, h2=h2, quote=quote, bullet=bullet, code=code, title=ss["Title"])


def _header_footer(title: str):
    def draw(c, doc):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.drawString(2 * cm, A4[1] - 1.3 * cm, title)
        c.drawRightString(A4[0] - 2 * cm, A4[1] - 1.3 * cm, "Running header")
        c.drawCentredString(A4[0] / 2, 1.2 * cm, f"Page {doc.page}")
        c.restoreState()

    return draw


def make_book(path: Path, outline: bool = True, chapters: int = 3) -> Path:
    """Single-column book: title, chapters (h1/h2), lists, quote, table, code, image, link, header/footer, bookmarks."""
    st = styles()
    doc = BaseDocTemplate(str(path), pagesize=A4, title="Sample Book", author="Jane Doe",
                          leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.5 * cm, bottomMargin=2.5 * cm)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_header_footer("Sample Book"))])
    story = [Paragraph("Sample Book", st["title"]), Paragraph("by Jane Doe", st["body"]), PageBreak()]
    key = 0
    for ch in range(1, chapters + 1):
        title = f"Chapter {ch}: The Story Part {ch}"
        story.append(_Bookmark(f"ch{ch}", title, 0, outline))
        story.append(Paragraph(title, st["h1"]))
        story.append(Paragraph(THE + " " + LOREM, st["body"]))
        story.append(Paragraph(f"Section {ch}.1 First ideas", st["h2"]))
        story.append(_Bookmark(f"ch{ch}s1", f"Section {ch}.1 First ideas", 1, outline))
        for k in range(3):
            story.append(Paragraph(("This is <b>bold text</b> and <i>italic text</i>. " if k == 0 else "") + THE + " " + LOREM, st["indent"]))
        story.append(Paragraph("A quotation follows. " * 1 + "It is set in italics and indented on both sides.", st["body"]))
        story.append(Paragraph("“To be, or not to be, that is the question: whether it is nobler in the mind to suffer the slings "
                               "and arrows of outrageous fortune.”", st["quote"]))
        story.append(Paragraph("Here is a list of things:", st["body"]))
        for t in ("first bullet item with some text", "second bullet item that is considerably longer so that it wraps onto "
                  "a second line in the page to check that hanging indents are joined properly", "third item"):
            story.append(Paragraph(t, st["bullet"], bulletText="•"))
        story.append(Spacer(1, 8))
        for n, t in enumerate(("Preheat the oven.", "Mix the flour and the eggs together until smooth.", "Bake for an hour."), 1):
            story.append(Paragraph(t, st["bullet"], bulletText=f"{n}."))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Section {ch}.2 Data and code", st["h2"]))
        data = [["Name", "Qty", "Price"], ["Apple", "3", "1.20"], ["Pear", "10", "0.80"], ["Plum", "7", "2.10"]]
        t = Table(data)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
        story += [t, Spacer(1, 10)]
        story.append(Preformatted("def hello():\n    print('hello')\n    return 42", st["code"]))
        story.append(Spacer(1, 10))
        story.append(KeepTogether([Image(_image_bytes(), width=8 * cm, height=4.8 * cm),
                                   Paragraph("Figure %d. A synthetic test picture." % ch, st["body"])]))
        story.append(Paragraph('See <a href="https://example.com/docs" color="blue">the docs</a> and '
                               f'<a href="#ch1" color="blue">chapter 1</a>. ' + LOREM, st["body"]))
        for _ in range(4):
            story.append(Paragraph(THE + " " + LOREM + " " + THE, st["indent"]))
        story.append(PageBreak())
    doc.multiBuild(story)
    return path


class _Bookmark(Spacer):
    def __init__(self, name, title, level, outline=True):
        super().__init__(0, 0)
        self.name, self.title, self.level, self.outline = name, title, level, outline

    def draw(self):
        self.canv.bookmarkPage(self.name)
        if self.outline:
            self.canv.addOutlineEntry(self.title, self.name, self.level, closed=False)


def make_twocol(path: Path) -> Path:
    """Two-column article: spanning title, running header/footer, superscript footnote refs with footnotes, an image."""
    st = styles()
    W, H = A4
    lm, tm, bm = 2 * cm, 3 * cm, 3.2 * cm
    gut = 0.8 * cm
    colw = (W - 2 * lm - gut) / 2
    doc = BaseDocTemplate(str(path), pagesize=A4, title="Two Column Article", author="J. Smith")

    def on_page(c, d):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.drawString(lm, H - 1.3 * cm, "Journal of Synthetic Tests")
        c.drawCentredString(W / 2, 1.2 * cm, str(d.page))
        c.setLineWidth(0.4)
        c.line(lm, 2.9 * cm, lm + 4 * cm, 2.9 * cm)
        c.setFont("Times-Roman", 8)
        c.drawString(lm, 2.5 * cm, "1")
        c.drawString(lm + 0.35 * cm, 2.5 * cm, FOOTNOTES[(d.page - 1) % len(FOOTNOTES)])
        c.restoreState()

    first_h = H - tm - bm - 3.6 * cm
    f_title = Frame(lm, H - tm - 3.0 * cm + 0.5 * cm, W - 2 * lm, 3.0 * cm, id="t", leftPadding=0, rightPadding=0)
    cols1 = [Frame(lm + i * (colw + gut), bm, colw, first_h + 0.3 * cm, id=f"a{i}", leftPadding=0, rightPadding=0) for i in range(2)]
    cols = [Frame(lm + i * (colw + gut), bm, colw, H - tm - bm + 1.2 * cm, id=f"b{i}", leftPadding=0, rightPadding=0) for i in range(2)]
    doc.addPageTemplates([PageTemplate(id="first", frames=[f_title] + cols1, onPage=on_page, autoNextPageTemplate="rest"),
                          PageTemplate(id="rest", frames=cols, onPage=on_page)])
    body = ParagraphStyle("b", fontName="Times-Roman", fontSize=10, leading=12.5, alignment=TA_JUSTIFY, spaceAfter=0, firstLineIndent=10)
    h2 = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=8, spaceAfter=4)
    ttl = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=1, spaceAfter=6)
    auth = ParagraphStyle("a", fontName="Helvetica", fontSize=10, leading=12, alignment=1)
    story = [Paragraph("A Study of Two-Column Layouts", ttl), Paragraph("J. Smith", auth), _FrameBreak()]
    for sec in range(1, 5):
        story.append(Paragraph(f"{sec}. Section number {sec}", h2))
        for k in range(5):
            sup = '<super>1</super>'
            story.append(Paragraph(f"{THE}{sup} {LOREM} {THE}", body))
        if sec == 2:
            story.append(Spacer(1, 6))
            story.append(Image(_image_bytes(), width=colw, height=colw * 0.6))
            story.append(Paragraph("Figure 1. A picture inside a column.", body))
    doc.build(story)
    return path


from reportlab.platypus.doctemplate import FrameBreak as _FrameBreak  # noqa: E402


def make_scanned(path: Path, src: Path) -> Path:
    """Rasterise the pages of `src` into a PDF that has images only (no text layer). Uses pypdfium2 + Pillow."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(src))
    imgs = [doc[i].render(scale=200 / 72, grayscale=True).to_pil().convert("L") for i in range(min(2, len(doc)))]
    imgs[0].save(str(path), "PDF", resolution=200, save_all=True, append_images=imgs[1:])
    return path


def make_text_scan_source(path: Path) -> Path:
    """Two simple pages of big, clean text suitable for OCR."""
    c = canvas.Canvas(str(path), pagesize=A4)
    for pg in range(2):
        c.setFont("Helvetica-Bold", 26)
        c.drawString(72, 760, f"Scanned Chapter {pg + 1}")
        c.setFont("Times-Roman", 14)
        y = 720
        lines = [("The quick brown fox jumps over the lazy dog.", "Pack my box with five dozen liquor jugs.",
                  "How vexingly quick daft zebras jump over the road."),
                 ("Sphinx of black quartz, judge my vow.", "Jackdaws love my big sphinx of quartz.",
                  "The five boxing wizards jump quickly.")][pg]
        for line in lines:
            c.drawString(72, y, line)
            y -= 20
        c.showPage()
    c.save()
    return path


def main(out: str) -> None:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    make_book(d / "book.pdf")
    make_book(d / "book_no_outline.pdf", outline=False)
    make_twocol(d / "twocol.pdf")
    src = make_text_scan_source(d / "_ocr_src.pdf")
    make_scanned(d / "scanned.pdf", src)
    print("wrote samples to", d)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples")
