"""Mathematics: display formulas as pictures (alt text, equation number as text) or as one-row text, inline stacked
fractions as "a/b", table value columns left alone; the sentence around a display formula stays one paragraph."""
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from pdftoepub.api import ConvertOptions, convert
from pdftoepub.core import formulas
from pdftoepub.core.ir import Line, Span

XHTML = "{http://www.w3.org/1999/xhtml}"
ROOT = Path(__file__).resolve().parents[4]
CORPUS = ROOT / "tests" / ".corpus"


def _math_pdf(path):
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A5)
    W, H = A5
    y = H - 60

    def text(x, yy, s, font="Times-Roman", size=11):
        c.setFont(font, size)
        c.drawString(x, yy, s)
        return x + c.stringWidth(s, font, size)

    for s in ["Differential calculus is the art of comparing small quantities with each other,",
              "and this chapter shows how their ratio is found. We may then write at once"]:
        text(40, y, s)
        y -= 15
    # display formula: dy/dx = 5/7 x^4 . with the equation number (12) at the right margin
    y -= 22
    x = 150
    text(x, y + 8, "dy", "Times-Italic")
    text(x, y - 8, "dx", "Times-Italic")
    c.line(x - 1, y + 3.5, x + 12, y + 3.5)
    x = text(x + 16, y, "=", "Symbol")
    text(x + 5, y + 8, "5")
    text(x + 5, y - 8, "7")
    c.line(x + 4, y + 3.5, x + 11, y + 3.5)
    x = text(x + 13, y, "x", "Times-Italic")
    x = text(x, y + 4, "4", size=7)
    text(x, y, ".")
    text(W - 40 - c.stringWidth("(12)", "Times-Roman", 11), y, "(12)")
    y -= 30
    for s in ["where x is the variable of the curve, so that the slope grows with the fourth power and",
              "never stays still."]:
        text(40, y, s)
        y -= 15
    # inline stacked fraction n over z inside a text line
    y -= 6
    x = text(52, y, "Next the line K L is equal to")
    text(x + 4, y + 6, "n", "Times-Italic", 8)
    text(x + 4, y - 5, "z", "Times-Italic", 8)
    c.line(x + 3, y + 3, x + 9, y + 3)
    text(x + 12, y, "x times the length that we called the unit before.")
    y -= 15
    text(40, y, "and the construction gives the answer at once, as the old geometers did by hand.")
    y -= 15
    text(52, y, "La racine primitive de la congruence est donnée par les équations")
    # one-row display formula: x^2 = 1, (mod 7)
    y -= 26
    x = text(160, y, "x", "Times-Italic")
    x = text(x, y + 4, "2", size=7)
    x = text(x + 2, y, "=", "Symbol")
    text(x + 3, y, "1, (mod 7),")
    y -= 26
    text(40, y, "et nous n'avons besoin pour cela que d'une racine primitive de chaque congruence.")
    # a table: labels and values with super / subscripts (a column of values is not a formula)
    y -= 30
    for label, v, up, down in [("Primary black hole mass", "36", "+5", "-4"), ("Secondary black hole mass", "29", "+4", "-4"),
                               ("Final black hole mass", "62", "+4", "-4")]:
        text(40, y, label)
        x = text(250, y, v)
        text(x, y + 4, up, size=7)
        text(x, y - 3, down, size=7)
        text(x + 10, y, "M")
        y -= 18
    c.showPage()
    c.save()
    return path


def _paragraphs(epub):
    z = zipfile.ZipFile(epub)
    docs = [etree.fromstring(z.read(n)) for n in sorted(z.namelist()) if re.match(r"OEBPS/ch\d+\.xhtml", n)]
    return z, [p for d in docs for p in d.iter(XHTML + "p")]


def test_display_formulas_inline_fractions_and_tables(tmp_path):
    pdf = _math_pdf(tmp_path / "m.pdf")
    convert(pdf, tmp_path / "m.epub", ConvertOptions(ocr="off"))
    z, paras = _paragraphs(tmp_path / "m.epub")
    imgs = [(p, i) for p in paras for i in p.iter(XHTML + "img") if "formula" in (i.get("class") or "")]
    assert len(imgs) == 1
    p, img = imgs[0]
    alt = img.get("alt")
    assert "dy/dx" in alt and "5/7" in alt and "=" in alt
    assert re.search(r"width:\d+(\.\d+)?em", img.get("style") or "")
    eqno = [s for s in p.iter(XHTML + "span") if s.get("class") == "eqno"]
    assert [e.text for e in eqno] == ["(12)"]
    # one paragraph: the sentence before, the formula, and the sentence continuing after it
    text = "".join(p.itertext())
    assert "We may then write at once" in text and "where x is the variable" in text
    # the picture is a cropped grey-scale PNG within the size caps
    name = "OEBPS/" + img.get("src")
    im = Image.open(io.BytesIO(z.read(name)))
    assert im.format == "PNG" and im.mode == "L" and max(im.size) <= 1600 and im.size[0] > im.size[1] > 40
    all_text = ["".join(q.itertext()) for q in paras]
    assert any("K L is equal to n/z x times" in t for t in all_text)  # inline fraction as text
    one_row = [s for q in paras for s in q.iter(XHTML + "span") if s.get("class") == "dmath"
               and not list(s.iter(XHTML + "img"))]
    assert len(one_row) == 1
    assert "".join(one_row[0].itertext()).replace(" ", "").startswith("x2=1,(mod7)")
    assert one_row[0].find(XHTML + "sup") is not None
    assert any("équations" in t and "et nous n'avons besoin" in t for t in all_text)
    # the table's values stay text (a column of values with super / subscripts is not a formula)
    assert any(re.search(r"36\+5-4 M", t) for t in all_text) and any("Primary black hole mass" in t for t in all_text)
    # no lone formula fragments as paragraphs
    assert not [t for t in all_text if t.strip() in ("dy", "dx", "n", "z", "5", "7")]


def test_epubcheck_accepts_formula_markup(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    import epubcheck

    if not epubcheck.java_available():
        pytest.skip("java not found")
    convert(_math_pdf(tmp_path / "m.pdf"), tmp_path / "m.epub", ConvertOptions(ocr="off"))
    assert epubcheck.check(tmp_path / "m.epub", tmp_path) == []


def _l(text, x0, y0, size=10.0, **kw):
    w = 0.5 * size * len(text)
    return Line([Span(text, size, bbox=(x0, y0, x0 + w, y0 + 1.2 * size), **kw)], (x0, y0, x0 + w, y0 + 1.2 * size))


def test_fraction_pairs_pick_the_line_between_them():
    # numerator "n" is as close to the line above as to its own line: the pair decides
    lines = [_l("par même moyen je connois aussi la proportion qui est entre", 40, 100),
             _l("n", 280, 108, 7, italic=True), _l("pose comme entre n et a : si bien que K L étant", 40, 114),
             _l("x, I L est", 290, 114), _l("z", 280, 121, 7, italic=True),
             _l("le point K soit entre L et C, à cause qu'il y a ici un signe moins", 40, 128)]
    out = formulas.absorb_fractions(formulas.join_split_rows(lines), 400, 40)
    texts = [l.text for l in out]
    assert any("étant n/z x, I L est" in t for t in texts)
    assert "n" not in texts and "z" not in texts and len(out) == 3


def test_operator_boxes_from_math_fonts_do_not_decide_their_row():
    # pdfminer puts "−" (CMSY metrics) with the denominators: it still belongs to the text row
    host = Line([Span("(1) Differentiate y =", 12, bbox=(50, 80, 155, 92))], (50, 80, 155, 92))
    num = Line([Span("x", 12, bbox=(160, 70, 166, 82), italic=True), Span("5", 8, bbox=(166, 68, 170, 76), sup=True),
                Span(" ", 12), Span("3", 12, bbox=(190, 72, 196, 84))], (160, 68, 196, 84))
    den = Line([Span("7 ", 12, bbox=(161, 89, 167, 101)), Span("−", 12, bbox=(176, 89, 185, 101), math=True),
                Span(" ", 12), Span("5", 12, bbox=(190, 89, 196, 101))], (161, 89, 196, 101))
    out = formulas.absorb_fractions([host, num, den], 300, 40)
    assert [" ".join(l.text.split()) for l in out] == ["(1) Differentiate y = x5/7 − 3/5"]


@pytest.mark.parametrize("name", ["pg-galois"])
def test_real_book_formulas_join_their_sentences(name, tmp_path):
    """Galois (78 pages of French with displayed equations): display formulas no longer split sentences."""
    pdf = CORPUS / f"{name}.pdf"
    if not pdf.exists():
        pytest.skip("corpus file missing (python tests/corpus/fetch.py)")
    convert(pdf, tmp_path / "g.epub", ConvertOptions(ocr="off"))
    _, paras = _paragraphs(tmp_path / "g.epub")
    texts = ["".join(p.itertext()).strip() for p in paras]
    maths = sum(1 for p in paras for s in p.iter(XHTML + "span") if s.get("class") == "dmath")
    breaks = sum(1 for a, b in zip(texts, texts[1:]) if a and b and a[-1].isalpha() and b[0].islower())
    assert maths >= 50 and breaks <= 0.03 * len(texts)  # was 165 per 1000 paragraphs before formulas were joined


def test_region_render_follows_an_inherited_crop_box(tmp_path):
    """Project Gutenberg PDFs inherit a /CropBox 20 pt narrower than the /MediaBox from the page tree: pdfium renders
    the crop box, the analysis uses the media box. Region crops (formulas, vector figures) must still hit their text."""
    from PIL import ImageOps
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, FloatObject, NameObject
    from reportlab.pdfgen import canvas

    from pdftoepub.core.backends import get_backend
    from pdftoepub.core.backends.common import ImageStore

    src = tmp_path / "s.pdf"
    c = canvas.Canvas(str(src), pagesize=(432, 576))
    c.setFont("Helvetica-Bold", 30)
    c.drawString(120, 300, "MMMM")
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(str(src)))
    pages = w._root_object["/Pages"]
    pages[NameObject("/CropBox")] = ArrayObject([FloatObject(v) for v in (20, 0, 412, 576)])
    for p in w.pages:
        p.pop("/CropBox", None)
    w.write(str(tmp_path / "c.pdf"))
    doc = get_backend()[0].open(tmp_path / "c.pdf")
    try:
        line = next(l for l in doc.extract_page(1, "inline", ImageStore(), []).lines if "MMMM" in l.text)
        asset = doc.render_region(1, line.bbox, 100, gray=True)
    finally:
        doc.close()
    img = Image.open(io.BytesIO(asset.data)) if asset else None
    assert img is not None
    ink = ImageOps.invert(img.convert("L")).point(lambda v: 255 if v > 128 else 0)
    x0, _, x1, _ = ink.getbbox()
    assert x0 <= 0.1 * img.width and x1 >= 0.9 * img.width  # the whole word, not shifted by the 20 pt crop


def test_display_formula_continuation_and_exponents():
    from pdftoepub.core import structure
    from pdftoepub.core.ir import Paragraph, Run

    blocks = [Paragraph([Run("si A est un nombre positif")], "p", 1),
              Paragraph([Run("x", italic=True), Run("3", sup=True, display=1), Run(" = 2,", display=1)], "dmath", 1),
              Paragraph([Run("et si A est plus grand que")], "p", 1),
              Paragraph([Run("l'unité, la valeur sera négative.")], "p", 2, break_before="page"),
              Paragraph([Run("Primary black hole mass 36")], "p", 2)]
    for r in blocks[1].runs:
        r.display = 1
    out = structure.inline_display_math(blocks)
    assert len(out) == 2 and structure.plain(out[1].runs).startswith("Primary")
    assert "l'unité" in structure.plain(out[0].runs)


def test_exponent_in_a_display_formula_is_not_a_footnote_mark():
    from pdftoepub.core import structure
    from pdftoepub.core.layout import Ctx, RawBlock, RawNote

    note = RawNote("3", [Line([Span("3 Voir la note de l'éditeur.", 8.0, bbox=(40, 500, 300, 510))], (40, 500, 300, 510))], 1)
    formula = Line([Span("x", 10, italic=True, bbox=(150, 100, 156, 112)), Span("3", 7, sup=True, bbox=(156, 98, 160, 106)),
                    Span(" = 2,", 10, bbox=(160, 100, 185, 112))], (150, 98, 185, 112), 1, "dmath")
    blk = RawBlock("text", 1, 98, [formula], None, 40, 300, None, False, None, True, True)
    model = structure.HeadingModel([], None, 10.0)
    out, notes = structure.convert_blocks([blk], Ctx(body_size=10.0), {1: [note]}, model)
    assert not [r for r in out[0].runs if r.noteref]


def _border_blank(img) -> bool:
    g = img.convert("L")
    w, h = g.size
    edge = [g.getpixel((x, 0)) for x in range(w)] + [g.getpixel((x, h - 1)) for x in range(w)]
    edge += [g.getpixel((0, y)) for y in range(h)] + [g.getpixel((w - 1, y)) for y in range(h)]
    return min(edge) >= 160


def test_formula_crop_covers_delimiter_ink_and_stops_halfway_to_the_text_line():
    """A big bracket reaches past the glyph box its font metrics give (CMEX): the crop grows over its ink. The text
    line just above is never in the picture: the crop stops halfway between it and the formula."""
    from PIL import ImageDraw

    from pdftoepub.core.backends.common import ImageStore, asset_from_pil
    from pdftoepub.core.ir import PageData

    s = 200 / 72
    page_img = Image.new("L", (int(300 * s), int(200 * s)), 255)
    d = ImageDraw.Draw(page_img)

    def ink(x0, y0, x1, y1):
        d.rectangle((x0 * s, y0 * s, x1 * s - 1, y1 * s - 1), fill=0)

    ink(20, 40, 280, 52)    # the text line above (its descenders reach its box bottom)
    ink(100, 70, 140, 80)   # numerator
    ink(100, 82.5, 140, 83.5)  # fraction bar
    ink(100, 86, 140, 96)   # denominator
    ink(146, 62, 150, 104)  # "]": ink from 62 to 104, glyph box 70-80 only

    def render(rect, dpi):
        return asset_from_pil(page_img.crop(tuple(round(v * s) for v in rect)))

    def piece(text, box, **kw):
        return formulas._Piece([Span(text, 10.0, bbox=box, math=True, **kw)], *box)

    pieces = [piece("a", (100, 70, 140, 80), italic=True), piece("b", (100, 86, 140, 96), italic=True),
              piece("]", (146, 70, 150, 80))]
    page = PageData(1, 300, 200)
    store = ImageStore()
    above = (20, 40, 280, 52)
    item = formulas._formula(pieces, page, 20, 10.0, render, store, [above])
    assert item is not None and item.kind == "formula"
    x0, y0, x1, y1 = item.bbox
    assert x1 >= 150 and y0 <= 62 and y1 >= 104  # the whole bracket
    assert y0 >= (52 + 70) / 2 - 0.5  # not into the line above (its box ends at 52, the formula's starts at 70)
    assert _border_blank(Image.open(io.BytesIO(store.assets[item.image_id].data)))


def _calculus_page(pno):
    from pdftoepub.core.backends import get_backend
    from pdftoepub.core.backends.common import ImageStore

    pdf = CORPUS / "pg-calculus-made-easy.pdf"
    if not pdf.exists():
        pytest.skip("corpus file missing (python tests/corpus/fetch.py)")
    doc = get_backend("pdfminer")[0].open(pdf)
    store = ImageStore()
    try:
        page = doc.extract_page(pno, "inline", store, [])
        n0 = len(page.images)
        formulas.process_page(page, lambda r, dpi: doc.render_region(pno, r, dpi, gray=True), store)
    finally:
        doc.close()
    return page, page.images[n0:], store


def test_text_row_cut_around_a_low_operator_is_one_line_not_part_of_the_formula():
    """Calculus made easy p.23: pdfminer cuts "which is y − dy, will be" around the "−" (its CMSY box sits a row low).
    The stray "−" joined the display formula below, whose picture then took the lower half of the text line."""
    page, crops, store = _calculus_page(23)
    assert any("which is y − dy, will be such that" in l.text for l in page.lines)
    assert not any("− −" in c.alt for c in crops)
    for c in crops:
        assert _border_blank(Image.open(io.BytesIO(store.assets[c.image_id].data))), c.alt


def test_big_delimiters_stay_in_their_formula_picture():
    """Calculus made easy p.34: "= x⁻² [1 − 2dx/x + 2(2+1)/(1×2) (dx/x)² − etc.]": the closing bracket's top piece
    formed a cluster of its own, and the "×" of the denominator went to the next equation and clamped the crop."""
    page, crops, store = _calculus_page(34)
    first = min(crops, key=lambda c: c.bbox[1])
    assert "(1 × 2)" in first.alt
    assert first.bbox[2] >= 327.7  # the closing bracket (glyph box 320.7-327.7)
    assert _border_blank(Image.open(io.BytesIO(store.assets[first.image_id].data)))
