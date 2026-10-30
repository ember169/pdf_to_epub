"""Chapters of scanned books from the page layout (`openings`): opening pages, half-titles, printed TOC, consistency."""
from collections import Counter

from pdftoepub.core import layout, openings, structure
from pdftoepub.core.ir import Heading, Line, PageData, Span

W, H = 400.0, 600.0
VOCAB = ("the island lay quiet under a grey sky while the boats came home slowly and the women waited on the "
         "wharf with baskets of bread and the children ran along the sand calling out names of fathers").split()


def _line(text, y, x0=40.0, x1=None, size=10.0, pno=1):
    x1 = x1 if x1 is not None else x0 + 5.2 * len(text)
    return Line([Span(text, size, bbox=(x0, y, x1, y + size * 1.2))], (x0, y, x1, y + size * 1.2), pno)


def _centred(text, y, size=10.0, pno=1):
    w = 5.2 * len(text) * size / 10
    return _line(text, y, (W - w) / 2, (W + w) / 2, size, pno)


def _body(pno, y0, n=None, seed=0):
    n = n if n is not None else int((560 - y0) // 14)
    out = []
    for i in range(n):
        words = [VOCAB[(pno * 7 + seed + i * 3 + k) % len(VOCAB)] for k in range(11)]
        text = " ".join(words)
        text = text[:1].upper() + text[1:] + ("." if i % 4 == 3 else "")
        out.append(_line(text, y0 + 14 * i, 40.0, 360.0, pno=pno))
    return out


def _page(pno, lines):
    return PageData(pno, W, H, lines=lines, ocr_layer=True)


def _book(openings_at: dict[int, list[tuple[str, float]]], n=14, half: dict[int, str] | None = None,
          extra: dict[int, list[Line]] | None = None):
    """OCR-layer pages of running text; `openings_at[p]` = centred title lines [(text, size)] lower on the page."""
    pages = []
    for p in range(1, n + 1):
        if half and p in half:
            pages.append(_page(p, [_centred(half[p], 250, 11, p)]))
            continue
        if extra and p in extra:
            pages.append(_page(p, extra[p]))
            continue
        if p in openings_at:
            y = 150.0
            lines = []
            for text, size in openings_at[p]:
                lines.append(_centred(text, y, size, p))
                y += 1.6 * size + 2
            lines += _body(p, y + 24)
            pages.append(_page(p, lines))
        else:
            pages.append(_page(p, _body(p, 60)))
    return pages


def _convert(pages, title="An Island Plant"):
    running: Counter = Counter()
    layout.remove_running(pages, [], running)
    ctx = layout.compute_ctx(pages, True)
    raw = []
    for p in pages:
        raw += layout.page_blocks(p, ctx)[0]
    plan = openings.plan(raw, pages, ctx, running, title)
    model = structure.build_heading_model(raw, ctx)
    blocks, _ = structure.convert_blocks(raw, ctx, {}, model, plan)
    chapters = structure.build_chapters(blocks, [], len(pages), title, [])
    return plan, chapters, blocks


def test_chapter_openings_on_scanned_pages_with_a_misread_numeral():
    pages = _book({3: [("I.", 10), ("THE ROOTS.", 10)], 7: [("II.", 10), ("THE GREEN BRANCHES.", 10)],
                   11: [("BE:", 10), ("THE RESULT OF DROUGHT AND WINTER.", 10)]})
    plan, chapters, _ = _convert(pages)
    assert plan is not None and plan.chapters == 3
    titles = [c.title for c in chapters]
    assert titles[-3:] == ["I. THE ROOTS.", "II. THE GREEN BRANCHES.", "III. THE RESULT OF DROUGHT AND WINTER."]
    assert len(chapters) == 4  # + the pages before chapter I


def test_one_centred_title_is_not_a_pattern():
    plan, chapters, _ = _convert(_book({3: [("THE ROOTS.", 10)]}))
    assert plan is None and len(chapters) == 1


def test_short_scanned_excerpts_keep_the_conservative_model():
    pages = _book({2: [("I.", 10), ("ONE.", 10)], 3: [("II.", 10), ("TWO.", 10)], 5: [("III.", 10), ("THREE.", 10)]}, n=6)
    plan, chapters, _ = _convert(pages)
    assert plan is None and len(chapters) <= 2


def test_half_titles_mark_chapters_and_other_openings_are_sections():
    pages = _book({3: [("LE ROMAN EXPÉRIMENTAL", 15)], 6: [("LE SENS DU RÉEL", 10)], 8: [("LA DESCRIPTION", 10)],
                   11: [("DU ROMAN", 15)], 13: [("LES DOCUMENTS HUMAINS", 10)]},
                  half={2: "LE ROMAN EXPÉRIMENTAL", 10: "DU ROMAN"}, n=15)
    plan, chapters, blocks = _convert(pages, "Le roman expérimental")
    assert plan is not None and plan.chapters == 2
    assert [c.title for c in chapters][-2:] == ["LE ROMAN EXPÉRIMENTAL", "DU ROMAN"]
    sections = [t for c in chapters for _, t, _ in c.sections]
    assert sections == ["LE SENS DU RÉEL", "LA DESCRIPTION", "LES DOCUMENTS HUMAINS"]
    texts = [structure.plain(b.runs) for b in blocks]
    assert texts.count("LE ROMAN EXPÉRIMENTAL") == 1 and texts.count("DU ROMAN") == 1  # half-title copies dropped


def test_printed_table_of_contents_finds_an_opening_the_layout_missed():
    toc = [_centred("CONTENTS", 80, 12, 14)] + [
        _line(f"{t} {'.' * 20} {n}", 120 + 16 * i, 60, 340, pno=14)
        for i, (t, n) in enumerate([("The Roots", 1), ("The Green Branches", 5), ("The Last Voyage", 9)])]
    # chapter 3 starts at the normal top of its page (no sink): only the printed contents point to it
    missed = [_centred("THE LAST VOYAGE", 60, 10, 11)] + _body(11, 90)
    pages = _book({3: [("THE ROOTS", 10)], 7: [("THE GREEN BRANCHES", 10)]}, n=14, extra={11: missed, 14: toc})
    plan, chapters, _ = _convert(pages)
    assert plan is not None
    assert [c.title for c in chapters if c.title != "An Island Plant"][:3] == ["THE ROOTS", "THE GREEN BRANCHES",
                                                                           "THE LAST VOYAGE"]


def test_numbered_parts_in_mid_page_are_headings_not_chapters():
    pages = _book({3: [("FIRST ESSAY", 10)], 7: [("SECOND ESSAY", 10)], 11: [("THIRD ESSAY", 10)]})
    mid = _body(5, 60, 14) + [_centred("II", 270, 10, 5)] + _body(5, 300, 12, seed=3)
    pages[4] = _page(5, mid)
    plan, chapters, blocks = _convert(pages)
    assert plan.chapters == 3 and len(chapters) == 4
    heads = [b for b in blocks if isinstance(b, Heading)]
    part = next(h for h in heads if structure.plain(h.runs) == "II")
    assert part.level > 1


def test_similar_titles_tolerate_ocr_misreads():
    assert openings.similar("LETTRE A LA JEUN1.8SH", "LETTRE A LA JEUNESSE", 0.6)
    assert openings.similar("^E LA CRITIQUA", "DI^] LA CRITIQUE", 0.6)
    assert not openings.similar("DU ROMAN", "LE NATURALISME AU THÉÂTRE", 0.6)


def test_a_running_head_repeating_the_chapter_title_is_no_section():
    """An Island Plant: after a run of plates, the next text page carries the running head "‘THE RESULT OF DROUGHT
    AND WINTER." (stray OCR quote) set like an opening; it is not a second entry in the navigation."""
    pages = _book({3: [("I.", 10), ("THE ROOTS.", 10)], 7: [("II.", 10), ("THE GREEN BRANCHES.", 10)],
                   10: [("III.", 10), ("THE RESULT OF DROUGHT AND WINTER.", 10)],
                   13: [("‘THE RESULT OF DROUGHT AND WINTER.", 10)]}, n=15)
    plan, chapters, blocks = _convert(pages)
    assert plan is not None and plan.chapters == 3
    heads = [structure.plain(b.runs) for b in blocks if isinstance(b, Heading)]
    assert sum("DROUGHT" in h for h in heads) == 1


def test_a_running_head_set_as_a_heading_mid_chapter_is_dropped():
    """The same running head at the top of a text page, set larger than the body: an OCR heading, not a section."""
    head = _centred("‘THE RESULT OF DROUGHT AND WINTER.", 60, 13, 13)
    pages = _book({3: [("I.", 10), ("THE ROOTS.", 10)], 7: [("II.", 10), ("THE GREEN BRANCHES.", 10)],
                   10: [("III.", 10), ("THE RESULT OF DROUGHT AND WINTER.", 10)]}, n=15,
                  extra={13: [head] + _body(13, 100)})
    plan, chapters, blocks = _convert(pages)
    heads = [structure.plain(b.runs) for b in blocks if isinstance(b, Heading)]
    assert sum("DROUGHT" in h for h in heads) == 1
    assert not any("DROUGHT" in structure.plain(b.runs) for b in blocks if not isinstance(b, Heading) and hasattr(b, "runs"))
