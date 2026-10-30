from collections import Counter

from pdftoepub.core import layout, ocr, structure
from pdftoepub.core.ir import Line, Run, Span
from pdftoepub.core.layout import Ctx, Flow, xycut


def ctx(**kw) -> Ctx:
    c = Ctx(body_size=10.0, median_height=12.0)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def plain(runs):
    return "".join(r.text for r in runs)


def test_dehyphenation_drops_line_end_hyphen():
    out = structure.join_runs([Run("an inter-")], [Run("national treaty")], ctx())
    assert plain(out) == "an international treaty"


def test_dehyphenation_keeps_known_compound_and_capitalised():
    c = ctx(hyph_vocab=Counter({"well-known": 3}))
    assert plain(structure.join_runs([Run("a well-")], [Run("known fact")], c)) == "a well-known fact"
    assert plain(structure.join_runs([Run("Jean-")], [Run("Pierre came")], ctx())) == "Jean-Pierre came"


def test_dehyphenation_keeps_french_inversion():
    assert plain(structure.join_runs([Run("est-")], [Run("il parti")], ctx())) == "est-il parti"


def test_dehyphenation_uses_vocab_and_soft_hyphen():
    c = ctx(vocab=Counter({"reading": 4}))
    assert plain(structure.join_runs([Run("read-")], [Run("ing room")], c)) == "reading room"
    assert plain(structure.join_runs([Run("exam­")], [Run("ple")], ctx())) == "example"


def test_normalize_runs_merges_and_moves_whitespace():
    runs = structure.normalize_runs([Run("a "), Run("bold ", bold=True), Run("text", bold=True), Run("  end")])
    assert [(r.text, r.bold) for r in runs] == [("a ", False), ("bold text", True), (" end", False)]


def test_unicode_superscript_digits_become_sup_runs():
    runs = structure.normalize_runs([Run("word¹ next")])
    assert [(r.text, r.sup) for r in runs] == [("word", False), ("1", True), (" next", False)]


def test_list_marker_detection():
    assert structure._marker("• item")[0] == "ul"
    assert structure._marker("12. item")[:2] == ("ol", 12)
    assert structure._marker("a) item")[0] == "ola"
    assert structure._marker("— said he") is None


def _line(x0, y0, x1, y1, text, size=10.0):
    return Line([Span(text, size, bbox=(x0, y0, x1, y1))], (x0, y0, x1, y1))


def test_xycut_reads_columns_before_rows():
    lines = []
    for i in range(6):
        y = 100 + i * 12
        lines.append(_line(50, y, 250, y + 10, f"L{i}" + "x" * 30))
        lines.append(_line(300, y, 500, y + 10, f"R{i}" + "x" * 30))
    title = _line(50, 50, 500, 70, "A spanning title that crosses both columns", 20)
    flows = xycut(lines + [title], ctx(), True)
    order = [l.text[:2] for f in flows for l in f.items]
    assert order[0] == "A "
    assert order[1:] == [f"L{i}" for i in range(6)] + [f"R{i}" for i in range(6)]
    assert not any(isinstance(f, Flow) and f.kind == "col" for f in xycut(lines, ctx(), False))


def test_running_headers_removed_but_chapter_openers_kept():
    from pdftoepub.core.ir import PageData

    pages = []
    for n in range(1, 9):
        p = PageData(n, 400, 600)
        p.lines.append(_line(50, 20, 200, 30, "My Book Title", 8))
        p.lines.append(_line(180, 560, 220, 570, str(n), 8))
        p.lines.append(_line(50, 200, 350, 210, f"Body text of page {n} " + "word " * 5))
        if n in (2, 5, 8):  # chapter openers: same text near the top but never on neighbouring pages
            p.lines.append(_line(50, 60, 300, 75, "CHAPTER HEAD", 8))
        pages.append(p)
    layout.remove_running(pages, [])
    texts = [l.text for p in pages for l in p.lines]
    assert "My Book Title" not in texts
    assert not any(t.isdigit() for t in texts)
    assert texts.count("CHAPTER HEAD") == 3


def test_tesseract_tsv_parsing():
    tsv = "\t".join(["level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"]) + "\n"
    tsv += "5\t1\t1\t1\t1\t1\t300\t300\t200\t40\t96\tHello\n5\t1\t1\t1\t1\t2\t520\t300\t200\t40\t95\tworld\n"
    lines = ocr.parse_tsv(tsv, 1, 72 / 300)
    assert len(lines) == 1 and lines[0].text == "Hello world"
    assert lines[0].size > 8


def test_detached_bullets_are_not_a_table():
    from pdftoepub.core.tables import detect_text_tables

    lines = []
    for i, t in enumerate(["Waterproof tents", "Dried provisions", "Satellite phone"]):
        y = 100 + i * 16
        lines.append(_line(86, y, 92, y + 12, "•", 11))
        lines.append(_line(104, y, 200, y + 12, t, 11))
    lines += [_line(72, 60, 300, 72, "Intro paragraph line", 11)] * 3
    tables, rest = detect_text_tables(lines, 1, 600)
    assert tables == [] and len(rest) == len(lines)


def test_borderless_table_detected():
    from pdftoepub.core.tables import detect_text_tables

    rows = [["Region", "Revenue", "Growth"], ["Northland", "1200", "4%"], ["Southland", "980", "7%"], ["Eastland", "1430", "2%"]]
    lines = []
    for i, r in enumerate(rows):
        for j, t in enumerate(r):
            x = 72 + j * 110
            lines.append(_line(x, 100 + i * 16, x + 6 * len(t), 112 + i * 16, t, 11))
    lines += [_line(72, 40, 300, 52, "Intro paragraph line", 11)] * 2
    tables, rest = detect_text_tables(lines, 1, 600)
    assert len(tables) == 1 and tables[0].rows[1] == ["Northland", "1200", "4%"] and len(rest) == 2
