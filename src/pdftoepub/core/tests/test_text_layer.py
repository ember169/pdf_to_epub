"""Text layers with their own space glyphs (OCR layers such as ABBYY FineReader's, word processors): words come from
those spaces, not from gaps, so letter-spaced small type stays whole ("Bernard", not "B e r n a r d")."""
from reportlab.pdfgen import canvas

from pdftoepub.core.backends import get_backend
from pdftoepub.core.backends.common import ImageStore

FILLER = "Les sociétés égalitaires reposent sur une division du travail entre femmes et hommes."


def _page_text(path):
    doc = get_backend()[0].open(path)
    try:
        return [l.text.strip() for l in doc.extract_page(1, "inline", ImageStore(), []).lines]
    finally:
        doc.close()


def _pdf(path, rows):
    """rows: [(text, x, y, size, char_space)]; each row is one text object (its spaces are glyphs)."""
    c = canvas.Canvas(str(path), pagesize=(400, 600))
    for text, x, y, size, cs in rows:
        t = c.beginText(x, y)
        t.setFont("Times-Roman", size)
        t.setCharSpace(cs)
        t.textOut(text)
        c.drawText(t)
    c.showPage()
    c.save()


def test_letter_spaced_words_stay_whole_when_the_layer_has_space_glyphs(tmp_path):
    rows = [(FILLER[:60], 30, 560 - 14 * i, 10, 0) for i in range(4)]
    rows.append(("Voir Bernard, Lefort et Garnier en 2010.", 30, 480, 6.5, 1.3))  # tracked notes type
    _pdf(tmp_path / "a.pdf", rows)
    lines = _page_text(tmp_path / "a.pdf")
    assert "Voir Bernard, Lefort et Garnier en 2010." in lines


def test_a_missing_space_glyph_shows_as_a_wide_gap(tmp_path):
    rows = [(FILLER[:60], 30, 560 - 14 * i, 10, 0) for i in range(4)]
    rows += [("University of", 30, 480, 10, 0), ("California Press.", 30 + 58 + 3, 480, 10, 0)]  # no glyph between
    _pdf(tmp_path / "b.pdf", rows)
    assert any("University of California Press." in l for l in _page_text(tmp_path / "b.pdf"))


def test_a_layer_without_space_glyphs_still_gets_its_word_spaces(tmp_path):
    c = canvas.Canvas(str(tmp_path / "c.pdf"), pagesize=(400, 600))
    c.setFont("Times-Roman", 10)
    for i in range(4):  # LaTeX-like: every word placed on its own, no space glyph anywhere
        x = 30
        for w in FILLER.split()[:8]:
            c.drawString(x, 560 - 14 * i, w)
            x += c.stringWidth(w, "Times-Roman", 10) + 3
    c.showPage()
    c.save()
    lines = _page_text(tmp_path / "c.pdf")
    assert lines[0] == " ".join(FILLER.split()[:8])


def test_pdf_metadata_strings_are_decoded_as_written(tmp_path):
    """UTF-8 bytes in the Info dictionary (no byte-order mark) are UTF-8, not PDFDocEncoding ("My Ã†ntonia")."""
    import zipfile

    from pypdf import PdfWriter
    from pypdf.generic import ByteStringObject, NameObject

    from pdftoepub.api import ConvertOptions, convert
    from pdftoepub.core.backends.common import decode_pdf_string, repair_mojibake

    assert decode_pdf_string(b"My \xc3\x81ntonia") == "My Ántonia"
    assert decode_pdf_string(b"\xfe\xff\x00C\x00a\x00f\x00\xe9") == "Café"
    assert decode_pdf_string(b"Caf\xe9") == "Café"  # PDFDocEncoding
    assert repair_mojibake("My Ã†ntonia") == "My Ántonia" and repair_mojibake("Ça va") == "Ça va"
    _pdf(tmp_path / "t.pdf", [(FILLER[:60], 30, 560 - 14 * i, 10, 0) for i in range(6)])
    w = PdfWriter(clone_from=str(tmp_path / "t.pdf"))
    w._info.get_object()[NameObject("/Title")] = ByteStringObject(b"My \xc3\x81ntonia")
    w.write(str(tmp_path / "m.pdf"))
    convert(tmp_path / "m.pdf", tmp_path / "m.epub", ConvertOptions(ocr="off"))
    opf = zipfile.ZipFile(tmp_path / "m.epub").read("OEBPS/content.opf").decode()
    assert "<dc:title>My Ántonia</dc:title>" in opf


def test_a_spacing_accent_set_in_its_own_font_joins_its_letter(tmp_path):
    """TeX's "´" before a capital comes from another font (its own span): "G´EOM´ETRIE" reads "GÉOMÉTRIE"."""
    c = canvas.Canvas(str(tmp_path / "a.pdf"), pagesize=(400, 600))
    for i in range(4):
        c.setFont("Times-Roman", 10)
        c.drawString(30, 560 - 14 * i, FILLER[:60])
    x = 30
    for txt, font in (("LA G", "Times-Roman"), ("´", "Helvetica"), ("EOM", "Times-Roman"), ("´", "Helvetica"),
                      ("ETRIE", "Times-Roman")):
        c.setFont(font, 24)
        c.drawString(x, 450, txt)
        x += c.stringWidth(txt, font, 24) if txt != "´" else 0
    c.showPage()
    c.save()
    assert any("LA GÉOMÉTRIE" in l for l in _page_text(tmp_path / "a.pdf"))
