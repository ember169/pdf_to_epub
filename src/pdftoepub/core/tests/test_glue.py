"""Glued words in OCR'd text ("danslavie" -> "dans la vie"), with a tiny synthetic lexicon in wordfreq's format."""
import gzip
import io
import struct
import zipfile

import pytest

from pdftoepub.core import glue, lexicon
from pdftoepub.core.ir import Paragraph, Run

FR = {"de": 7.7, "la": 7.4, "le": 7.4, "les": 7.3, "et": 7.3, "il": 7.0, "dans": 6.9, "pour": 6.7, "une": 6.9, "a": 6.9,
      "à": 7.2, "vie": 5.9, "exemple": 5.3, "par": 6.7, "drap": 3.5, "politique": 5.4, "cet": 5.9, "sur": 6.6,
      "travail": 5.4, "dela": 3.3, "contre": 6.0, "partie": 5.4, "contrepartie": 3.8, "maison": 5.4, "entre": 6.1}
EN = {"the": 7.7, "of": 7.4, "and": 7.4, "differently": 4.2, "abled": 3.1, "able": 5.3}


def _pack(obj) -> bytes:
    """The MessagePack subset wordfreq writes (arrays, maps, strings, small ints)."""
    if isinstance(obj, dict):
        return bytes([0x80 | len(obj)]) + b"".join(_pack(k) + _pack(v) for k, v in obj.items())
    if isinstance(obj, list):
        head = bytes([0x90 | len(obj)]) if len(obj) < 16 else b"\xdc" + struct.pack(">H", len(obj))
        return head + b"".join(_pack(x) for x in obj)
    if isinstance(obj, str):
        b = obj.encode("utf-8")
        return (bytes([0xA0 | len(b)]) if len(b) < 32 else b"\xd9" + bytes([len(b)])) + b
    return bytes([obj])


def _write(dirpath, lang, freqs):
    bins: list = [[] for _ in range(900)]
    for w, z in freqs.items():
        bins[round((9 - z) * 100)].append(w)
    data = _pack([{"format": "cB", "version": 1}] + bins)
    (dirpath / f"large_{lang}.msgpack.gz").write_bytes(gzip.compress(data))


@pytest.fixture
def lexicons(tmp_path, monkeypatch):
    _write(tmp_path, "fr", FR)
    _write(tmp_path, "en", EN)
    monkeypatch.setenv("PDFTOEPUB_LEXICON_DIR", str(tmp_path))
    lexicon.table.cache_clear()
    yield
    lexicon.table.cache_clear()


def test_the_wordfreq_format_is_read(lexicons):
    t = lexicon.table("fr")
    assert abs(t["dans"] - 6.9) < 0.011 and abs(t["contrepartie"] - 3.8) < 0.011 and "danslavie" not in t
    assert lexicon.table("de") == {}


def _para(text):
    return Paragraph([Run(text)], "p", 1)


def test_glued_words_are_split_and_real_words_left_alone(lexicons):
    blocks = [_para("prendre du plaisir danslavie, voir parexemple la maison. Une contrepartie, unepolitique ;"),
              _para("Le mot Danslavie, le code dans2vie, www.danslavie.fr, a@danslavie.fr, et drapa ; dela."),
              _para("une travaille répétée travaille ; les differently abled")]
    changes = glue.split_glued(blocks, "fr")
    texts = ["".join(r.text for r in b.runs) for b in blocks]
    assert "danslavie," not in texts[0] and "dans la vie," in texts[0] and "par exemple" in texts[0]
    assert "une politique" in texts[0] and "contrepartie" in texts[0]  # a word of the list stays whole
    # capitalised, digits, addresses, a one-letter part beside an uncommon word, a list typo: untouched
    assert texts[1] == "Le mot Danslavie, le code dans2vie, www.danslavie.fr, a@danslavie.fr, et drapa ; dela."
    assert "travaille" in texts[2] and "abled" in texts[2]  # repeated in the book; a word of the other language
    assert sorted(changes) == [("danslavie", "dans la vie"), ("parexemple", "par exemple"),
                               ("unepolitique", "une politique")]


def test_no_lexicon_no_change(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFTOEPUB_LEXICON_DIR", str(tmp_path / "missing"))
    lexicon.table.cache_clear()
    blocks = [_para("plaisir danslavie")]
    assert glue.split_glued(blocks, "fr") == [] and blocks[0].runs[0].text == "plaisir danslavie"
    lexicon.table.cache_clear()


def _scan_pdf(path, invisible: bool):
    """A page image with the text drawn over it invisibly (an OCR layer), or a born-digital page (visible text)."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(400, 600))
    if invisible:
        img = Image.new("L", (400, 600), 235)
        c.drawImage(ImageReader(img), 0, 0, 400, 600)
    sentences = ["Le travail de la vie est dans la maison et dans la politique.",
                 "Pour une vie de travail et de politique, la maison est une partie."]
    for i in range(18):
        t = c.beginText(30, 560 - 14 * i)
        t.setFont("Times-Roman", 10)
        if invisible:
            t.setTextRenderMode(3)
        t.textOut("Il prend du plaisir danslavie et dans le travail de la maison." if i == 0 else sentences[i % 2])
        c.drawText(t)
    c.showPage()
    c.save()


@pytest.mark.parametrize("invisible", [True, False])
def test_only_ocr_text_is_repaired(lexicons, tmp_path, invisible):
    from pdftoepub.api import ConvertOptions, convert

    pdf = tmp_path / "s.pdf"
    _scan_pdf(pdf, invisible)
    convert(pdf, tmp_path / "s.epub", ConvertOptions(ocr="off"))
    z = zipfile.ZipFile(tmp_path / "s.epub")
    text = " ".join(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml"))
    assert ("dans la vie" in text) == invisible and ("danslavie" in text) != invisible
