"""Endnotes: the numbered notes a chapter prints under a "Notes" heading at its end (often in two columns of small
type), linked to the superscript numbers of that chapter's text.

`extract` works on the layout blocks, before they become paragraphs: the region runs from the "Notes" heading to the
next heading ("Bibliographie", the next chapter). Its lines, including those the page-footnote detector took from the
page bottoms, are put back in reading order (page, column, height) and cut into notes where a line starts with the
next number. The region becomes one `endnotes` block.

`link` works on the converted blocks: a superscript number in the text between the previous endnotes block and this
one points to the note with that number (the first time it occurs), and the note links back.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .ir import Footnote, Heading, Line, ListBlock, Paragraph, Span, Table
from .layout import RawBlock, RawNote

NOTES_RE = re.compile(r"(?i)^\s*(notes?|notes et r[ée]f[ée]rences|endnotes|notes and references)\s*:?\s*$")
END_RE = re.compile(r"(?i)^\s*(bibliograph(ie|y)|r[ée]f[ée]rences( bibliographiques)?|works cited|sources|annexes?|"
                    r"appendix|index|glossaire|glossary)\s*:?\s*$")
NUM_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]?\s*(?=\S)")
TERMINAL = tuple(".!?»”)]>")


@dataclass
class Note:
    number: int
    lines: list[Line] = field(default_factory=list)
    page: int = 0


def _region_end(raw: list[RawBlock], i: int, size: float) -> int:
    page0 = raw[i].page
    for k in range(i + 1, len(raw)):
        b = raw[k]
        if b.page > page0 + 60:
            return k
        if b.kind == "table" and _note_table(b):  # two columns of notes the table detector took
            continue
        if b.kind != "text":  # a picture, a table, a formula: the notes are over
            return k
        t = b.text.strip()
        if END_RE.match(t) or NOTES_RE.match(t):
            return k
        if b.size >= 1.25 * size:  # body text or the next chapter's title: notes are set in their own (smaller) type
            return k
    return len(raw)


def extract(raw: list[RawBlock], notes: dict[int, list[RawNote]], page_width: dict[int, float]):
    """Returns the new block list; consumed page notes are removed from `notes` in place."""
    out: list[RawBlock] = []
    i = 0
    region_no = 0
    while i < len(raw):
        b = raw[i]
        if not (b.kind == "text" and len(b.lines) <= 2 and NOTES_RE.match(b.text)):
            out.append(b)
            i += 1
            continue
        body = [x.size for x in raw[i + 1:i + 4] if x.kind == "text" and x.page == b.page]  # the notes' own type
        body = body or [l.size for p in (b.page, b.page + 1) for rn in notes.get(p, []) for l in rn.lines[:1]]
        size = statistics.median(body) if body else b.size
        if b.size < 1.05 * size and not b.centred:  # "Notes" as a word in running text, not a heading
            out.append(b)
            i += 1
            continue
        k = _region_end(raw, i, size)
        last_page = raw[k].page if k < len(raw) else raw[-1].page
        end_y = raw[k].y0 if k < len(raw) else 1e9
        stream = []  # (page, column, y, number or None, line)
        for x in raw[i + 1:k]:
            if x.kind == "text":
                stream += [(l, None) for l in x.lines]
            elif x.kind == "table":
                stream += [(l, None) for l in _table_lines(x)]
        taken = []
        for pno in range(b.page, last_page + 1):
            for rn in notes.get(pno, []):
                if pno == b.page and rn.lines and rn.lines[0].y0 < b.y0:
                    continue
                if pno == last_page and rn.lines and rn.lines[0].y0 >= end_y:
                    continue
                taken.append(rn)
                num = int(rn.marker) if rn.marker.isdigit() else None
                stream += [(_strip_number(l, punct_only=True) if j == 0 else l, num if j == 0 else None)
                           for j, l in enumerate(rn.lines)]
        parsed = _split(stream, page_width)
        chars = [sum(len(l.text) for l in n.lines) for n in parsed]
        if len(parsed) < 3 or parsed[0].number > 2 or max(chars, default=0) > 3000:
            out.append(b)
            i += 1
            continue
        region_no += 1
        for rn in taken:
            notes[rn.page] = [x for x in notes.get(rn.page, []) if x is not rn]
        out.append(b)
        out.append(RawBlock("endnotes", b.page, b.y0 + 0.1, [], item=(region_no, parsed)))
        i = k
    return out


def _note_table(b: RawBlock) -> bool:
    rows = getattr(b.item, "rows", None) or []
    firsts = [next((c for c in r if c.strip()), "") for r in rows]
    return bool(rows) and sum(1 for c in firsts if NUM_RE.match(c) and re.match(r"\s*\d{1,3}\s*[.)]", c)) >= 0.5 * len(rows)


def _table_lines(b: RawBlock) -> list[Line]:
    """Lines back from a table block: cells left to right become columns, rows top to bottom."""
    x0, y0, x1, y1 = b.item.bbox
    rows = b.item.rows
    ncol = max((len(r) for r in rows), default=1)
    h = (y1 - y0) / max(1, len(rows))
    out = []
    for i, r in enumerate(rows):
        for j, cell in enumerate(r):
            if cell.strip():
                cx = x0 + (x1 - x0) * j / ncol
                box = (cx, y0 + i * h, cx + (x1 - x0) / ncol - 2, y0 + (i + 1) * h)
                out.append(Line([Span(cell, b.size or 6.5, bbox=box)], box, b.page))
    return out


def _split(stream, page_width: dict[int, float]) -> list[Note]:
    by_page: dict[int, list] = {}
    for l, num in stream:
        by_page.setdefault(l.page, []).append((l, num))
    ordered = []
    for pno in sorted(by_page):
        w = page_width.get(pno, 600.0)
        items = _unmerge_columns(by_page[pno], w)
        left = sum(1 for l, _ in items if l.x1 < 0.55 * w)
        right = sum(1 for l, _ in items if l.x0 > 0.45 * w)
        two = left >= 2 and right >= 2
        ordered += sorted(items, key=lambda it: ((1 if two and it[0].x0 > 0.45 * w else 0), it[0].y0, it[0].x0))
    out: list[Note] = []
    for l, num in ordered:
        text = l.text.strip()
        if not text and num is None:
            continue
        expected = out[-1].number + 1 if out else 1
        n = num
        if n is None:
            m = NUM_RE.match(text)
            n = int(m.group(1)) if m else None
        # a jump: notes the text layer lacks (OCR missed lines); only for a clear "N. Text" after a finished note
        jump = (n is not None and expected < n <= expected + 8 and (not out or _ends(out[-1]))
                and re.match(r"^\s*\d{1,3}\s*[.)]\s+\S", text) is not None)
        ok = n is not None and (n == expected or jump or (n == expected + 1 and (not out or _ends(out[-1]))))
        if ok:
            if num is None:  # the number is printed on the line: not part of the note's text
                l = _strip_number(l)
            out.append(Note(n, [l] if l.text.strip() else [], l.page))
        elif out:
            out[-1].lines.append(l)
    return out


def _unmerge_columns(items, w: float):
    """OCR-layer rows glued across the column gap ("34. Author, 1977. 41. Cf. Other, 2006."): cut them at the
    gutter, found where spans starting with a note number begin in the right half."""
    starts = sorted(sp.bbox[0] for l, _ in items for sp in l.spans
                    if sp.bbox[0] > 0.4 * w and NUM_RE.match(sp.text) and re.match(r"\s*\d{1,3}\s*[.)]", sp.text))
    if len(starts) < 2:
        return items
    gutter = starts[len(starts) // 2] - 2
    out = []
    for l, num in items:
        left = [sp for sp in l.spans if sp.bbox == (0, 0, 0, 0) or sp.bbox[0] < gutter]
        right = [sp for sp in l.spans if sp.bbox != (0, 0, 0, 0) and sp.bbox[0] >= gutter]
        if left and right and any(sp.text.strip() for sp in left) and any(sp.text.strip() for sp in right):
            for part in (left, right):
                vis = [sp for sp in part if sp.bbox != (0, 0, 0, 0)]
                box = (min(sp.bbox[0] for sp in vis), l.y0, max(sp.bbox[2] for sp in vis), l.y1)
                out.append((Line(part, box, l.page, l.kind), num if part is left else None))
        else:
            out.append((l, num))
    return out


def _ends(note: Note) -> bool:
    return bool(note.lines) and note.lines[-1].text.rstrip().endswith(TERMINAL)


def _strip_number(l: Line, punct_only: bool = False) -> Line:
    """The note number printed at the start of the line, or only the "." / ")" left after it (`punct_only`)."""
    spans = list(l.spans)
    for k, s in enumerate(spans):
        if s.text.strip():
            m = re.match(r"^\s*[.)]\s*", s.text) if punct_only else NUM_RE.match(s.text)
            if m:
                rest = s.text[m.end():]
                spans[k] = Span(rest, s.size, s.bold, s.italic, False, False, s.mono, s.bbox, s.link, s.math)
            break
    return Line([s for s in spans if s.text], l.bbox, l.page, l.kind)


def footnotes_of(item, runs_from_lines, ctx) -> list[Footnote]:
    region_no, parsed = item
    fns = []
    for n in parsed:
        runs = runs_from_lines(n.lines, ctx)
        fns.append(Footnote(f"en{region_no}-{n.number}", runs, str(n.number), n.page, orphan=True))
    return fns


def link(blocks) -> int:
    """Link superscript numbers to the endnotes that follow them. Returns the number of links made."""
    from .ir import Endnotes
    pending = []  # runs with a superscript number since the previous endnotes block
    made = 0
    for b in blocks:
        if isinstance(b, Endnotes):
            by_num = {fn.marker: fn for fn in b.notes}
            for r in pending:
                fn = by_num.get(r.text.strip())
                if fn is not None and fn.orphan:
                    r.noteref = fn.id
                    fn.orphan = False
                    made += 1
            pending = []
            continue
        runs = []
        if isinstance(b, (Paragraph, Heading)):
            runs = b.runs
        elif isinstance(b, ListBlock):
            runs = [r for it in b.items for r in it]
        elif isinstance(b, Table):
            runs = [r for row in b.rows for c in row for r in c]
        for r in runs:
            if r.sup and not r.noteref and re.fullmatch(r"\s*\d{1,3}\s*", r.text or ""):
                pending.append(r)
    return made
