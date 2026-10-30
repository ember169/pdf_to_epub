"""The cover: a cover document first in the spine, the right page, a good picture, no duplicated cover text."""
import io
import re
import zipfile

from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

from pdftoepub.api import ConvertOptions, convert
from pdftoepub.core import cover
from pdftoepub.core.backends.common import ImageStore
from pdftoepub.core.ir import Heading, ImageAsset, Line, PageData, Paragraph, Run, Span


def _thumb(ink: float):
    img = Image.new("L", (100, 150), 255)
    if ink:
        ImageDraw.Draw(img).rectangle((0, 0, 99, int(150 * ink) - 1), fill=0)
    return img


def _page(n, size=10.0):
    return PageData(n, 360, 540, lines=[Line([Span("Texte", size)], (40, 100, 200, 100 + size), n)])


def test_the_cover_page_is_page_one_unless_blank_or_a_bookplate_before_a_cover():
    pages = [_page(1), _page(2), _page(3)]
    assert cover.choose(pages, {1: _thumb(0.3), 2: _thumb(0.1), 3: _thumb(0.1)}, 10) == 1
    assert cover.choose(pages, {1: _thumb(0.0), 2: _thumb(0.1), 3: _thumb(0.1)}, 10) == 2  # blank page 1
    assert cover.choose(pages, {1: _thumb(0.01), 2: _thumb(0.6), 3: _thumb(0.1)}, 10) == 2  # bookplate, then a cover
    assert cover.choose(pages, {1: _thumb(0.01), 2: _thumb(0.1), 3: _thumb(0.1)}, 10) == 1  # unsure: page 1
    big = [_page(1), _page(2, 30.0), _page(3)]
    assert cover.choose(big, {1: _thumb(0.01), 2: _thumb(0.05), 3: _thumb(0.1)}, 10) == 2  # display type
    assert cover.choose(pages, {1: _thumb(0.0), 2: _thumb(0.0), 3: _thumb(0.0)}, 10) is None


def _jpeg(w, h, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), 128).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def test_a_full_page_picture_is_kept_as_embedded_and_grey_stays_grey():
    store = ImageStore()
    data = _jpeg(1000, 1500)
    iid = store.add(data, "image/jpeg", 1000, 1500)
    page = PageData(1, 360, 540, scan_ids=[iid])
    assert cover.picture(page, store, lambda dpi: None).data == data
    grey = cover.picture(PageData(1, 360, 540), store, lambda dpi: Image.new("RGB", (900, 1600), (90, 90, 90)))
    assert Image.open(io.BytesIO(grey.data)).mode == "L" and grey.height == 1600 and len(grey.data) <= cover.MAX_BYTES


def test_the_cover_text_is_dropped_only_when_it_is_the_title_and_names():
    blocks = [Heading(1, [Run("Pour une histoire")], 1), Paragraph([Run("Jeanne Dubois")], "p", 1),
              Paragraph([Run("Premier chapitre")], "p", 2)]
    out, n = cover.drop_cover_text(blocks, 1, ["Pour une histoire du travail", "Jeanne Dubois"])
    assert [b.page for b in out] == [2] and n == 5
    paper = [Heading(1, [Run("Pour une histoire")], 1), Paragraph([Run("Abstract. We study the history of work.")], "p", 1)]
    out, n = cover.drop_cover_text(paper, 1, ["Pour une histoire", "Jeanne Dubois"])
    assert out == paper and n == 0


def _book(path):
    c = canvas.Canvas(str(path), pagesize=(360, 540))
    c.setFont("Times-Bold", 30)
    c.drawString(40, 380, "Pour une histoire")
    c.setFont("Times-Roman", 14)
    c.drawString(40, 340, "Jeanne Dubois")
    c.showPage()
    for p in range(2):
        c.setFont("Times-Roman", 10)
        for i in range(30):
            c.drawString(40, 500 - 14 * i, f"Le travail de la ligne {i} de la page {p + 2} se poursuit ici.")
        c.showPage()
    c.setTitle("Pour une histoire")
    c.setAuthor("Jeanne Dubois")
    c.save()


def test_the_epub_opens_on_a_cover_document(tmp_path):
    _book(tmp_path / "b.pdf")
    convert(tmp_path / "b.pdf", tmp_path / "b.epub", ConvertOptions(ocr="off"))
    z = zipfile.ZipFile(tmp_path / "b.epub")
    opf = z.read("OEBPS/content.opf").decode()
    itemrefs = re.findall(r'<itemref idref="([^"]+)"', opf)
    assert itemrefs[0] == "cover" and 'properties="cover-image"' in opf and '<meta name="cover" content="cover-image"/>' in opf
    assert '<reference type="cover"' in opf
    xhtml = z.read("OEBPS/cover.xhtml").decode()
    assert 'epub:type="cover"' in xhtml and "<title>Pour une histoire</title>" in xhtml and "images/cover.jpg" in xhtml
    nav = z.read("OEBPS/nav.xhtml").decode()
    assert 'epub:type="cover" href="cover.xhtml"' in nav and 'epub:type="toc"' in nav and 'epub:type="bodymatter"' in nav
    im = Image.open(io.BytesIO(z.read("OEBPS/images/cover.jpg")))
    assert im.height == 1600 and im.mode == "L"  # rendered 1600 px high; black on white stays grey
    first = z.read(itemrefs and [n for n in z.namelist() if n.endswith("ch001.xhtml")][0]).decode()
    assert "Jeanne Dubois" not in first and "Le travail de la ligne 0" in first  # the cover's text is the cover


def test_no_cover_without_images(tmp_path):
    _book(tmp_path / "b.pdf")
    convert(tmp_path / "b.pdf", tmp_path / "b.epub", ConvertOptions(ocr="off", image_mode="none"))
    z = zipfile.ZipFile(tmp_path / "b.epub")
    assert "OEBPS/cover.xhtml" not in z.namelist() and "Jeanne Dubois" in z.read("OEBPS/ch001.xhtml").decode()
