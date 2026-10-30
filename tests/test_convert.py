"""End-to-end: every generated fixture through pdftoepub.convert."""
from __future__ import annotations

import re
import shutil
import zipfile

import pytest
from lxml import etree

import epubcheck
from fixtures import make_fixtures
from pdftoepub.api import ConversionError

OK = [n for n in make_fixtures.BUILDERS if n not in ("encrypted", "corrupt")]
NS = {"x": "http://www.w3.org/1999/xhtml"}


def chapters(epub):
    """Yield (name, root) for each content XHTML (nav excluded)."""
    with zipfile.ZipFile(epub) as z:
        for n in z.namelist():
            if n.endswith((".xhtml", ".html")):
                root = etree.fromstring(z.read(n))
                if root.xpath("//x:nav[@*[local-name()='type']='toc']", namespaces=NS):
                    continue
                yield n, root


def text_of(root) -> str:
    return re.sub(r"\s+", " ", " ".join(root.xpath("//x:body//text()", namespaces=NS)))


def skip_if_ocr_unavailable(name):
    if name == "scanned" and not shutil.which("tesseract"):
        pytest.skip("tesseract not installed")


@pytest.mark.parametrize("name", [n for n in make_fixtures.BUILDERS if n != "encrypted"])  # AES salts are random
def test_fixture_generation_is_deterministic(name, tmp_path):
    a, _ = make_fixtures.build(name, tmp_path / "a")
    b, _ = make_fixtures.build(name, tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.core
@pytest.mark.parametrize("name", ["encrypted", "corrupt"])
def test_bad_pdfs_raise_conversion_error(name, fixtures, tmp_path):
    import pdftoepub
    pdf, _ = fixtures[name]
    with pytest.raises(ConversionError):
        pdftoepub.convert(pdf, tmp_path / "x.epub")


@pytest.mark.core
@pytest.mark.parametrize("name", OK)
def test_epub_is_valid_zip_with_chapters(name, convert_fixture):
    skip_if_ocr_unavailable(name)
    res, spec = convert_fixture(name)
    with zipfile.ZipFile(res.epub_path) as z:
        assert z.namelist()[0] == "mimetype"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    assert res.chapter_count >= spec.min_chapters


@pytest.mark.core
@pytest.mark.epubcheck
@pytest.mark.parametrize("name", OK)
def test_epubcheck_clean(name, convert_fixture, tmp_path):
    skip_if_ocr_unavailable(name)
    if not epubcheck.java_available():
        pytest.skip("java not found: install a JRE (or run in the Docker test image) to run epubcheck")
    res, _ = convert_fixture(name)
    assert epubcheck.check(res.epub_path, tmp_path) == []


@pytest.mark.core
@pytest.mark.parametrize("name", OK)
def test_text_headings_and_no_image_only_chapters(name, convert_fixture):
    skip_if_ocr_unavailable(name)
    res, spec = convert_fixture(name)
    all_text = ""
    for n, root in chapters(res.epub_path):
        t = text_of(root)
        assert len(t.strip()) > 0 or not root.xpath("//x:img", namespaces=NS), f"{n} is image-only"
        assert len(t.strip()) > 0, f"{n} has no text"
        all_text += " " + t
    norm = re.sub(r"\s+", " ", all_text)
    for phrase in spec.body:
        assert re.sub(r"\s+", " ", phrase) in norm, f"missing body text: {phrase!r}"
    heads = " | ".join(
        re.sub(r"\s+", " ", "".join(h.itertext())).strip()
        for _, root in chapters(res.epub_path)
        for h in root.xpath("//x:h1|//x:h2|//x:h3|//x:h4|//x:h5|//x:h6", namespaces=NS))
    for h in spec.headings:
        assert h in heads, f"missing heading {h!r} in {heads!r}"
    for a in spec.absent:
        assert a not in norm, f"running header/footer leaked: {a!r}"


@pytest.mark.core
def test_header_footer_kept_when_disabled(convert_fixture):
    res, _ = convert_fixture("header_footer", drop_headers_footers=False)
    txt = " ".join(text_of(r) for _, r in chapters(res.epub_path))
    assert "RUNNING HEADER" in txt


@pytest.mark.core
def test_two_column_reading_order(convert_fixture):
    res, _ = convert_fixture("two_column")
    txt = " ".join(text_of(r) for _, r in chapters(res.epub_path))
    assert txt.index("LEFTCOL") < txt.rindex("LEFTCOL") < txt.index("RIGHTCOL")


@pytest.mark.core
def test_hyphenation_removed(convert_fixture):
    res, _ = convert_fixture("hyphenated")
    txt = " ".join(text_of(r) for _, r in chapters(res.epub_path))
    assert "extraor-" not in txt and "documenta-" not in txt


@pytest.mark.core
def test_lists_and_tables_are_semantic(convert_fixture):
    res, _ = convert_fixture("lists")
    assert any(r.xpath("//x:ul/x:li|//x:ol/x:li", namespaces=NS) for _, r in chapters(res.epub_path))
    res, _ = convert_fixture("table")
    assert any(r.xpath("//x:table//x:td", namespaces=NS) for _, r in chapters(res.epub_path))


@pytest.mark.core
def test_image_inline_and_none_mode(convert_fixture):
    res, _ = convert_fixture("image")
    assert any(r.xpath("//x:img", namespaces=NS) for _, r in chapters(res.epub_path))
    res, _ = convert_fixture("image", image_mode="none")
    assert not any(r.xpath("//x:img", namespaces=NS) for _, r in chapters(res.epub_path))


@pytest.mark.core
@pytest.mark.parametrize("name", ["single_column", "image"])
def test_css_relative_units_only(name, convert_fixture):
    res, _ = convert_fixture(name)
    with zipfile.ZipFile(res.epub_path) as z:
        css = [z.read(n).decode() for n in z.namelist() if n.endswith(".css")]
        inline = [z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml")]
    assert css, "no stylesheet"
    for s in css:
        assert not re.search(r"font-size\s*:\s*[\d.]+px", s), "px font-size in CSS"
        assert not re.search(r"(?<![\w-])width\s*:\s*[\d.]+px", s), "fixed px width in CSS"
        body = re.search(r"(?<![\w-])body\s*\{[^}]*\}", s)
        assert not (body and "font-size" in body.group(0)), "font-size set on body"
    for x in inline:
        assert not re.search(r"font-size\s*:\s*[\d.]+px", x)


@pytest.mark.core
def test_scanned_uses_ocr(convert_fixture):
    if not shutil.which("tesseract"):
        pytest.skip("tesseract not installed")
    res, _ = convert_fixture("scanned")
    assert res.ocr_pages == 1
    res, _ = convert_fixture("scanned", ocr="off")
    assert res.ocr_pages == 0
