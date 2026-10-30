"""Regression tests for problems found on the real-world corpus (tests/corpus/REPORT.md)."""
from pdftoepub.core import layout
from pdftoepub.core.backends.common import ImageStore, figures_from_clusters, fix_spacing_accents, map_pua, style_from_name
from pdftoepub.core.ir import ImageAsset, Line, PageData, Span
from pdftoepub.core.layout import Ctx
from pdftoepub.core.tables import detect_text_tables


def _line(x0, y0, x1, y1, text, size=10.0, **kw):
    return Line([Span(text, size, bbox=(x0, y0, x1, y1), **kw)], (x0, y0, x1, y1))


def test_tesseract_glyphless_font_is_plain_text():
    # Internet Archive / OCRmyPDF text layers use Tesseract's GlyphLessFont, flagged fixed-pitch: it is not code
    assert style_from_name("GlyphLessFont", 8) == (False, False, False)
    assert style_from_name("ABCDEF+GlyphLessFont") == (False, False, False)
    assert style_from_name("Courier", 0)[2] is True


def test_private_use_small_caps_are_mapped_to_letters():
    assert map_pua(" ", "ZTBIHM+LinLibertine") == "a vaste"  # Linux Libertine small caps
    assert map_pua("", "Minion-SC") == "Chap"  # Adobe small caps (U+F7xx)
    assert map_pua("", "SomeOtherFont") == ""  # unknown PUA layouts are left alone


def test_spacing_accents_from_ot1_fonts_are_combined():
    assert fix_spacing_accents("esp`ece d’op´erations") == "espèce d’opérations"
    assert fix_spacing_accents("fa¸con, mˆeme, na¨ıf, ˆıle") == "façon, même, naïf, île"
    assert fix_spacing_accents("x = a´ + b and `code`") == "x = a´ + b and `code`"


def test_shaded_code_box_is_not_rasterised_as_figure():
    store = ImageStore()
    render = lambda r: ImageAsset(b"x" * 10, "image/png", 10, 10)  # noqa: E731
    code = [_line(80, 110 + 12 * i, 300, 120 + 12 * i, f"import torch  # line {i}", mono=True) for i in range(5)]
    box = (72, 100, 520, 180)  # one filled background rectangle behind the listing
    figs, lines = figures_from_clusters([box], 1, 595, 842, code, [], [], render, store, shapes=[box])
    assert figs == [] and len(lines) == 5
    # a real chart: many strokes inside the cluster, a few labels -> figure, labels dropped
    strokes = [(100 + 4 * i, 300, 103 + 4 * i, 300 + (i * 7) % 60) for i in range(60)]
    labels = [_line(110, 365, 140, 373, "0.5"), _line(200, 365, 230, 373, "1.0")]
    figs, lines = figures_from_clusters([(100, 300, 340, 375)], 1, 595, 842, labels, [], [], render, store, shapes=strokes)
    assert len(figs) == 1 and lines == []


def test_dropcap_does_not_swallow_the_following_lines():
    ctx = Ctx(body_size=10.0, median_height=10.0)
    cap = _line(63, 327, 98, 371, "L", 43.3)
    l1 = _line(102, 331, 357, 341, "a vaste cuisine de ferme où s’étirent les")
    l2 = _line(102, 343, 357, 353, "ombres sur le carreau rose, où la vieille")
    l3 = _line(102, 355, 357, 365, "essuie la vaisselle tintante ; là Cyrille")
    fixed = layout.fix_dropcaps([cap, l1, l2, l3], ctx)
    assert len(fixed) == 3 and fixed[0].text.startswith("La vaste")
    assert fixed[0].y1 <= 342  # the merged first line keeps its own height
    rows = layout.join_rows(fixed)
    assert [r.text for r in rows][1:] == [l2.text, l3.text]
    # lines overlapping horizontally are never one visual row, even if their boxes overlap vertically
    tall = _line(63, 327, 357, 371, "L" + l1.text)
    assert len(layout.join_rows([tall, l2, l3])) == 3


def test_prose_column_is_not_absorbed_by_a_borderless_table():
    lines = []
    rows = [["", "LLaMA", "GPT3", "OPT"], ["Gender", "70.6", "62.6", "65.7"], ["Religion", "79.0", "73.3", "68.6"],
            ["Race", "57.0", "64.7", "68.6"], ["Age", "70.1", "64.4", "67.8"]]
    prose = ["if societal biases associated with occupations", "can be captured by the model. For example, a",
             "sentence in the WinoGender dataset is composed", "of three different pronouns and the goal of",
             "the model is to choose the right antecedent."]
    for i, r in enumerate(rows):
        y = 100 + 14 * i
        for j, t in enumerate(r):
            if t:
                x = 80 + 55 * j
                lines.append(_line(x, y, x + 6 * len(t), y + 10, t))
        lines.append(_line(306, y, 524, y + 10, prose[i]))
    tables, rest = detect_text_tables(lines, 1, 595)
    assert len(tables) == 1 and tables[0].bbox[2] < 300
    assert [l.text for l in rest] == prose


def test_line_gap_is_measured_within_columns():
    p = PageData(1, 595, 842)
    for i in range(30):  # two columns, 12 pt pitch, 10 pt lines -> 2 pt gap
        y = 100 + 12 * i
        p.lines.append(_line(50, y + 0.4, 290, y + 10.4, "left column text line " * 2))
        p.lines.append(_line(306, y, 546, y + 10, "right column text line " * 2))
    ctx = layout.compute_ctx([p], True)
    assert 0.15 <= ctx.gap_norm <= 0.25


def test_running_head_on_the_folio_row_is_removed_even_without_a_chain():
    # short chapters: each verso head appears only once between two chapter openers (no 3-page chain)
    pages = []
    for n in range(1, 9):
        p = PageData(n, 420, 595)
        if n % 4 != 1:  # chapter openers (1, 5) carry no running head
            head = "My Ántonia" if n % 2 == 0 else f"Book {n // 4 + 1} — The Shimerdas"
            folio, text = (_line(94, 38, 105, 49, str(n)), _line(321, 38, 374, 49, head)) if n % 2 == 0 else \
                (_line(313, 38, 327, 49, str(n)), _line(47, 38, 160, 49, head))
            p.lines += [folio, text]
        words = ["river", "prairie", "wagon", "harvest", "winter", "kitchen", "orchard", "school"]
        p.lines += [_line(47, 69 + 14 * i, 327, 79 + 14 * i, f"The {words[(n + i) % 8]} and the {words[(n * i) % 8]} {'again ' * (i % 3)}")
                    for i in range(20)]
        pages.append(p)
    layout.remove_running(pages, [])
    texts = [l.text for p in pages for l in p.lines]
    assert not any("Ántonia" in t or "Shimerdas" in t for t in texts)
    assert len(texts) == 8 * 20


def _dense_pdf(path, pages=2, lines=60):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for p in range(pages):
        for i in range(lines):
            c.drawString(50, 800 - 12 * i, f"Page {p + 1} line {i}: the quick brown fox jumps over the lazy dog.")
        c.showPage()
    c.save()
    return path


def test_pdfminer_page_budget_keeps_page_as_image(tmp_path, monkeypatch, backend):
    import pytest

    if backend != "pdfminer":
        pytest.skip("per-page budget is a pdfminer-backend guard")
    from pdftoepub.api import ConvertOptions, convert
    from pdftoepub.core.backends import pdfminer_backend

    pdf = _dense_pdf(tmp_path / "dense.pdf")
    monkeypatch.setattr(pdfminer_backend, "MAX_PAGE_CHARS", 2000)  # each page has ~3800 glyphs
    res = convert(pdf, tmp_path / "a.epub", ConvertOptions(ocr="off"))
    assert sum("too complex" in w for w in res.warnings) == 2
    monkeypatch.setattr(pdfminer_backend, "MAX_PAGE_CHARS", 150_000)
    monkeypatch.setattr(pdfminer_backend, "PAGE_TIMEOUT", -1.0)  # budget already spent at the first check
    res = convert(pdf, tmp_path / "b.epub", ConvertOptions(ocr="off"))
    assert any("too complex" in w and "took more than" in w for w in res.warnings)


def test_ocr_line_sizes_are_snapped_but_headings_kept():
    p = PageData(1, 300, 500, ocr_layer=True)
    sizes = [9.8, 8.7, 9.1, 9.9, 10.2, 9.5, 9.9]
    p.lines = [_line(40, 60 + 14 * i, 260, 70 + 14 * i, "body text line " * 3, s) for i, s in enumerate(sizes)]
    p.lines.append(_line(80, 30, 200, 46, "CHAPTER III", 15.0))
    layout.snap_ocr_sizes(p)
    assert len({l.size for l in p.lines[:-1]}) == 1 and p.lines[-1].size == 15.0


def test_tall_delimiter_pieces_become_one_delimiter():
    assert map_pua("x = x1 ... xn") == "x = [x1 ... xn]"
    assert map_pua("sera   x0,") == "sera { x0,"


def test_chapter_name_next_to_a_chained_running_head_is_removed():
    pages = []
    for n in range(1, 10):
        p = PageData(n, 420, 595)
        if n % 3 == 1:  # chapter opener: big title lower on the page, no running head
            p.lines.append(_line(164, 162, 255, 183, f"CHAPITRE {n // 3 + 1}", 12.0))
        else:
            p.lines += [_line(63, 43, 93, 52, "La glèbe", 9.0), _line(314, 43, 357, 52, f"Chapitre {'I' * (n // 3 + 1)}", 9.0)]
        words = ["champ", "ferme", "blé", "pluie", "soleil", "village", "route", "moulin", "étang"]
        p.lines += [_line(63, 70 + 13 * i, 357, 80 + 13 * i, f"Le {words[(n + i) % 9]} et la {words[(n * i) % 9]} {'encore ' * (i % 3)}")
                    for i in range(15)]
        pages.append(p)
    layout.remove_running(pages, [])
    texts = [l.text for p in pages for l in p.lines]
    assert not any(t.startswith(("La glèbe", "Chapitre")) for t in texts)
    assert sum(t.startswith("CHAPITRE") for t in texts) == 3


def test_paragraph_split_by_a_floating_figure_is_rejoined():
    from pdftoepub.core import structure
    from pdftoepub.core.ir import Figure, Paragraph, Run

    a = Paragraph([Run("There had been nothing strange")], "p", 40, 500, None, False, 10.0)
    fig = Figure("img0005", "", None, 41, 60, "page")
    b = Paragraph([Run("about the tree before, but now it was.")], "p", 41, 300, None, False, 10.0)
    out = structure.merge_across_breaks([a, fig, b], Ctx(body_size=10.0))
    assert [type(x).__name__ for x in out] == ["Paragraph", "Figure"]
    assert structure.plain(out[0].runs) == "There had been nothing strange about the tree before, but now it was."
    c = Paragraph([Run("A new paragraph after the plate.")], "p", 41, 300, None, False, 10.0)
    assert len(structure.merge_across_breaks([a, fig, c], Ctx(body_size=10.0))) == 3


def test_link_urls_with_spaces_are_percent_encoded():
    from pdftoepub.core import structure
    from pdftoepub.core.ir import Chapter, Paragraph, Run

    p = Paragraph([Run("paper", link=("url", "https://proceedings.neurips.cc/paper/92d1e1eb fb.pdf"))], "p", 1)
    structure.resolve_links([Chapter("c", [p])])
    assert p.runs[0].link == ("url", "https://proceedings.neurips.cc/paper/92d1e1eb%20fb.pdf")


def test_ocr_line_jitter_does_not_split_sentences():
    ctx = Ctx(body_size=10.0, median_height=10.0, gap_norm=0.16)
    a = _line(31, 102, 256, 112, "tale qui bégaye peut seule nous donner une idée")
    b = _line(31, 117.3, 256, 127.3, "exacte de la littérature expérimentale qui, née")
    assert layout._is_break(a, b, 31, 256, ctx) is True  # native text: a 0.5 em gap is a paragraph break
    assert layout._is_break(a, b, 31, 256, ctx, ocr=True) is False
    c = _line(31, 102, 256, 112, "et la phrase se termine ici.")
    assert layout._is_break(c, b, 31, 256, ctx, ocr=True) is True


def test_misread_ocr_running_heads_are_removed():
    variants = ["LE ROMAN EXPÉRIMENTAL.", "LE KOMAN EXPÉRIMENTAL.", "LE ROMAN EXPÉRIMENTAI,", "LE ROMAN hXPEKIMENTAL.",
                "LE ROMAN EXPERIMENTAL."]
    pages = []
    words = ["roman", "méthode", "expérience", "science", "nature", "médecin", "romancier", "fait"]
    for n in range(1, 21):
        p = PageData(n, 300, 470, ocr_layer=True)
        y = 22 + (n * 7) % 18  # scans: the head wanders by a few % of the page height
        head = (variants[n // 4 % 5] if n % 4 == 0 else variants[0]) + (f" {n}" if n % 2 else "")
        p.lines.append(_line(60, y, 230, y + 9, (f"{n} " if n % 2 == 0 else "") + head, 8.0))
        p.lines += [_line(30, 50 + 12 * i, 255, 60 + 12 * i, f"Le {words[(n + i) % 8]} de la {words[(n * i) % 8]} {'encore ' * (i % 3)}")
                    for i in range(25)]
        pages.append(p)
    layout.remove_running(pages, [])
    assert not any("ROMAN" in l.text or "KOMAN" in l.text for p in pages for l in p.lines)
    assert sum(len(p.lines) for p in pages) == 20 * 25


def test_ocr_noise_lines_are_dropped_but_short_real_lines_kept():
    from collections import Counter

    ctx = Ctx(body_size=10.0, vocab=Counter({"the": 50, "shepherd": 9, "paid": 4, "heed": 3, "to": 40, "taunt": 3}))
    p = PageData(1, 300, 500, ocr_layer=True)
    texts = ["The shepherd paid no heed to the taunt.", "fathers.", "TSeAd ab oe aa", "ener * KK xk *", "ry yr ye rey CP"]
    p.lines = [_line(30, 40 + 12 * i, 250, 50 + 12 * i, t) for i, t in enumerate(texts)]
    assert layout.drop_ocr_noise([p], ctx) == 3
    assert [l.text for l in p.lines] == texts[:2]
    native = PageData(2, 300, 500, lines=[_line(30, 40, 250, 50, "ry yr ye rey CP")])
    assert layout.drop_ocr_noise([native], ctx) == 0


def test_ocr_noise_filter_keeps_french_lines_with_elisions():
    from collections import Counter

    p = PageData(1, 300, 500, source="ocr")
    p.lines = [_line(30, 40, 250, 50, "Ce qui a déterminé mon choix et l’a arrêté sur l’/4-")]
    assert layout.drop_ocr_noise([p], Ctx(body_size=10.0, vocab=Counter())) == 0


def test_huge_embedded_bitmap_is_not_decoded_at_full_size(tmp_path, monkeypatch, backend):
    import importlib

    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from pdftoepub.core.backends import get_backend

    img = tmp_path / "big.png"
    Image.new("RGB", (3000, 1000), (200, 30, 30)).save(img)
    pdf = tmp_path / "big.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    c.drawString(72, 800, "A page with one very large plot below.")
    c.drawImage(str(img), 72, 400, 400, 133)
    c.showPage()
    c.save()
    mod = importlib.import_module(f"pdftoepub.core.backends.{backend}_backend")
    monkeypatch.setattr(mod, "MAX_DECODE_PIXELS", 1_000_000)  # 3 Mpx counts as huge here
    doc = get_backend()[0].open(pdf)
    store = ImageStore()
    warnings: list[str] = []
    pd = doc.extract_page(1, "inline", store, warnings)
    doc.close()
    assert len(pd.images) == 1 and any("very large image (3000 x 1000 px)" in w for w in warnings)
    asset = store.assets[pd.images[0].image_id]
    assert max(asset.width, asset.height) <= 1600 and asset.width > asset.height
