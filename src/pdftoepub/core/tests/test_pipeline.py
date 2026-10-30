import re
import shutil
import zipfile

import pytest
from lxml import etree

from pdftoepub.api import ConversionError, ConvertOptions, ProgressEvent, convert
from pdftoepub.core._samples import make_samples

XHTML = "{http://www.w3.org/1999/xhtml}"


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    make_samples.main(str(d))
    return d


def open_epub(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    # packaging rules
    assert names[0] == "mimetype"
    assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    assert z.read("mimetype") == b"application/epub+zip"
    for n in names:
        if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            etree.fromstring(z.read(n))  # well-formed
    return z


def chapters(z):
    out = []
    for n in sorted(z.namelist()):
        if re.match(r"OEBPS/ch\d+\.xhtml", n):
            out.append((n, etree.fromstring(z.read(n))))
    return out


def body_text(root):
    return " ".join("".join(p.itertext()) for p in root.iter(XHTML + "p"))


def test_book_structure(samples, tmp_path):
    events: list[ProgressEvent] = []
    res = convert(samples / "book.pdf", tmp_path / "b.epub", progress=events.append)
    assert res.title == "Sample Book" and res.page_count == 10 and res.chapter_count == 4
    assert events[0].stage == "extract" and events[-1].stage == "done"
    z = open_epub(tmp_path / "b.epub")
    chs = chapters(z)
    assert len(chs) == 4
    for _, root in chs:
        assert root.find(f".//{XHTML}h1") is not None
    for _, root in chs[1:]:
        assert len(body_text(root)) > 100  # real text, never image-only
    ch1 = chs[1][1]
    tags = {e.tag.replace(XHTML, "") for e in ch1.iter()}
    assert {"h1", "h2", "p", "ul", "ol", "table", "blockquote", "pre", "figure", "img", "strong", "em", "a"} <= tags
    text = " ".join(ch1.itertext())
    assert "Running header" not in text and "Page 2" not in text  # header/footer removed
    hrefs = [a.get("href") for a in ch1.iter(XHTML + "a")]
    assert "https://example.com/docs" in hrefs and any(h.startswith("ch002.xhtml#") for h in hrefs)
    cells = [c.text for c in ch1.iter(XHTML + "td")]
    assert "1.20" in cells
    # nav + NCX
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    assert len(list(nav.iter(XHTML + "a"))) >= 7
    assert b"navPoint" in z.read("OEBPS/toc.ncx")
    opf = z.read("OEBPS/content.opf").decode()
    assert 'properties="nav"' in opf and 'properties="cover-image"' in opf and "Jane Doe" in opf


def test_css_is_relative_only(samples, tmp_path):
    convert(samples / "book.pdf", tmp_path / "b.epub")
    css = zipfile.ZipFile(tmp_path / "b.epub").read("OEBPS/style.css").decode()
    assert not re.search(r"\d\s*(px|pt)\b", css)
    body_rule = re.search(r"body\s*\{[^}]*\}", css).group(0)
    assert "font-size" not in body_rule


def test_chapters_from_headings_without_outline(samples, tmp_path):
    res = convert(samples / "book_no_outline.pdf", tmp_path / "b.epub")
    assert res.chapter_count == 4  # title page + 3 chapters, split on the largest heading level
    z = open_epub(tmp_path / "b.epub")
    assert "Chapter 2" in "".join(chapters(z)[2][1].find(f".//{XHTML}h1").itertext())


def test_two_columns_footnotes_and_cross_column_paragraphs(samples, tmp_path):
    res = convert(samples / "twocol.pdf", tmp_path / "t.epub")
    z = open_epub(tmp_path / "t.epub")
    chs = chapters(z)
    sec1 = chs[1][1]
    paras = ["".join(p.itertext()) for p in sec1.find(f".//{XHTML}section").iter(XHTML + "p")]
    assert len(paras) == 5  # paragraphs continuing into the next column / page are merged back together
    assert all(p.rstrip().endswith("words.") for p in paras)
    assert sec1.find(f".//{XHTML}a[@{{http://www.idpf.org/2007/ops}}type='noteref']") is not None
    notes = [e for e in sec1.iter(XHTML + "aside")]
    assert notes and "first note" in "".join(notes[0].itertext())
    assert "Journal of Synthetic Tests" not in "".join(sec1.itertext())
    assert any(n.endswith(".png") for n in z.namelist())
    assert res.warnings == []


def test_errors_raise_conversion_error(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_text("not a pdf at all")
    with pytest.raises(ConversionError):
        convert(bad, tmp_path / "o.epub")
    with pytest.raises(ConversionError):
        convert(tmp_path / "missing.pdf", tmp_path / "o.epub")
    from pypdf import PdfWriter

    blank = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=300, height=300)
    w.write(str(blank))
    with pytest.raises(ConversionError):
        convert(blank, tmp_path / "o.epub")
    assert not (tmp_path / "o.epub").exists()


def test_encrypted_pdf_is_rejected(samples, tmp_path):
    enc = tmp_path / "enc.pdf"
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(str(samples / "book.pdf")))
    w.encrypt(user_password="s", owner_password="o", algorithm="AES-256")
    w.write(str(enc))
    with pytest.raises(ConversionError, match="password"):
        convert(enc, tmp_path / "o.epub")


def test_options_title_author_language(samples, tmp_path):
    res = convert(samples / "book.pdf", tmp_path / "b.epub", ConvertOptions(title="T", author="A", language="fr-CA", image_mode="none"))
    z = open_epub(tmp_path / "b.epub")
    opf = z.read("OEBPS/content.opf").decode()
    assert res.title == "T" and "<dc:title>T</dc:title>" in opf and "<dc:creator" in opf and "<dc:language>fr-CA</dc:language>" in opf
    assert not [n for n in z.namelist() if n.startswith("OEBPS/images/")]


def test_scanned_pdf_without_ocr_keeps_images_and_warns(samples, tmp_path):
    res = convert(samples / "scanned.pdf", tmp_path / "s.epub", ConvertOptions(ocr="off"))
    assert any("no usable text layer" in w for w in res.warnings)
    open_epub(tmp_path / "s.epub")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_scanned_pdf_ocr(samples, tmp_path):
    res = convert(samples / "scanned.pdf", tmp_path / "s.epub", ConvertOptions(ocr_langs="eng"))
    assert res.ocr_pages == 2
    z = open_epub(tmp_path / "s.epub")
    txt = " ".join(body_text(r) for _, r in chapters(z))
    assert "quick brown fox" in txt or "Sphinx" in txt
    assert not [n for n in z.namelist() if n.startswith("OEBPS/images/img")]  # no page images, real text
