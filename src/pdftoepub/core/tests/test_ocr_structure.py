"""OCR pages: robust line sizes, strict headings, no chapter splits from OCR size noise, running heads on short scans."""
import io
import re
import shutil
import subprocess
import zipfile

import pytest
from lxml import etree

from pdftoepub.api import ConvertOptions, convert
from pdftoepub.core import ocr, structure
from pdftoepub.core.ir import Line, Span
from pdftoepub.core.layout import RawBlock

XHTML = "{http://www.w3.org/1999/xhtml}"


def test_ocr_line_size_does_not_depend_on_letter_shapes():
    # same 10 px em: "une" spans the x-height only, "lequel" ascenders + descenders, "Été" capital accent
    a = ocr.line_size_px([(0, 0, 30, 4.8, 95, "une"), (40, 0, 30, 4.8, 95, "mon"), (80, 0, 30, 4.8, 95, "va")])
    b = ocr.line_size_px([(0, 0, 50, 9.5, 95, "lequel"), (60, 0, 40, 9.5, 95, "pythagore"), (110, 0, 20, 7.3, 95, "de")])
    c = ocr.line_size_px([(0, 0, 30, 8.5, 95, "Été"), (40, 0, 30, 4.8, 95, "une"), (80, 0, 30, 7.0, 95, "pas")])
    assert all(abs(x - 10) <= 0.6 for x in (a, b, c))


def _blk(text, size, *, lines=1, above=12.0, centred=False):
    ls = [Line([Span(text, size, bbox=(40, 100 + 14 * i, 260, 110 + 14 * i))], (40, 100 + 14 * i, 260, 110 + 14 * i))
          for i in range(lines)]
    return RawBlock("text", 1, 100, ls, None, 40, 260, None, True, above, centred)


def test_ocr_headings_need_strong_evidence():
    key = structure._heading_key
    assert key(_blk("ROMAN EXPÉRIMENTAL", 20.0, centred=True), 10.0) is not None
    assert key(_blk("faute d'être précisée el comprise. Il me paraît donc", 13.5), 10.0) is None  # lower case start
    assert key(_blk("Pour plus de clarté, je crois devoir résumer briè-", 14.0), 10.0) is None  # hyphen end
    assert key(_blk("Dans mes études littéraires, j'ai souvent parlé de", 14.0), 10.0) is None  # mid-sentence
    assert key(_blk("Chapitre premier", 11.8), 10.0) is None  # within OCR size noise
    assert key(_blk("Chapitre premier", 14.0, above=2.0), 10.0) is None  # no whitespace above, not centred
    assert key(_blk("Chapitre premier", 14.0, above=12.0), 10.0) is not None
    assert not structure.strong_ocr_heading(_blk("Chapitre premier", 14.0), 10.0)
    assert structure.strong_ocr_heading(_blk("CHAPITRE PREMIER", 16.0, centred=True), 10.0)


def test_weak_ocr_headings_do_not_split_chapters():
    from pdftoepub.core.ir import Heading, Paragraph, Run

    blocks = []
    for i in range(3):
        blocks.append(Heading(1, [Run(f"Section {i}")], i + 1, weak=True))
        blocks.append(Paragraph([Run("Body text " * 20)], "p", i + 1))
    chapters = structure.build_chapters(blocks, [], 3, "Book", [])
    assert len(chapters) == 1
    for b in blocks[::2]:
        b.weak = False
    assert len(structure.build_chapters(blocks, [], 3, "Book", [])) == 3


def _tesseract_has(lang: str) -> bool:
    if not shutil.which("tesseract"):
        return False
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    return lang in out.split()


def _scanned_essay(path, tmp_path):
    """4 typeset pages (centred title on p.1, running heads with folios on both sides on pp.2-4, justified prose),
    rasterised to an image-only PDF like a scan."""
    import pypdfium2 as pdfium
    from PIL import Image
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph as P

    src = tmp_path / "src.pdf"
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(src), pagesize=A5)
    W, H = A5
    body = ParagraphStyle("b", fontName="Times-Roman", fontSize=11, leading=14, alignment=4, firstLineIndent=14)
    # alternate runs of x-height-only words and words with ascenders + descenders: raw OCR box heights then differ
    # by ~2x between lines (what made accented French lines look like headings)
    low = "a man saw an ocean as we came over a mere a wave rose over our vessel once more ".split()
    tall = "philosophy typography lengthy highly playfully jolly bodily geography ".split()
    for pno in range(1, 5):
        y = H - 50
        if pno == 1:
            c.setFont("Times-Bold", 22)
            c.drawCentredString(W / 2, H - 90, "THE EXPERIMENTAL NOVEL")
            y = H - 130
        else:
            c.setFont("Times-Roman", 9)
            head = "THE EXPERIMENTAL NOVEL."
            c.drawString(50, H - 35, f"{pno}  {head}" if pno % 2 == 0 else head)
            if pno % 2:
                c.drawRightString(W - 50, H - 35, str(pno))
        for k in range(3):
            seq = [(tall if 30 <= i < 42 else low)[(pno + k + i) % 8] for i in range(70)]  # one tall run
            text = " ".join(seq).capitalize() + "."
            para = P(text, body)
            _, h = para.wrap(W - 100, y)
            para.drawOn(c, 50, y - h)
            y -= h + 8
        c.showPage()
    c.save()
    pdf = pdfium.PdfDocument(str(src))
    imgs = [pdf[i].render(scale=200 / 72, grayscale=True).to_pil().convert("L") for i in range(len(pdf))]
    pdf.close()
    imgs = [Image.open(io.BytesIO(_jpeg(i))) for i in imgs]
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:], resolution=200)
    return path


def _jpeg(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


@pytest.mark.skipif(not _tesseract_has("eng"), reason="tesseract with English data not installed")
def test_scanned_essay_has_one_chapter_one_heading_and_no_running_heads(tmp_path):
    pdf = _scanned_essay(tmp_path / "scan.pdf", tmp_path)
    res = convert(pdf, tmp_path / "s.epub", ConvertOptions(ocr="auto", ocr_langs="eng"))
    assert res.ocr_pages == 4
    z = zipfile.ZipFile(tmp_path / "s.epub")
    docs = [etree.fromstring(z.read(n)) for n in sorted(z.namelist()) if re.match(r"OEBPS/ch\d+\.xhtml", n)]
    heads = ["".join(h.itertext()) for d in docs for tag in ("h1", "h2", "h3", "h4") for h in d.iter(XHTML + tag)]
    paras = ["".join(p.itertext()) for d in docs for p in d.iter(XHTML + "p")]
    assert res.chapter_count == 1 and len(docs) == 1
    assert len(heads) == 1 and "EXPERIMENTAL" in heads[0].upper()
    assert not any("THE EXPERIMENTAL NOVEL" in p for p in paras)  # running heads (upper case) removed
    # 12 typeset paragraphs; OCR may split a few, but not line by line
    assert 10 <= len(paras) <= 16


CORPUS = __import__("pathlib").Path(__file__).resolve().parents[4] / "tests" / ".corpus"


@pytest.mark.parametrize("name,lang", [("scan-only-en", "eng"), ("scan-only-fr", "fra")])
def test_real_scanned_excerpts_are_not_split_into_chapters(name, lang, tmp_path):
    """The excerpts reported from the frozen binaries (6 pages -> 37 chapters; body lines as h1/h2). Needs the corpus
    (`python tests/corpus/fetch.py`) and tesseract language data, else skipped."""
    pdf = CORPUS / f"{name}.pdf"
    if not pdf.exists() or not _tesseract_has(lang):
        pytest.skip("corpus file or tesseract language data missing")
    res = convert(pdf, tmp_path / "o.epub", ConvertOptions(ocr="auto", ocr_langs=lang))
    z = zipfile.ZipFile(tmp_path / "o.epub")
    docs = [z.read(n).decode() for n in z.namelist() if re.match(r"OEBPS/ch\d+\.xhtml", n)]
    heads = [h for d in docs for h in re.findall(r"<h[1-4][^>]*>([^<]*)<", d) if h != res.title]  # minus synthetic title
    assert res.ocr_pages == res.page_count and res.chapter_count <= 2
    assert len(heads) <= 2 and all(len(h) <= 60 and not h[:1].islower() for h in heads)
    assert not any(re.search(r"LE ROMAN EXP[ÉE]RIMENTAL\.", d) for d in docs)  # running head of the French excerpt
