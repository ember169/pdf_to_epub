"""Borderless (whitespace-aligned) table detection on already extracted lines."""
from __future__ import annotations

import re
import statistics

from .ir import Line, TableItem

_NUMERIC = re.compile(r"^[\divxlcIVXLC.\-–]+$")
_MARKER_CELL = re.compile(r"^(?:[•·▪▫◦●○■□‣⁃∙➢➤▶►\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])$")


def _split_cells(line: Line) -> list[tuple[float, float, str, bool, float]]:
    """Split one text line at big internal gaps -> [(x0, x1, text, bold)]."""
    size = max(line.size, 1.0)
    cells: list[list] = []
    for sp in line.spans:
        if not sp.text.strip() and cells:
            cells[-1][2] += sp.text
            continue
        x0, x1 = sp.bbox[0], sp.bbox[2]
        if cells and x0 - cells[-1][1] <= 1.5 * size:
            cells[-1][1] = max(cells[-1][1], x1)
            cells[-1][2] += sp.text
            cells[-1][3] = cells[-1][3] and sp.bold
        else:
            cells.append([x0, x1, sp.text, sp.bold])
    return [(c[0], c[1], c[2].strip(), c[3], size) for c in cells if c[2].strip()]


def detect_text_tables(lines: list[Line], pno: int, page_width: float) -> tuple[list[TableItem], list[Line]]:
    if len(lines) < 6:
        return [], lines
    # group lines into visual rows; running prose (e.g. the other column next to a table) is never a cell
    order = sorted((i for i in range(len(lines)) if not _is_prose(lines[i])), key=lambda i: (lines[i].y0 + lines[i].y1) / 2)
    rows: list[list[int]] = []
    for i in order:
        l = lines[i]
        if rows:
            ref = lines[rows[-1][0]]
            ov = min(ref.y1, l.y1) - max(ref.y0, l.y0)
            if ov >= 0.5 * min(ref.height, l.height):
                rows[-1].append(i)
                continue
        rows.append([i])

    info = []  # per row: cells or None
    for r in rows:
        cells: list = []
        for i in sorted(r, key=lambda i: lines[i].x0):
            cells += _split_cells(lines[i])
        cells.sort()
        ok = len(cells) >= 2 and all(len(c[2]) <= 60 for c in cells)
        info.append(cells if ok else None)

    tables: list[TableItem] = []
    consumed: set[int] = set()
    k = 0
    while k < len(rows):
        if info[k] is None:
            k += 1
            continue
        j = k
        while j + 1 < len(rows) and info[j + 1] is not None and _row_gap_ok(lines, rows, j, j + 1):
            j += 1
        run = list(range(k, j + 1))
        if len(run) >= 3:
            tbl = _build(run, info, rows, lines, pno)
            if tbl is not None:
                tables.append(tbl[0])
                consumed.update(tbl[1])
                k = j + 1
                continue
        k = j + 1
    if not tables:
        return [], lines
    return tables, [l for i, l in enumerate(lines) if i not in consumed]


def _is_prose(line: Line) -> bool:
    t = line.text.strip()
    return len(t) >= 35 and len(t.split()) >= 6 and len(_split_cells(line)) == 1


def _row_gap_ok(lines, rows, a, b) -> bool:
    la = lines[rows[a][0]]
    lb = lines[rows[b][0]]
    h = max(la.height, lb.height, 1.0)
    return (lb.y0 - la.y1) < 1.6 * h


def _build(run, info, rows, lines, pno):
    # column model: merge cell x-intervals across rows
    intervals = sorted((c[0], c[1]) for r in run for c in info[r])
    cols: list[list[float]] = []
    for x0, x1 in intervals:
        if cols and x0 <= cols[-1][1] + 0.5:
            cols[-1][1] = max(cols[-1][1], x1)
        else:
            cols.append([x0, x1])
    if len(cols) < 2 or len(cols) > 12:
        return None

    def col_of(c):
        mid = (c[0] + c[1]) / 2
        for ci, (a, b) in enumerate(cols):
            if a - 0.5 <= mid <= b + 0.5:
                return ci
        return None

    grid: list[list[str]] = []
    bold_first = False
    nonempty = 0
    total = 0
    for ri, r in enumerate(run):
        row = [""] * len(cols)
        for c in info[r]:
            ci = col_of(c)
            if ci is None:
                return None
            row[ci] = (row[ci] + " " + c[2]).strip()
        if ri == 0:
            bold_first = all(c[3] for c in info[r])
        nonempty += sum(1 for x in row if x)
        total += len(row)
        grid.append(row)
    if nonempty < 0.6 * total:
        return None
    first_col = [r[0] for r in grid if r[0]]
    if first_col and all(_MARKER_CELL.match(c) for c in first_col):
        return None  # bullets / numbers drawn apart from their text: a list, not a table
    cell_texts = [c for row in grid for c in row if c]
    avg_len = statistics.mean(len(c) for c in cell_texts)
    avg_words = statistics.mean(len(c.split()) for c in cell_texts)
    if avg_len > 28 or avg_words > 5:
        return None
    # text columns (narrow footnote or newspaper columns) read as sentences, tables as discrete values
    lower_start = sum(1 for c in cell_texts if c[0].islower()) / len(cell_texts)
    hyph_end = sum(1 for c in cell_texts if c.endswith(("-", ",", ";"))) / len(cell_texts)
    if lower_start > 0.25 or hyph_end > 0.2:
        return None
    sizes = [c[4] for r in run for c in info[r]]
    if max(sizes) - min(sizes) > 0.8:
        return None
    full = sum(1 for r in run if len(info[r]) == len(cols))
    if full < 0.7 * len(run):
        return None
    # a table of contents (title + page number) is better left as text
    if len(cols) == 2 and all(_NUMERIC.match(r[1] or "x") for r in grid) and statistics.mean(len(r[0]) for r in grid) > 15:
        return None
    consumed = {i for r in run for i in rows[r]}
    xs = [lines[i] for i in consumed]
    bbox = (min(l.x0 for l in xs), min(l.y0 for l in xs), max(l.x1 for l in xs), max(l.y1 for l in xs))
    return TableItem(bbox, grid, pno, bold_first), consumed
