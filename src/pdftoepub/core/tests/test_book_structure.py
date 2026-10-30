"""A collective volume without outline or metadata (round 5): printed table of contents as the structure, chapter
openings (number, byline), endnotes linked to their references, page list, metadata from the first pages."""
import re
import zipfile

from lxml import etree
from reportlab.pdfgen import canvas

from pdftoepub.api import ConvertOptions, convert
from pdftoepub.core import endnotes, frontmatter, ocrfix, printedtoc
from pdftoepub.core.ir import Endnotes, Footnote, Heading, Line, PageData, Paragraph, Run, Span

X = "{http://www.w3.org/1999/xhtml}"
OPS = "{http://www.idpf.org/2007/ops}"
W, H = 360, 540
OFFSET = 2  # printed page = PDF page + 2
WORDS = ("la critique du travail domestique montre que la vie sociale repose sur des rapports de "
         "production et sur une division sexuée qui traverse les institutions et les familles ouvrières").split()
CHAPTERS = [  # (number, author, title, sections, notes)
    (1, "Alice Martin", "Le travail invisible", ["Une histoire longue", "Les luttes"], 3),
    (2, "Bruno Petit et Clara Roy", "Marchés et usines", ["Le marché", "La résistance"], 4),
    (3, "Diane Morel", "Les villes nouvelles", ["Des identités"], 2),
]


def _prose(seed, n):
    return " ".join(WORDS[(seed * 5 + k) % len(WORDS)] for k in range(n))


def _book(path, starts=None):
    """Two passes: the first records where parts and chapters start, the second prints them in the contents."""
    if starts is None:
        starts = _book(path, {"part1": 1, 1: 1, 2: 1, "part2": 1, 3: 1})
    found = {}
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setAuthor("")
    pno = 0

    def page(running=None):
        nonlocal pno
        if pno:
            c.showPage()
        pno += 1
        if running:  # running head with the printed folio
            c.setFont("Times-Roman", 8)
            folio = pno + OFFSET
            c.drawString(30, H - 25, f"{folio}  {running}" if folio % 2 == 0 else f"{running}  {folio}")

    def text(x, y, s, size=10, font="Times-Roman"):
        c.setFont(font, size)
        c.drawString(x, y, s)

    page()  # 1: title page
    text(60, 400, "Pour une histoire", 24)
    text(60, 370, "du travail urbain", 24)
    text(80, 300, "Volume coordonné par", 11, "Times-Italic")
    text(80, 280, "Jeanne Dubois", 11)
    text(80, 264, "Marc Lefèvre", 11)
    page()  # 2: copyright page
    text(40, 300, "© Éditions Exemple, 2019", 9)
    text(40, 285, "Tous droits réservés", 9)
    text(40, 270, "ISBN : 978-0-306-40615-7", 9)
    page()  # 3: Sommaire
    text(130, 480, "Sommaire", 12, "Times-Bold")
    y = 450
    for key, label, ptitle in (("part1", "Première partie", "Les fondements"), ("part2", "Deuxième partie", "Les villes")):
        text(30, y, label, 9)
        text(30, y - 12, ptitle, 9)
        text(300, y - 12, str(starts[key] + OFFSET), 9)
        y -= 34
        for num, author, title, secs, _ in CHAPTERS:
            if (key == "part1") != (num <= 2):
                continue
            text(30, y, f"{num}.", 9)
            text(45, y, author, 9)
            text(45, y - 12, title, 9)
            text(300, y - 12, str(starts[num] + OFFSET), 9)
            text(45, y - 22, " | ".join(secs), 6)
            y -= 40
    for num, author, title, secs, nnotes in CHAPTERS:
        if num == 3:
            page()  # part 2 divider
            found["part2"] = pno
            text(60, 300, "Deuxième partie", 14)
            text(60, 280, "Les villes", 18)
        elif num == 1:
            page()  # part 1 divider
            found["part1"] = pno
            text(60, 300, "Première partie", 14)
            text(60, 280, "Les fondements", 18)
        page()  # chapter opening: author above the title, no running head
        found[num] = pno
        text(40, 430, author, 11, "Times-Italic")
        text(40, 405, title, 16)
        y = 370
        ref = 1
        for s_i, sec in enumerate(secs):
            text(40, y, sec, 12, "Times-Bold")
            y -= 20
            for k in range(16):
                line = _prose(num * 10 + s_i * 3 + k, 11)
                text(40, y, line)
                if k % 5 == 1 and ref <= nnotes:  # a superscript reference at the line end
                    c.setFont("Times-Roman", 6)
                    c.drawString(40 + c.stringWidth(line, "Times-Roman", 10) + 1, y + 4, str(ref))
                    ref += 1
                y -= 14
                if y < 80:
                    page(title)
                    y = H - 60
            y -= 10
        if y < 200:
            page(title)
            y = H - 60
        text(40, y, "Notes", 12, "Times-Bold")
        y -= 18
        y0 = y
        for n in range(1, nnotes + 1):  # two columns of small type
            col = 0 if n <= (nnotes + 1) // 2 else 1
            if col == 1 and n == (nnotes + 1) // 2 + 1:
                y = y0
            text(40 + col * 150, y, f"{n}. Voir Auteur {n}, 2010, p. {n + 10}.", 6.5)
            y -= 10
    c.showPage()
    c.save()
    return found


def test_printed_contents_drive_the_structure(tmp_path):
    pdf = tmp_path / "volume-9780306406157.pdf"
    _book(pdf)
    out = tmp_path / "v.epub"
    res = convert(pdf, out, ConvertOptions(ocr="off"))
    z = zipfile.ZipFile(out)
    opf = z.read("OEBPS/content.opf").decode()
    assert "<dc:title>Pour une histoire du travail urbain</dc:title>" in opf
    assert "Jeanne Dubois</dc:creator>" in opf and 'scheme="marc:relators">edt</meta>' in opf
    assert "urn:isbn:9780306406157" in opf and "<dc:publisher>Éditions Exemple</dc:publisher>" in opf
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    toc = next(n for n in nav.iter(X + "nav") if n.get(OPS + "type") == "toc")
    top = [li for li in toc.find(X + "ol")]
    tops = ["".join(li.find(X + "a").itertext()) for li in top]
    assert any("Première partie" in t and "Les fondements" in t for t in tops)
    part1 = next(li for li in top if "Les fondements" in "".join(li.find(X + "a").itertext()))
    nested = ["".join(a.itertext()) for a in part1.iter(X + "a")][1:]
    assert any(t.startswith("1. Le travail invisible") for t in nested)
    assert any(t.startswith("2. Marchés et usines") for t in nested)
    assert any("Une histoire longue" in t for t in nested)  # a section from the printed list
    assert not any("Martin" in t for t in nested)  # authors are bylines, not navigation entries
    assert res.chapter_count >= 6  # front matter, 2 part openers, 3 chapters
    # chapter 2: h1 with its number, byline, linked endnotes in one section
    ch = next(n for n in z.namelist() if n.endswith(".xhtml") and "Marchés et usines</h1>" in z.read(n).decode())
    root = etree.fromstring(z.read(ch))
    assert root.find(f".//{X}p[@class='byline']") is not None
    sec = [s for s in root.iter(X + "section") if s.get(OPS + "type") == "endnotes"]
    assert len(sec) == 1 and len(list(sec[0].iter(X + "li"))) == 4
    refs = [a for a in root.iter(X + "a") if a.get(OPS + "type") == "noteref"]
    assert len(refs) >= 3
    # page list with printed numbers
    pl = next(n for n in nav.iter(X + "nav") if n.get(OPS + "type") == "page-list")
    labels = ["".join(a.itertext()) for a in pl.iter(X + "a")]
    assert "7" in labels and len(labels) >= 8  # PDF page 5 is printed page 7


def test_contents_rows_parse_into_parts_chapters_and_sections():
    def ln(t, x, y, size=9.0):
        return Line([Span(t, size, bbox=(x, y, x + 5 * len(t), y + size))], (x, y, x + 5 * len(t), y + size), 3)
    p = PageData(3, 360, 540, lines=[ln("Sommaire", 130, 40, 12), ln("Introduction", 30, 70), ln("9", 300, 70),
                                     ln("Première partie", 30, 100), ln("Les fondements", 30, 112), ln("12", 300, 112),
                                     ln("1.", 30, 140), ln("Alice Martin", 45, 140), ln("Le travail", 45, 152),
                                     ln("invisible", 45, 164), ln("13", 300, 164),
                                     ln("Une histoire | Les luttes", 45, 176, 6.0)])
    entries, pages = printedtoc.parse([p])
    assert pages == [3]
    kinds = [(e.kind, e.level, e.title, e.printed) for e in entries]
    assert kinds == [("other", 1, "Introduction", 9), ("part", 1, "Les fondements", 12),
                     ("chapter", 2, "Le travail invisible", 13)]
    assert entries[2].authors == ["Alice Martin"] and entries[2].sections == ["Une histoire", "Les luttes"]
    assert entries[1].number == 1 and entries[1].label == "Première partie"


def test_page_offset_needs_agreeing_folios():
    assert printedtoc.page_offset({10: 12, 11: 13, 12: 14, 13: 99}) == 2
    assert printedtoc.page_offset({10: 12, 11: 40}) is None


def test_metadata_from_the_first_pages():
    def ln(t, y, size):
        return Line([Span(t, size, bbox=(40, y, 300, y + size))], (40, y, 300, y + size), 1)
    title = PageData(1, 360, 540, lines=[ln("Pour une histoire", 100, 24), ln("du travail urbain", 130, 24),
                                         ln("Volume coordonné par", 200, 11), ln("Jeanne Dubois", 215, 11),
                                         ln("Marc Lefèvre", 230, 11)])
    imprint = PageData(2, 360, 540, lines=[ln("© Éditions Exemple, 2019", 100, 9), ln("ISBN 978-0-306-40615-7", 120, 9)])
    from collections import Counter
    meta = frontmatter.from_pages([title, imprint], 10.0, Counter({"pourunehistoiredutravailurbain": 40}))
    assert meta.title == "Pour une histoire du travail urbain"
    assert meta.editors == ["Jeanne Dubois", "Marc Lefèvre"]
    assert (meta.publisher, meta.year, meta.isbn) == ("Éditions Exemple", "2019", "9780306406157")
    assert frontmatter.isbn_ok("9780306406157") and not frontmatter.isbn_ok("9780306406158")
    assert frontmatter.title_from_filename("dokumen.pub_pour-une-histoire-9780306406157") == "pour une histoire"


def test_endnote_lines_split_by_number_across_columns_and_link_back():
    def ln(t, x, y, page=9):
        return Line([Span(t, 6.5, bbox=(x, y, x + 100, y + 6.5))], (x, y, x + 100, y + 6.5), page)
    from pdftoepub.core.layout import RawBlock
    head = RawBlock("text", 9, 100, [Line([Span("Notes", 12, bold=True, bbox=(40, 100, 80, 112))], (40, 100, 80, 112), 9)])
    left = RawBlock("text", 9, 120, [ln("1. Voir Auteur, 2010.", 40, 120), ln("2. Ibid., p. 4, et pour", 40, 130),
                                     ln("une suite, Autre, 2012.", 40, 140)])
    right = RawBlock("text", 9, 120, [ln("3. Troisième note.", 200, 120), ln("4. Quatrième note.", 200, 130)])
    out = endnotes.extract([head, left, right], {}, {9: 360})
    blk = next(b for b in out if b.kind == "endnotes")
    notes = blk.item[1]
    assert [n.number for n in notes] == [1, 2, 3, 4]
    assert " ".join(l.text.strip() for l in notes[1].lines) == "Ibid., p. 4, et pour une suite, Autre, 2012."
    fns = [Footnote(f"en1-{n}", [Run("x")], str(n), 9, orphan=True) for n in (1, 2, 3, 4)]
    text = Paragraph([Run("un mot"), Run("2", sup=True), Run(" et la suite")], "p", 8)
    assert endnotes.link([text, Endnotes(fns, 9)]) == 1
    assert text.runs[1].noteref == "en1-2" and not fns[1].orphan and fns[0].orphan


def test_ocr_corrections_are_conservative():
    body = [Paragraph([Run("Tolstoï " * 3 + "Kaufman " * 3 + "of " * 3 + "California " * 3)], "p", 1),
            Paragraph([Run("au xix"), Run("c", sup=True), Run(" siècle, lbid., Tbe end, voir Tolstoî et Kaufrnan, "
                                                                 "University ofCalifornia, en 2 0 1 0, contrepartie.")],
                      "p", 2)]
    done = ocrfix.correct(body)
    t = "".join(r.text for r in body[1].runs)
    assert "xixe" in t and "Ibid." in t and "The end" in t and "Tolstoï et Kaufman" in t
    assert "of California" in t and "2010" in t and "contrepartie" in t
    assert done["lexicon"] == 2 and done["camel"] == 1


def test_running_head_with_a_misread_folio_is_still_a_running_head():
    from pdftoepub.core.layout import _norm_key
    assert _norm_key("39<> Pour un livre") == _norm_key("14 Pour un livre") == _norm_key("Pour un livre 2O5")
    assert _norm_key("Il était une fois") == "iletaitunefois"


def test_scan_page_images_blank_dark_or_pictures():
    from PIL import Image, ImageDraw

    from pdftoepub.core.pipeline import _scan_is_redundant

    blank = Image.new("L", (120, 180), 230)
    assert _scan_is_redundant(PageData(1, 360, 540), blank) == (True, False)
    specks = blank.copy()
    ImageDraw.Draw(specks).point([(10, 10), (50, 90), (100, 150)], fill=0)
    assert _scan_is_redundant(PageData(1, 360, 540), specks)[0]
    plate = blank.copy()
    ImageDraw.Draw(plate).ellipse((20, 30, 100, 150), fill=40)  # an illustration
    assert not _scan_is_redundant(PageData(1, 360, 540), plate)[0]
    divider = Image.new("L", (120, 180), 255)  # a black block in a white margin, white title inside
    d = ImageDraw.Draw(divider)
    d.rectangle((8, 8, 112, 172), fill=0)
    d.rectangle((30, 40, 95, 52), fill=255)
    title = Line([Span("Sur les villes", 18, bbox=(90, 120, 285, 156))], (90, 120, 285, 156), 1)
    assert _scan_is_redundant(PageData(1, 360, 540, lines=[title]), divider) == (True, True)


def test_quotes_and_lowercase_continuations_join_across_pages():
    from pdftoepub.core import structure
    from pdftoepub.core.layout import Ctx

    q1 = Paragraph([Run("la phrase citée continue sans point")], "blockquote", 4, 400, None, True, 10.0)
    q2 = Paragraph([Run("et se termine ici.")], "blockquote", 5, 60, "page", True, 10.0)
    p1 = Paragraph([Run("une étude des archives municipales.")], "p", 6, 400, None, False, 10.0)
    p2 = Paragraph([Run("montrerait les liens entre les quartiers.")], "p", 7, 60, "page", True, 10.0)
    p3 = Paragraph([Run("Un nouveau paragraphe.")], "p", 7, 120, None, True, 10.0)
    out = structure.merge_across_breaks([q1, q2, p1, p2, p3], Ctx(body_size=10.0))
    assert [structure.plain(b.runs) for b in out] == [
        "la phrase citée continue sans point et se termine ici.",
        "une étude des archives municipales. montrerait les liens entre les quartiers.", "Un nouveau paragraphe."]
    assert [r.pagebreak for r in out[0].runs if r.pagebreak] == [5]  # where page 5 begins, for the page list


def test_rejected_page_notes_keep_their_numbers():
    from pdftoepub.core.layout import Ctx, split_footnotes

    def ln(t, y):
        return Line([Span(t, 7.0, bbox=(40, y, 300, y + 7))], (40, y, 300, y + 7), 3)
    body = [Line([Span(f"Ligne de texte {i} assez longue pour le corps.", 10.0, bbox=(40, 60 + 14 * i, 300, 70 + 14 * i))],
                 (40, 60 + 14 * i, 300, 70 + 14 * i), 3) for i in range(10)]
    page = PageData(3, 360, 540, lines=body + [ln("4. Martin, 2011.", 400), ln("7. Durand, 1997.", 412)])
    notes, lines = split_footnotes(page, Ctx(body_size=10.0))
    assert not notes and any(l.text.strip() == "4. Martin, 2011." for l in lines)


def test_contents_rows_taken_by_the_table_detector_are_read_back():
    from pdftoepub.core.ir import TableItem

    def ln(t, x, y, size=9.0):
        return Line([Span(t, size, bbox=(x, y, x + 5 * len(t), y + size))], (x, y, x + 5 * len(t), y + size), 3)
    table = TableItem((30, 100, 310, 156), [["Deuxième partie", ""], ["Les villes", "11"], ["3. Diane Morel", ""],
                                            ["Les villes nouvelles", "12"]], 3)
    p = PageData(3, 360, 540, lines=[ln("Sommaire", 130, 40, 12), ln("Les fondements", 30, 70), ln("6", 300, 70),
                                     ln("1. Alice Martin", 30, 82), ln("Le travail invisible", 45, 94), ln("7", 300, 94)],
                 tables=[table])
    entries, _ = printedtoc.parse([p])
    assert [(e.kind, e.title, e.printed) for e in entries] == [
        ("other", "Les fondements", 6), ("chapter", "Le travail invisible", 7), ("part", "Les villes", 11),
        ("chapter", "Les villes nouvelles", 12)]


def test_ocr_noise_is_no_heading():
    from pdftoepub.core.structure import garbled_heading

    assert garbled_heading("MeeISLAND PLANT") and garbled_heading("_i")
    assert not any(garbled_heading(t) for t in ("ISLAND PLANT", "I. THE ROOTS.", "LLaMA", "Le XIXe siècle", "1.B.", "II"))


def test_authors_printed_in_the_title_block_become_a_byline():
    assert printedtoc._author_prefix("Alice Martin Le travail invisible", ["Alice Martin"]) == (
        "Alice Martin", "Le travail invisible")
    assert printedtoc._author_prefix("Bruno Petit et Clara Roy Marchés et usines", ["Bruno Petit", "Clara Roy"]) == (
        "Bruno Petit et Clara Roy", "Marchés et usines")
    assert printedtoc._author_prefix("Le travail invisible", ["Alice Martin"]) is None


def test_a_divider_entry_holds_the_chapter_that_follows():
    def ln(t, x, y, size=9.0):
        return Line([Span(t, size, bbox=(x, y, x + 5 * len(t), y + size))], (x, y, x + 5 * len(t), y + size), 3)
    p = PageData(3, 360, 540, lines=[ln("Sommaire", 130, 40, 12), ln("Introduction", 30, 70), ln("9", 300, 70),
                                     ln("1. Le travail invisible", 30, 82), ln("10", 300, 82),
                                     ln("Première partie", 30, 100), ln("Les fondements", 30, 112), ln("40", 300, 112),
                                     ln("2. Marchés et usines", 30, 124), ln("41", 300, 124),
                                     ln("Épilogue", 30, 140), ln("90", 300, 140),
                                     ln("3. Les villes nouvelles", 30, 152), ln("91", 300, 152)])
    entries, _ = printedtoc.parse([p])
    assert [(e.title, e.level) for e in entries] == [
        ("Introduction", 1), ("Le travail invisible", 2), ("Les fondements", 1), ("Marchés et usines", 2),
        ("Épilogue", 1), ("Les villes nouvelles", 2)]


def test_a_page_marker_never_cuts_a_word():
    from pdftoepub.core import structure
    from pdftoepub.core.layout import Ctx

    a = Paragraph([Run("la physiologie et la phy-")], "p", 4, 400, None, False, 10.0)
    b = Paragraph([Run("siologie expérimentale.")], "p", 5, 60, "page", False, 10.0)
    c = Paragraph([Run("le monde, de l'homme elle-")], "p", 5, 400, None, False, 10.0)
    d = Paragraph([Run("même. Fin.")], "p", 6, 60, "page", False, 10.0)
    out = structure.merge_across_breaks([a, b, c, d], Ctx(body_size=10.0))
    for p in out:
        i = next(k for k, r in enumerate(p.runs) if r.pagebreak)
        before = "".join(r.text for r in p.runs[:i])
        assert before.endswith(" ") or not before, before  # the marker sits between two words
