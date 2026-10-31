"""Navigation of novels from free-ebook publishers (round 8): a fleuron set as a lone letter is no heading, a
"CHAPITRE II" label above the title opens its chapter, publisher pages before chapter I stay one entry, and with an
outline the navigation is the outline."""
import re
import zipfile

from lxml import etree
from reportlab.pdfgen import canvas

from pdftoepub.api import ConvertOptions, convert

X = "{http://www.w3.org/1999/xhtml}"
OPS = "{http://www.idpf.org/2007/ops}"
W, H = 360, 540
WORDS = ("le voyageur arriva au village un soir de juillet et demanda une chambre a l aubergiste qui le regarda "
         "longtemps avant de repondre que la maison etait pleine depuis la foire").split()
TITLES = ["Le voyageur", "La foire", "Le retour", "Les adieux"]
ROMAN = ["I", "II", "III", "IV"]


def _prose(seed, n):
    return " ".join(WORDS[(seed * 7 + k) % len(WORDS)] for k in range(n))


def _novel(path, outline: bool, titled: bool):
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setAuthor("")
    c.setTitle("")

    def text(x, y, s, size=10, font="Times-Roman"):
        c.setFont(font, size)
        c.drawString(x, y, s)

    text(60, 400, "JEAN EXEMPLE", 14)  # title page
    text(60, 360, "LE VOYAGEUR", 26)
    c.showPage()
    text(40, 480, "À propos de l'éditeur :", 14, "Times-Bold")  # publisher's pages
    for k in range(6):
        text(40, 460 - 14 * k, _prose(90 + k, 10))
    text(40, 340, "Licence", 14, "Times-Bold")
    for k in range(4):
        text(40, 320 - 14 * k, _prose(80 + k, 10))
    c.showPage()
    for n, (num, title) in enumerate(zip(ROMAN, TITLES), 1):
        c.bookmarkPage(f"ch{n}")
        if outline:
            c.addOutlineEntry(title, f"ch{n}", level=0)
        text(40, 470, f"CHAPITRE {num}", 12, "Times-Bold")
        if titled:
            text(40, 440, title, 20)
        y = 400
        for page in range(2):
            for k in range(22):
                text(40, y, _prose(n * 31 + page * 23 + k, 11))
                y -= 14
            if page == 0:
                c.showPage()
                y = H - 60
        text(170, y - 30, "n", 20)  # the end-of-chapter fleuron: "n" in an ornament font, extracted as a letter
        c.showPage()
    c.save()


def _nav(z):
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    toc = next(n for n in nav.iter(X + "nav") if n.get(OPS + "type") == "toc")
    return ["".join(a.itertext()).strip() for a in toc.iter(X + "a")]


def _headings(z):
    out = {}
    for n in sorted(z.namelist()):
        if re.search(r"ch\d+\.xhtml$", n):
            root = etree.fromstring(z.read(n))
            out[n] = ["".join(h.itertext()).strip() for h in root.iter() if h.tag in (X + "h1", X + "h2", X + "h3")]
    return out


def test_outline_novel_navigation_is_the_outline(tmp_path):
    pdf = tmp_path / "le-voyageur.pdf"
    _novel(pdf, outline=True, titled=True)
    out = tmp_path / "v.epub"
    convert(pdf, out, ConvertOptions(ocr="off"))
    z = zipfile.ZipFile(out)
    nav = _nav(z)
    assert nav[1:] == TITLES  # front matter, then the outline: no "n", no "Licence", no "CHAPITRE II"
    heads = _headings(z)
    flat = [h for hs in heads.values() for h in hs]
    assert "n" not in flat
    for num, title in zip(ROMAN, TITLES):  # the label opens its own chapter, joined to the title
        f = next(n for n, hs in heads.items() if hs and hs[0].endswith(title))
        assert heads[f][0] == f"CHAPITRE {num} — {title}"
        assert not any(h == f"CHAPITRE {num}" for h in flat)


def test_labelled_chapters_without_outline_keep_the_front_matter_together(tmp_path):
    pdf = tmp_path / "le-voyageur.pdf"
    _novel(pdf, outline=False, titled=False)
    out = tmp_path / "v.epub"
    convert(pdf, out, ConvertOptions(ocr="off"))
    z = zipfile.ZipFile(out)
    nav = _nav(z)
    assert nav[1:] == [f"CHAPITRE {r}" for r in ROMAN]  # one entry for the title and publisher's pages
    assert not any(h == "n" for hs in _headings(z).values() for h in hs)
