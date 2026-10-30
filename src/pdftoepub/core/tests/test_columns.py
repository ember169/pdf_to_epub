"""Two-column reading order around full-width elements and tables inside a column (the LLaMA page 4 case: a borderless
table in the right column whose rows line up with the left column's lines)."""
import re

from pdftoepub.core import layout
from pdftoepub.core.ir import Line, PageData, Span

LEFT = ("Zero-shot. We provide a textual description of the task and a test example. The model either provides an "
        "answer using open-ended generation or ranks the proposed answers. Few-shot. We provide a few examples of the "
        "task between one and sixty-four and a test example. The model takes this text as input and generates the "
        "answer or ranks different options. We compare our model with other foundation models, namely the closed "
        "language models of the last years, and with the open models that were released before it in this report.")
RIGHT = ("We evaluate the models on free-form generation tasks and multiple choice tasks. In the multiple choice tasks "
         "the objective is to select the most appropriate completion among a set of given options, based on a "
         "provided context. We select the completion with the highest likelihood given the provided context.")
AFTER = ("Common sense reasoning. We consider eight standard common sense reasoning benchmarks that include Cloze and "
         "Winograd style tasks, as well as multiple choice question answering, in the zero-shot setting.")


def _wrap(text, width=48):
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + [cur]


def _l(text, x0, y, x1=None, size=9.0):
    x1 = x1 if x1 is not None else x0 + 4.6 * len(text)
    return Line([Span(text, size, bbox=(x0, y, x1, y + 10))], (x0, y, x1, y + 10), 1)


def _page():
    lines = []
    y = 60
    for row in ["Model BoolQ PIQA SIQA HellaSwag WinoGrande ARC-e ARC-c OBQA", "GPT-3 175B 60.5 81.0 - 78.9 70.2 68.8 51.4 57.6",
                "Gopher 280B 79.3 81.8 50.6 79.2 70.1 - - -", "Chinchilla 70B 83.7 81.8 51.3 80.8 74.9 - - -"]:
        lines.append(_l(row, 60, y, 552))
        y += 12
    lines.append(_l("Table 3: Zero-shot performance on Common Sense Reasoning tasks.", 150, y + 8, 462))
    top = y + 40
    right = _wrap(RIGHT)
    for i, t in enumerate(right):
        lines.append(_l(t, 322, top + 12 * i, 562))
    ty = top + 12 * len(right) + 12  # a borderless table: one Line per cell, rows 16 pt apart
    left = _wrap(LEFT)
    # the left column's lines (list items set with extra space) share the table's blank rows: every row of the
    # table region is also a horizontal gap across the whole page
    ys = [top + 12 * i for i in range((ty - top) // 12)]
    ys += [ty + 16 * r for r in range(len(left) - len(ys))]
    for t, yy in zip(left, ys):
        lines.append(_l(t, 50, yy, 290))
    for r, cells in enumerate([["0-shot", "1-shot", "5-shot", "64-shot"], ["GPT-3", "175B", "14.6", "23.0", "29.9"],
                               ["Gopher", "280B", "10.1", "24.5", "28.2"], ["Chinchilla", "70B", "16.6", "31.5", "35.5"],
                               ["PaLM", "540B", "21.2", "29.3", "39.6"]]):
        xs = [400, 440, 480, 520] if r == 0 else [322, 380, 430, 480, 530]
        for x, c in zip(xs, cells):
            lines.append(_l(c, x, ty + 16 * r, x + 5 * len(c)))
    ay = max(ty + 16 * 5, ys[-1] + 16) + 12
    for i, t in enumerate(_wrap(AFTER)):
        lines.append(_l(t, 322, ay + 12 * i, 562))
    return PageData(1, 612, 792, lines=lines)


def test_table_inside_a_column_does_not_glue_the_columns():
    page = _page()
    ctx = layout.compute_ctx([page], True)
    blocks, _ = layout.page_blocks(page, ctx)
    texts = [b.text for b in blocks if b.kind == "text"]
    assert not any("Zero-shot" in t and ("GPT-3" in t or "14.6" in t) for t in texts)
    # main glued "... the closed language models of the last years, GPT-3 175B 14.6 23.0 29.9 and with the open ..."
    assert not any(re.search(r"\d\d\.\d", t) for t in texts if "language models" in t or "Few-shot" in t)
    assert any("released before it in this report" in t for t in texts)
    left = next(i for i, t in enumerate(texts) if "Zero-shot. We provide" in t)
    left_end = next(i for i, t in enumerate(texts) if "released before it in this report" in t)
    right = next(i for i, t in enumerate(texts) if "We evaluate the models" in t)
    after = next(i for i, t in enumerate(texts) if "Common sense reasoning" in t)
    assert left <= left_end < right < after  # the left column is read before the right one
    assert "".join(texts).count("Zero-shot") == 2  # once in the left column, once in the full-width caption


def test_single_column_page_keeps_its_line_order():
    lines = [_l(t, 72, 80 + 13 * i, 540) for i, t in enumerate(_wrap(LEFT + " " + RIGHT, 90))]
    page = PageData(1, 612, 792, lines=lines)
    ctx = layout.compute_ctx([page], True)
    blocks, _ = layout.page_blocks(page, ctx)
    assert " ".join(b.text for b in blocks) == " ".join(l.text for l in lines)
