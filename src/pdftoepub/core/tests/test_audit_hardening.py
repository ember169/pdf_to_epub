"""Security / robustness audit fixes: job-level locking, bounded render / decode memory, isolation, metadata, URLs."""
import threading
import time
import zipfile

import pytest

from pdftoepub.api import ConvertOptions, convert
from pdftoepub.core import ocr
from pdftoepub.core._samples import make_samples
from pdftoepub.core.ir import Line, Span


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    make_samples.main(str(d))
    return d


# ---------------------------------------------------------------- (4) one slow job must not block the others

def test_ocr_of_one_job_does_not_block_another_job(samples, tmp_path, monkeypatch):
    in_ocr, other_done = threading.Event(), threading.Event()

    def slow_ocr(engine, image, pno, timeout=300):
        in_ocr.set()
        other_done.wait(30)  # a job holding a global lock here would deadlock the other job until the timeout
        return [Line([Span("recognised text " * 4, 10.0, bbox=(50, 50, 400, 62))], (50, 50, 400, 62), pno)]

    monkeypatch.setattr(ocr, "find_engine", lambda langs: (ocr.OcrEngine("tesseract", "eng"), None))
    monkeypatch.setattr(ocr, "ocr_image", slow_ocr)
    errors = []

    def scanned_job():
        try:
            convert(samples / "scanned.pdf", tmp_path / "s.epub", ConvertOptions(ocr="force"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=scanned_job)
    t.start()
    assert in_ocr.wait(30)
    t0 = time.monotonic()
    convert(samples / "book.pdf", tmp_path / "b.epub")  # must not wait for the OCR job
    elapsed = time.monotonic() - t0
    other_done.set()
    t.join(60)
    assert not errors and elapsed < 25


def test_concurrent_jobs_give_the_same_epub_as_sequential(samples, tmp_path):
    def content(path):
        z = zipfile.ZipFile(path)
        return {n: z.read(n) for n in z.namelist() if n.endswith((".xhtml", ".css")) or "/images/" in n}

    names = ["book.pdf", "twocol.pdf", "figure.pdf", "book.pdf"]
    names = [n for n in names if (samples / n).exists()]
    ref = {}
    for i, n in enumerate(names):
        convert(samples / n, tmp_path / f"seq{i}.epub")
        ref[i] = content(tmp_path / f"seq{i}.epub")
    errors = []

    def job(i, n):
        try:
            convert(samples / n, tmp_path / f"par{i}.epub")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=job, args=(i, n)) for i, n in enumerate(names)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors
    for i in ref:
        assert content(tmp_path / f"par{i}.epub") == ref[i]


# ---------------------------------------------------------------- (5) bounded rendering / decoding

def _huge_page_pdf(path):
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(14400, 14400))  # 200 x 200 inches, the PDF maximum
    c.setFont("Helvetica", 400)
    for i in range(20):
        c.drawString(1000, 13000 - 600 * i, f"Huge page line {i} with enough words to be text")
    c.showPage()
    c.save()
    return path


def test_huge_page_renders_are_clamped(tmp_path):
    from pdftoepub.core.backends import get_backend
    from pdftoepub.core.backends.common import MAX_RENDER_PIXELS

    pdf = _huge_page_pdf(tmp_path / "huge.pdf")
    backend, _ = get_backend()
    doc = backend.open(pdf)
    try:
        img = doc.render_page(1, 300, gray=True)  # unclamped: 60000 x 60000 px
        assert img.width * img.height <= MAX_RENDER_PIXELS and img.width > 1000
        assert any("rendered at reduced resolution" in w for w in doc.warnings)
    finally:
        doc.close()
    res = convert(pdf, tmp_path / "huge.epub")
    assert any("rendered at reduced resolution" in w for w in res.warnings)


def test_clamp_scale():
    from pdftoepub.core.backends.common import clamp_scale

    assert clamp_scale(595, 842, 300) == (300 / 72, False)
    s, clamped = clamp_scale(14400, 14400, 300, 50_000_000)
    assert clamped and 0.98 * 50_000_000 < (14400 * s) ** 2 <= 50_000_000


def test_pillow_limit_is_set_explicitly(samples, tmp_path):
    from PIL import Image

    from pdftoepub.core.backends.common import MAX_RENDER_PIXELS

    convert(samples / "book.pdf", tmp_path / "b.epub")
    assert Image.MAX_IMAGE_PIXELS == MAX_RENDER_PIXELS // 2


# ---------------------------------------------------------------- (6) isolation: timeout, memory cap, page limit

def _flate_bomb_pdf(path, inflated_mb=600):
    """One page whose content stream is ~0.6 MB of Flate data inflating to `inflated_mb` MB of blanks."""
    import zlib

    comp = zlib.compressobj(9)
    chunk = b" " * (1 << 20)
    data = b"".join(comp.compress(chunk) for _ in range(inflated_mb)) + comp.flush()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << >> >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def test_isolated_conversion_relays_progress_and_result(samples, tmp_path):
    from pdftoepub.core.isolation import convert_isolated

    events = []
    res = convert_isolated(samples / "book.pdf", tmp_path / "b.epub", progress=events.append, timeout_s=120)
    direct = convert(samples / "book.pdf", tmp_path / "d.epub")
    assert (res.title, res.page_count, res.chapter_count) == (direct.title, direct.page_count, direct.chapter_count)
    assert events and events[0].stage == "extract" and events[-1].stage == "done"
    assert zipfile.ZipFile(tmp_path / "b.epub").namelist()[0] == "mimetype"


def test_isolated_conversion_limits(samples, tmp_path):
    from pdftoepub.api import ConversionError
    from pdftoepub.core.isolation import convert_isolated

    with pytest.raises(ConversionError, match="took longer than"):
        convert_isolated(samples / "book.pdf", tmp_path / "t.epub", timeout_s=0.05)  # child start-up alone is longer
    assert not (tmp_path / "t.epub").exists()
    with pytest.raises(ConversionError, match="has 10 pages; the limit is 3"):
        convert_isolated(samples / "book.pdf", tmp_path / "p.epub", max_pages=3)
    with pytest.raises(ConversionError, match="could not be read|not a PDF"):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4\n garbage")
        convert_isolated(bad, tmp_path / "x.epub")


def test_isolated_conversion_stops_a_flate_bomb(tmp_path, backend):
    from pdftoepub.api import ConversionError
    from pdftoepub.core.isolation import convert_isolated

    pdf = _flate_bomb_pdf(tmp_path / "bomb.pdf")
    assert pdf.stat().st_size < 2_000_000
    with pytest.raises(ConversionError) as exc:
        convert_isolated(pdf, tmp_path / "bomb.epub", ConvertOptions(ocr="off"), timeout_s=60, max_mem_mb=250)
    if backend == "pdfminer":  # pdfminer inflates the whole stream in memory: the cap must trigger
        assert "memory" in str(exc.value)
    assert not (tmp_path / "bomb.epub").exists()


# ---------------------------------------------------------------- (9) metadata text, (11) link URLs

def test_clean_text_field_and_title_fallbacks(samples, tmp_path):
    from pathlib import Path

    from pypdf import PdfReader, PdfWriter

    from pdftoepub.core import pipeline, structure

    assert structure.clean_text_field("\ud800\x07 ‮") == ""
    assert structure.clean_text_field(" A\x00 title​\nhere ") == "A title here"
    assert pipeline._guess_title([], Path("/x/\udcff_my_book.pdf")) == "my book"
    assert pipeline._guess_title([], Path("/x/\udcff.pdf")) == "Untitled"
    # an option title made only of control characters / lone surrogates falls back to the PDF's own title
    res = convert(samples / "book.pdf", tmp_path / "a.epub", ConvertOptions(title="\ud800\x07 ", author="Jane\x00 Doe\ud800"))
    opf = zipfile.ZipFile(tmp_path / "a.epub").read("OEBPS/content.opf").decode()
    assert res.title == "Sample Book" and "<dc:title>Sample Book</dc:title>" in opf and "Jane Doe" in opf
    # PDF metadata that is control characters only: next fallback (heading / file name), never an empty dc:title
    w = PdfWriter(clone_from=PdfReader(str(samples / "book_no_outline.pdf")))
    w.add_metadata({"/Title": "\x07\x08", "/Author": "\x01"})
    w.write(str(tmp_path / "ctl.pdf"))
    res = convert(tmp_path / "ctl.pdf", tmp_path / "c.epub")
    opf = zipfile.ZipFile(tmp_path / "c.epub").read("OEBPS/content.opf").decode()
    assert res.title.strip() and f"<dc:title>{res.title}</dc:title>" in opf and "\x07" not in opf


def test_tex_leaking_into_the_info_title_is_not_the_title(samples, tmp_path):
    from pypdf import PdfReader, PdfWriter

    from pdftoepub.core import structure

    # hyperref fed a macro (an apostrophe) to /Title: the PDF holds TeX code, as each backend unescapes it
    tex = r"Puck of Pook{\protect \edef U00{U00}\let \enc@update \relax \protect \xdef \U00/times/m/n/10.95 }s Hill"
    for t in (tex, "Puck of Pook{rotect def U00{U00}et nc@update elax rotect def 00/times/m/n/10.95 }s Hill",
              "Pook{protect edef U00{U00}let enc@update elax", r"\textbf{Title}", "A \\def B"):
        assert structure.leaked_markup(t) and structure.clean_meta_title(t) is None, t
    for t in ("Le Roman expérimental", "The Project Gutenberg eBook #33283: Calculus Made Easy, 2nd Edition",
              "An island plant : a Nantucket story", "Burrell, David De Forest, 1876-", "LA GÉOMÉTRIE(1)",
              "C/C++ and Python", "Mail me@example.com", "Undefined behaviour"):
        assert not structure.leaked_markup(t) and structure.clean_meta_title(t) == t, t
    w = PdfWriter(clone_from=PdfReader(str(samples / "book.pdf")))
    w.add_metadata({"/Title": tex, "/Author": r"\author{Jane}"})
    w.write(str(tmp_path / "tex.pdf"))
    res = convert(tmp_path / "tex.pdf", tmp_path / "t.epub")
    z = zipfile.ZipFile(tmp_path / "t.epub")
    text = "".join(z.read(n).decode() for n in z.namelist() if n.endswith((".opf", ".xhtml", ".ncx")))
    assert res.title == "Sample Book" and not any(s in text for s in ("U00", "@update", "/times/", r"\author", "{Jane}"))


@pytest.mark.parametrize("href,expected", [
    ("https://proceedings.neurips.cc/paper/92d1e1eb fb.pdf", "https://proceedings.neurips.cc/paper/92d1e1eb%20fb.pdf"),
    (" https://ex.com/a b?q=é#f g ", "https://ex.com/a%20b?q=%C3%A9#f%20g"),
    ("http://bücher.de/ä", "http://xn--bcher-kva.de/%C3%A4"),
    ("https://ex.com/100%", "https://ex.com/100%25"),
    ("https://ex.com/a%20b", "https://ex.com/a%20b"),
    ("http://user:pw@ex.com:8080/x", "http://ex.com:8080/x"),
    ("mailto:a@b.co", "mailto:a@b.co"),
    ("https://ex.com/\x01\ud800x", "https://ex.com/x"),
    ("javascript:alert(1)", None), ("http://", None), ("https://exa mple.com/", None), ("mailto:nobody", None),
    ("https://ex.com:99999/", None), ("file:///etc/passwd", None), ("", None),
])
def test_safe_url(href, expected):
    from pdftoepub.core.structure import safe_url

    assert safe_url(href) == expected


def test_no_pypdfium2_warnings_on_the_console(samples, tmp_path, caplog, capfd, backend):
    """Rendering and image extraction free pdfium bitmaps explicitly without pypdfium2's 'potentially unsafe' log line
    (non-technical users see stderr in the console window of the desktop binary)."""
    import logging

    from pdftoepub.core.backends import get_backend
    from pdftoepub.core.backends.common import ImageStore

    caplog.set_level(logging.DEBUG)
    doc = get_backend()[0].open(samples / "book.pdf")
    for pno in range(1, doc.page_count + 1):
        doc.extract_page(pno, "inline", ImageStore(), [])
    doc.render_page(1, 300, gray=True)
    doc.close()
    convert(samples / "scanned.pdf", tmp_path / "s.epub", ConvertOptions(ocr="off"))
    err = capfd.readouterr().err
    assert "potentially unsafe" not in err and "Explicitly closing" not in err
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and ("pypdfium2" in r.name or "unsafe" in r.getMessage())]
