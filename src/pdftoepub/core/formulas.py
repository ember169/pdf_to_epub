"""Mathematics in born-digital PDFs, the pragmatic way: what every EPUB reader can show.

A PDF stores a formula as glyphs placed in two dimensions: a fraction is a numerator line above the text line and a
denominator line below it, a display formula is a cloud of short fragments. Read as text lines, both came out as
separate one-word paragraphs ("dy", "dx", "= 5") that cut sentences in half. Per page (born-digital pages only):

1. Inline fractions: short math fragments just above and below a prose line, aligned with each other, are put back
   into that line as "a/b" (with parentheses around compound parts); a lone fragment above / below becomes a
   superscript / subscript. Fragments on the line itself (an operator between two fractions) are put back in order.
2. Display formulas: the remaining fragments are grouped into vertical clusters between prose lines. A cluster with
   math evidence (math fonts, operators, Greek, super/subscripts, stacked fragments) is a display formula:
   * one row (no stacking, no radical or big operator): kept as text, in a line of kind "dmath";
   * two-dimensional: rendered from the page as a grey-scale picture (`ImageItem` kind "formula"), with the
     linearised text as alt text and the equation number "(12)" kept as text.
   A connecting word printed beside a formula ("or", "and") is kept as text before it.

Structure (`structure.inline_display_math`) then places display formulas inside the paragraph that introduces them,
so the sentence around a formula stays one paragraph. No MathML: the reader support is too uneven to rely on.
"""
from __future__ import annotations

import io
import math
import re
import statistics
from dataclasses import dataclass

from .ir import ImageItem, Line, PageData, Span

STRONG = set("=+−×÷±∓<>≤≥≠≈≡∼≃≅∝∞∑∏∐∫∬∮√∂∇∆′″·⋅∘∗⊗⊕⊖⊙∈∉∋⊂⊃⊆⊇∪∩∧∨¬∀∃→←↔↦⇒⇐⇔⟨⟩⌊⌋⌈⌉‖")
BIG = set("∑∏∐∫∬∮√")
FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "exp", "lim", "max", "min", "det", "sup", "inf", "mod", "arg",
         "deg", "dim", "ker", "gcd", "lcm", "sinh", "cosh", "tanh", "arcsin", "arccos", "arctan", "tg", "ctg"}
EQNO_RE = re.compile(r"^\(\s*(\d{1,3}(\.\d{1,3})*[a-z]?|[ivxIVX]{1,5}|[A-Z]\.?\d{0,3}|\*{1,3})\s*\)$")
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
DPI = 200
MAX_HEIGHT_SHARE = 0.4  # a "formula" taller than this share of the page is a figure or a table
INK = 192  # grey level below which a rendered pixel is ink (crop trimming)


def _greek(c: str) -> bool:
    return "Α" <= c <= "ω" or c in "ϑϕϖϵϱς"


@dataclass
class _Piece:
    spans: list[Span]
    x0: float
    y0: float
    x1: float
    y1: float
    source: Span | None = None  # the span of a text line this piece was taken from

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def _box(spans: list[Span]) -> tuple[float, float, float, float]:
    vis = [s for s in spans if s.text.strip() and s.bbox != (0, 0, 0, 0)] or spans
    return (min(s.bbox[0] for s in vis), min(s.bbox[1] for s in vis), max(s.bbox[2] for s in vis),
            max(s.bbox[3] for s in vis))


_OPS = set("−+-×±∓·⋅÷=<>≤≥≈≠≡")


def _is_op(p: "_Piece | Span") -> bool:
    t = p.text.strip()
    return len(t) == 1 and t in _OPS


def _glyph_box(line: Line) -> tuple[float, float, float, float]:
    """The line's box without its math-font operators (their CMSY boxes may hang a row below the glyph)."""
    spans = [s for s in line.spans if s.text.strip() and s.bbox != (0, 0, 0, 0) and not (s.math and _is_op(s))]
    return _box(spans) if spans else line.bbox


def _pieces(line: Line) -> list[_Piece]:
    """The line cut at horizontal gaps wider than ~0.35 em (pdfminer joins a denominator, the operator after the
    fraction and the next denominator into one "line"). A lone operator is a piece of its own: its box (from the math
    font's metrics) does not tell which row it sits on."""
    spans = sorted((s for s in line.spans if s.bbox != (0, 0, 0, 0) or not s.text.strip()), key=lambda s: s.bbox[0])
    out: list[list[Span]] = []
    last_x1 = None
    prev_op = False
    for s in spans:
        if not s.text.strip():
            if out:
                out[-1].append(s)
            continue
        size = max(s.size, 1.0)
        op = _is_op(s)
        # a change of row inside one "line" (PyMuPDF groups a denominator with the next factor): a new piece
        prev = next((q for q in reversed(out[-1]) if q.text.strip()), None) if out else None
        shifted = (prev is not None and not (s.sup or s.sub or prev.sup or prev.sub)
                   and abs((s.bbox[1] + s.bbox[3]) / 2 - (prev.bbox[1] + prev.bbox[3]) / 2) > 0.3 * size)
        if out and last_x1 is not None and s.bbox[0] - last_x1 <= 0.35 * size and not op and not prev_op and not shifted:
            out[-1].append(s)
            last_x1 = max(last_x1, s.bbox[2])
        else:
            out.append([s])
            last_x1 = s.bbox[2]
        prev_op = op
    res = []
    for sp in out:
        while sp and not sp[-1].text.strip():
            sp.pop()
        if sp:
            res.append(_Piece(sp, *_box(sp)))
    return res


def _prose_words(spans: list[Span]) -> int:
    n = 0
    for s in spans:
        if s.math or s.mono:
            continue
        n += sum(1 for w in _WORD_RE.findall(s.text) if w.lower() not in FUNCS)
    return n


def _mathish(spans: list[Span]) -> tuple[int, int, int]:
    """(non-space chars, math-like chars, strong evidence chars)."""
    tot = ml = strong = 0
    for s in spans:
        single = s.italic and len(s.text.strip()) <= 2
        for c in s.text:
            if c.isspace():
                continue
            tot += 1
            st = c in STRONG or _greek(c) or s.math or s.sup or s.sub
            strong += st
            ml += st or c.isdigit() or single or c in "()[]{},.;:/'|!"
    return tot, ml, strong


def _is_prose(line: Line, colw: float, left: float | None = None) -> bool:
    """A text line (not a formula fragment). With `left`, a short line starting at the paragraph margin with a word
    in a text font ("(1) Differentiate y =", "(3) If ay + bx = ...") counts too: it carries inline math."""
    w = _prose_words(line.spans)
    if w >= 3 or (w >= 2 and line.x1 - line.x0 >= 0.4 * colw):
        return True
    tot, ml, _ = _mathish(line.spans)
    if w >= 1 and tot >= 25 and ml < 0.3 * tot:
        return True
    if left is not None and line.x0 <= left + 2.5 * max(line.size, 1.0):
        return any(re.search(r"[^\W\d_]{2,}", s.text) for s in line.spans if not (s.math or s.italic or s.mono))
    return False


_LEAD_RE = re.compile(r"[^\W\d_]{2,}(\s+[^\W\d_]{2,}){0,2}[,.;]?")
_REL = set("=<>≤≥≈≡≃≅∝⇒⇔→≠∼")


def _wrap(spans: list[Span]) -> list[Span]:
    """Parenthesise a compound numerator / denominator: "(a + b)"."""
    t = "".join(s.text for s in spans).strip()
    if len(t) > 1 and re.search(r"[\s+\-−×=,]", t) and not (t.startswith("(") and t.endswith(")")):
        size = spans[0].size
        return [Span("(", size, bbox=spans[0].bbox)] + spans + [Span(")", size, bbox=spans[-1].bbox)]
    return spans


def _copy(s: Span, **kw) -> Span:
    d = dict(text=s.text, size=s.size, bold=s.bold, italic=s.italic, sup=s.sup, sub=s.sub, mono=s.mono, bbox=s.bbox,
             link=s.link, math=s.math)
    d.update(kw)
    return Span(**d)


def _rebuild(line: Line, groups: list[tuple[float, list[Span]]]) -> Line:
    """`line` with groups of spans inserted at their x positions (spaces where the print has a gap)."""
    items = [(s.bbox[0] if s.bbox != (0, 0, 0, 0) else None, [s]) for s in line.spans]
    # spans without a box (spaces) keep their place: give them the previous position
    last = line.x0
    fixed = []
    for x, sp in items:
        if x is None:
            x = last
        last = x
        fixed.append((x, sp))
    fixed += groups
    fixed.sort(key=lambda g: g[0])
    out: list[Span] = []
    prev_x1 = None
    for x, sp in fixed:
        size = max(sp[0].size, 1.0)
        if out and prev_x1 is not None and x - prev_x1 > 0.15 * size and not out[-1].text.endswith(" ") \
                and not sp[0].text.startswith(" "):
            out.append(Span(" ", size))
        out += sp
        boxed = [s.bbox[2] for s in sp if s.bbox != (0, 0, 0, 0)]
        if boxed:
            prev_x1 = max(boxed)
    return Line(out, line.bbox, line.page, line.kind)


def _relation(p: _Piece, m: Line) -> float | None:
    """Vertical position of piece `p` relative to line `m`, in units of m's size: 0 = on the line, < 0 above."""
    size = max(m.size, 1.0)
    if not (m.x0 - 1.0 * size <= p.cx <= m.x1 + 3.0 * size):
        return None
    rel = (p.cy - (m.y0 + m.y1) / 2) / size
    return rel if abs(rel) <= 1.25 else None


def _pair(above: list[_Piece], below: list[_Piece]) -> list[tuple[_Piece, _Piece]]:
    pairs = []
    used = set()
    for a in above:
        best, dist = None, None
        for j, b in enumerate(below):
            if j in used:
                continue
            ov = min(a.x1, b.x1) - max(a.x0, b.x0)
            d = abs(a.cx - b.cx)
            if ov >= 0.3 * min(a.x1 - a.x0, b.x1 - b.x0) or d <= 0.5 * max(a.x1 - a.x0, b.x1 - b.x0):
                if dist is None or d < dist:
                    best, dist = j, d
        if best is not None:
            used.add(best)
            pairs.append((a, below[best]))
    return pairs


def _fraction(a: _Piece, b: _Piece) -> list[Span]:
    num = [_copy(s) for s in a.spans]
    den = [_copy(s) for s in b.spans]
    num[-1].text, den[-1].text = num[-1].text.rstrip(), den[-1].text.rstrip()
    size = max(a.spans[0].size, 1.0)
    end = max(a.x1, b.x1)
    # the trailing space keeps "n/z x" apart from a factor printed right after the fraction bar
    return _wrap(num) + [Span("/", size, bbox=(a.x1, a.y1, a.x1, a.y1))] + _wrap(den) + [Span(" ", size, bbox=(end, b.y0, end, b.y1))]


def join_split_rows(lines: list[Line]) -> list[Line]:
    """pdfminer cuts a text row where inline math interrupts it ("K L étant", [n over z], "x, I L est"; "(3) If ay +
    bx = by", [radical]): rejoin two pieces of one row when a numerator and a denominator stand in the gap between
    them, or when the right piece is math continuing the row right after a short gap."""
    lines = list(lines)
    small = [p for l in lines for p in _pieces(l) if len(p.text.strip()) <= 12 and not _prose_words(p.spans)]
    merged = True
    while merged:
        merged = False
        for a in lines:
            size = max(a.size, 1.0)
            cy = (a.y0 + a.y1) / 2
            for b in lines:
                if b is a:
                    continue
                ov = min(a.y1, b.y1) - max(a.y0, b.y0)
                gap = b.x0 - a.x1
                if ov < 0.5 * min(a.height, b.height):
                    continue
                # PyMuPDF: the row's first part ends with the numerator, the second starts with the denominator
                ea = next((x for x in reversed(a.spans) if x.text.strip()), None)
                sb = next((x for x in b.spans if x.text.strip()), None)
                if (ea is not None and sb is not None and ea.sup and sb.sub and -0.8 * size <= gap <= 0
                        and min(ea.bbox[2], sb.bbox[2]) - max(ea.bbox[0], sb.bbox[0]) > 0):
                    joined = Line(a.spans + b.spans, (a.x0, min(a.y0, b.y0), b.x1, max(a.y1, b.y1)), a.page, a.kind)
                    lines = [joined if l is a else l for l in lines if l is not b]
                    merged = True
                    break
                if not (0 < gap <= 3.0 * size):
                    continue
                inside = [p for p in small if a.x1 - 1 <= p.cx <= b.x0 + 1 and 0.35 * size < abs(p.cy - cy) <= 1.25 * size]
                frac = any(p.cy < cy for p in inside) and any(p.cy > cy for p in inside)
                op_between = any(_is_op(p) and a.x1 - 1 <= p.cx <= b.x0 + 1 and abs(p.cy - cy) <= 1.25 * size for p in small)

                def math_piece(l: Line) -> bool:
                    tot, ml, strong = _mathish(l.spans)
                    return strong > 0 and ml >= 0.6 * tot and not _prose_words(l.spans)

                # math continuing a text row, or opening it ("∼10⁷" + "times produces ..."); a row cut around an
                # operator its font metrics put a row lower ("which is y" [−] "dy, will be")
                cont = (gap <= 1.2 * size or (op_between and gap <= 2.0 * size)) and (math_piece(b) or math_piece(a))
                words = sorted((_prose_words(a.spans), _prose_words(b.spans)))
                cont = cont or (op_between and gap <= 2.0 * size and words[0] >= 1 and words[1] >= 3)
                if frac or cont:
                    space = [Span(" ", size)] if gap > 0.12 * size and not a.text.endswith(" ") else []
                    joined = Line(a.spans + space + b.spans, (a.x0, min(a.y0, b.y0), b.x1, max(a.y1, b.y1)), a.page, a.kind)
                    lines = [joined if l is a else l for l in lines if l is not b]
                    merged = True
                    break
            if merged:
                break
    return lines


def _aligned(a: _Piece, b: _Piece) -> bool:
    ov = min(a.x1, b.x1) - max(a.x0, b.x0)
    return ov >= 0.3 * min(a.x1 - a.x0, b.x1 - b.x0) or abs(a.cx - b.cx) <= 0.5 * max(a.x1 - a.x0, b.x1 - b.x0)


def absorb_fractions(lines: list[Line], colw: float, left: float) -> list[Line]:
    """Step 1: inline fractions and stray super/subscripts put back into their text line. A fraction is a numerator
    and a denominator aligned with each other, with a text line's middle between them."""
    prose = [l for l in lines if _is_prose(l, colw, left)]
    if not prose:
        return lines
    frags = [l for l in lines if not _is_prose(l, colw, left) and l.kind != "dmath"
             and not any(s.mono for s in l.spans) and not _prose_words(l.spans)]
    pieces = [p for f in frags for p in _pieces(f)]
    # a numerator / denominator the PDF library already put into the text line as a superscript / subscript
    inner: dict[int, Line] = {}  # id(piece) -> its text line
    for m in prose:
        for sp in m.spans:
            if (sp.sup or sp.sub) and sp.text.strip() and sp.bbox != (0, 0, 0, 0):
                p = _Piece([_copy(sp, sup=False, sub=False)], *sp.bbox)
                p.source = sp
                inner[id(p)] = m
                pieces.append(p)
    if not pieces:
        return lines

    def near(p: _Piece, m: Line) -> bool:
        size = max(m.size, 1.0)
        return m.x0 - 1.0 * size <= p.cx <= m.x1 + 4.0 * size

    # 1. fractions: pairs (numerator above, denominator below) around a text line's middle, best centred first
    options = []
    for a in pieces:
        if _is_op(a):
            continue
        for b in pieces:
            if b is a or _is_op(b) or not (a.cy < b.cy) or not _aligned(a, b):
                continue
            mid = (a.cy + b.cy) / 2
            if id(a) in inner and id(b) in inner and not (inner[id(a)] is inner[id(b)] and a.source.sup and b.source.sub):
                continue
            for m in prose:
                if inner.get(id(a), m) is not m or inner.get(id(b), m) is not m:
                    continue
                size = max(m.size, 1.0)
                mcy = (m.y0 + m.y1) / 2
                if a.cy < mcy < b.cy and 0.7 * size <= b.cy - a.cy <= 2.6 * size and abs(mcy - mid) <= 0.45 * size \
                        and near(a, m) and near(b, m):
                    options.append((abs(mcy - mid) / size + abs(a.cx - b.cx) / size, id(a), id(b), a, b, m))
    options.sort(key=lambda o: o[:3])
    taken: set[int] = set()
    per_host: dict[int, list] = {}
    for _, ia, ib, a, b, m in options:
        if ia in taken or ib in taken:
            continue
        taken.update((ia, ib))
        per_host.setdefault(id(m), []).append((a, b))
    # 2. the other pieces go to the nearest line (vertically; at the same height, the one they sit beside)
    rest: dict[int, list[tuple[float, _Piece]]] = {}
    for p in pieces:
        if id(p) in taken or id(p) in inner:
            continue
        best = None
        for m in prose:
            rel = _relation(p, m)
            if rel is None:
                continue
            hd = max(0.0, m.x0 - p.cx, p.cx - m.x1) / max(m.size, 1.0)
            key = (round(abs(rel) / 0.25), hd)
            if best is None or key < best[0]:
                best = (key, rel, m)
        if best is not None:
            rest.setdefault(id(best[2]), []).append((0.0 if _is_op(p) else best[1], p))
    used_spans: set[int] = set()
    rebuilt: dict[int, Line] = {}
    for m in prose:
        pairs = per_host.get(id(m), [])
        others = rest.get(id(m), [])
        groups: list[tuple[float, list[Span]]] = [(min(a.x0, b.x0), _fraction(a, b)) for a, b in pairs]
        done = [p for ab in pairs for p in ab]
        online = sorted((p for r, p in others if -0.35 <= r <= 0.35), key=lambda p: p.x0)
        if pairs:
            take = online
            for r, p in others:  # stray super / subscripts next to the fractions
                tot, ml, _ = _mathish(p.spans)
                if abs(r) > 0.35 and tot <= 6 and ml >= 0.8 * tot:
                    groups.append((p.x0, [_copy(s, sup=r < 0, sub=r > 0) for s in p.spans]))
                    done.append(p)
        else:  # no fraction: only the rest of the row itself (split off by the PDF) is put back
            take, end = [], m.x1
            for p in online:
                if p.x0 >= end - 1 and p.x0 - end <= 3 * max(m.size, 1.0):
                    take.append(p)
                    end = p.x1
            if not any(not _is_op(p) for p in take):
                take = []
            # operators displaced by their font metrics, standing in a gap of the row ("by − ax")
            take += [p for p in online if _is_op(p) and p not in take and m.x0 <= p.cx <= m.x1
                     and not any(min(sp.bbox[2], p.x1) > max(sp.bbox[0], p.x0) for sp in m.spans if sp.text.strip())]
        for p in take:
            groups.append((p.x0, [_copy(s) for s in p.spans]))
            done.append(p)
        if not groups:
            continue
        gone = {id(p.source) for p in done if id(p) in inner}
        host = Line([sp for sp in m.spans if id(sp) not in gone], m.bbox, m.page, m.kind) if gone else m
        rebuilt[id(m)] = _rebuild(host, groups)
        for p in done:
            used_spans.update(id(sp) for sp in p.spans)
    out = []
    for l in lines:
        if id(l) in rebuilt:
            out.append(rebuilt[id(l)])
            continue
        if any(id(sp) in used_spans for sp in l.spans):
            left_over = [sp for sp in l.spans if id(sp) not in used_spans]
            if any(sp.text.strip() for sp in left_over):  # what was not put back stays a fragment line
                out.append(Line(left_over, _box(left_over), l.page, l.kind))
            continue
        out.append(l)
    return out


def _rows(pieces: list[_Piece]) -> list[list[_Piece]]:
    rows: list[list[_Piece]] = []
    for p in sorted(pieces, key=lambda p: (_is_op(p), p.cy)):  # operators join the row of their neighbours
        h = p.y1 - p.y0
        # an operator's CMSY box may sit up to a row too low: try it where it is, then 3/4 of its height higher
        for dy in ((0.0, 0.75 * h) if _is_op(p) else (0.0,)):
            r = next((r for r in rows if min(r[0].y1, p.y1 - dy) - max(r[0].y0, p.y0 - dy)  # the row's first piece:
                      >= 0.5 * min(r[0].y1 - r[0].y0, h)), None)                         # rows must not grow together
            if r is not None:
                r.append(p)
                break
        else:
            rows.append([p])
    for r in rows:
        r.sort(key=lambda p: p.x0)
    rows.sort(key=lambda r: min(p.y0 for p in r))
    return rows


def _linear_spans(spans: list[Span]) -> str:
    out = []
    i = 0
    while i < len(spans):
        s = spans[i]
        if (s.sup or s.sub) and s.text.strip():
            j = i
            while j < len(spans) and spans[j].sup == s.sup and spans[j].sub == s.sub and (spans[j].sup or spans[j].sub):
                j += 1
            t = "".join(x.text for x in spans[i:j]).strip()
            out.append(("^" if s.sup else "_") + (t if len(t) == 1 else f"({t})"))
            i = j
            continue
        out.append(s.text)
        i += 1
    return "".join(out)


def _equations(body: list[_Piece]) -> list[list[_Piece]]:
    """Split a cluster holding several displayed equations (one above the other) into one piece list each: rows with
    a relation sign are the equation rows; other pieces (numerators, denominators) go to the nearest of them."""
    rows = _rows(body)
    mains = [r for r in rows if any(c in _REL for p in r for c in p.text)]
    if len(mains) < 2:
        return [body]
    cys = [statistics.mean(p.cy for p in r) for r in mains]
    out: list[list[_Piece]] = [list(r) for r in mains]
    rest = [p for r in rows if not any(r is m for m in mains) for p in r]
    for p in sorted(rest, key=_is_op):  # operators last, beside the pieces already placed
        k = min(range(len(cys)), key=lambda i: abs(p.cy - cys[i]))
        if _is_op(p):  # an operator in a gap of an equation's row ("1 × 2"; CMSY boxes sit up to a row too low)
            h = p.y1 - p.y0
            for i, e in enumerate(out):
                row = [q for q in e if not _is_op(q) and any(min(q.y1, y1) - max(q.y0, y0) > 0.3 * h
                                                             for y0, y1 in ((p.y0, p.y1), (p.y0 - 0.75 * h, p.y1 - 0.75 * h)))]
                if any(q.x1 <= p.cx for q in row) and any(q.x0 >= p.cx for q in row) \
                        and not any(q.x0 < p.cx < q.x1 for q in row):
                    k = i
                    break
        out[k].append(p)
    return out


def linearise(pieces: list[_Piece]) -> str:
    """Readable one-line text of a 2-D formula (alt text): the main row is the one with the relation sign; pieces
    stacked above and below it become fractions."""
    rows = _rows(pieces)
    if not rows:
        return ""
    rel = [p for p in pieces if p.text.strip() and p.text.strip()[0] in _REL]
    if rel:
        mcy = statistics.median(p.cy for p in rel)
    else:
        main = max(rows, key=lambda r: sum(len(p.text) for p in r))
        mcy = statistics.median(p.cy for p in main)
    size = statistics.median(max(s.size for s in p.spans) for p in pieces) or 10.0
    main = [p for p in pieces if abs(p.cy - mcy) <= 0.3 * size or (_is_op(p) and abs(p.cy - mcy) <= 1.25 * size)]
    others = [p for p in pieces if not any(p is q for q in main)]
    for op in [p for p in others if _is_op(p)]:  # "1 × 2" in a denominator: one piece (its box may sit a row low)
        h = op.y1 - op.y0
        row = [q for q in others if not _is_op(q) and any(min(q.y1, op.y1 - dy) - max(q.y0, op.y0 - dy) > 0.3 * h
                                                          for dy in (0.0, 0.75 * h))]
        lft = [q for q in row if q.x1 <= op.cx and op.x0 - q.x1 <= 1.5 * size]
        rgt = [q for q in row if q.x0 >= op.cx and q.x0 - op.x1 <= 1.5 * size]
        if lft and rgt:
            a, b = max(lft, key=lambda q: q.x1), min(rgt, key=lambda q: q.x0)
            merged = _Piece(a.spans + [Span(" ", size)] + op.spans + [Span(" ", size)] + b.spans,
                            a.x0, min(a.y0, b.y0), b.x1, max(a.y1, b.y1))
            others = [merged if q is a else q for q in others if q is not op and q is not b]
    spans = [s for p in sorted(main, key=lambda p: p.x0) for s in p.spans]
    m = Line(spans, (min(p.x0 for p in main), min(p.y0 for p in main), max(p.x1 for p in main), max(p.y1 for p in main))) \
        if main else Line([], (0, mcy, 0, mcy))
    above = [p for p in others if p.cy < mcy]
    below = [p for p in others if p.cy >= mcy]
    pairs = _pair(sorted(above, key=lambda p: p.x0), sorted(below, key=lambda p: p.x0))
    groups = [(min(a.x0, b.x0), _fraction(a, b)) for a, b in pairs]
    used = {id(x) for a, b in pairs for x in (a, b)}
    for p in others:
        if id(p) not in used:
            groups.append((p.x0, [_copy(s) for s in p.spans]))
    if not main:
        m = Line([], (min(g[0] for g in groups), mcy, min(g[0] for g in groups), mcy))
    text = _linear_spans(_rebuild(m, groups).spans)
    return re.sub(r"\s+", " ", text).strip()


def _column(lines: list[Line], page: PageData) -> tuple[float, float, float, float]:
    """(left, right, body size, column width) from the page's prose lines."""
    long_ = [l for l in lines if len(l.text.strip()) >= 30 and _prose_words(l.spans) >= 3]
    if not long_:
        return 0.0, page.width, 10.0, page.width
    left = min(l.x0 for l in long_)
    right = max(l.x1 for l in long_)
    size = statistics.median(l.size for l in long_)
    widths = sorted(l.x1 - l.x0 for l in long_)
    return left, right, size, widths[len(widths) // 2]


def _has_math(page: PageData) -> bool:
    for l in page.lines:
        for s in l.spans:
            if s.math or (not s.mono and any(c in STRONG and c not in "+-<>|" or _greek(c) for c in s.text)):
                return True
    return False


def process_page(page: PageData, render, store) -> int:
    """Steps 1 and 2 on one page. `render(rect, dpi)` returns an ImageAsset (or None). Returns formulas rendered."""
    if page.source != "native" or page.ocr_layer or not page.lines or not _has_math(page):
        return 0
    left, right, size, colw = _column(page.lines, page)
    for l in page.lines:  # a full-size glyph is not a superscript, whatever the PDF library flagged
        if not _is_prose(l, colw, left):
            for sp in l.spans:
                if (sp.sup or sp.sub) and sp.size >= 0.9 * size:
                    sp.sup = sp.sub = False
    lines = absorb_fractions(join_split_rows(page.lines), colw, left)
    prose = [l for l in lines if _is_prose(l, colw, left)]
    frags = sorted((l for l in lines if not _is_prose(l, colw, left) and not any(s.mono for s in l.spans)
                    and l.kind != "dmath"), key=lambda l: l.y0)
    # clusters of fragments: linked when vertically close and within 8 em sideways (side notes in the margin form
    # clusters of their own), never across a text line
    numbers = [f for f in frags if EQNO_RE.match(f.text.strip())]
    frags = [f for f in frags if not any(f is n for n in numbers)]
    parent = list(range(len(frags)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, f in enumerate(frags):
        for j in range(i + 1, len(frags)):
            g = frags[j]
            if g.y0 > f.y1 + 0.7 * size:
                break  # sorted by y0: the next ones are lower still
            if max(f.x0, g.x0) - min(f.x1, g.x1) > 8 * size or root(i) == root(j):
                continue
            lo, hi = min(f.y1, g.y1), max(f.y0, g.y0)
            if hi > lo and any(lo - 1 <= (p.y0 + p.y1) / 2 <= hi + 1 and min(p.x1, max(f.x1, g.x1)) > max(p.x0, min(f.x0, g.x0))
                               for p in prose):
                continue
            parent[root(j)] = root(i)
    groups: dict[int, list[Line]] = {}
    for i, f in enumerate(frags):
        groups.setdefault(root(i), []).append(f)
    clusters = sorted(groups.values(), key=lambda c: min(l.y0 for l in c))
    for n in numbers:  # an equation number at the right margin joins the formula on its row
        row = [c for c in clusters if min(n.y1, max(l.y1 for l in c)) - max(n.y0, min(l.y0 for l in c)) > 0.5 * n.height
               and n.x0 > max(l.x1 for l in c)]
        if row:
            min(row, key=lambda c: n.x0 - max(l.x1 for l in c)).append(n)
    out = list(lines)
    rendered = 0
    for c in clusters:
        x0, y0, x1, y1 = min(l.x0 for l in c), min(l.y0 for l in c), max(l.x1 for l in c), max(l.y1 for l in c)
        if any(min(y1, p.y1) - max(y0, p.y0) > 0.5 * (p.y1 - p.y0) and max(p.x0 - x1, x0 - p.x1) < 1.0 * size for p in prose):
            continue  # interleaved with text lines, or a text line continues its row ("• ∫ f(x) dx: integral"): inline
        # a column of values beside row labels is a table ("Primary black hole mass | 36 +5 −4 M⊙"), not an equation
        others = [l for l in lines if not any(l is m for m in c) and _prose_words(l.spans) >= 2]
        labelled = sum(1 for l in c if any(o.x1 <= l.x0 + 1 and min(o.y1, l.y1) - max(o.y0, l.y0) >= 0.5 * min(o.height, l.height)
                                           and len(o.text.strip()) >= 3 for o in others))
        if labelled >= 2:
            continue
        relation = any(ch in _REL for l in c for ch in l.text)
        if not relation and any(min(y1, im.bbox[3]) > max(y0, im.bbox[1]) and min(im.bbox[2], x1) > max(im.bbox[0], x0)
                                for im in page.images):
            continue  # labels on a figure (an equation, with its "=", is not a label)
        pieces = [p for l in c for p in _pieces(l)]
        eqs = _equations(pieces) if pieces else []
        results = []
        for k, eq in enumerate(eqs):  # a crop must not take a sliver of the next equation or of a text line
            avoid = [_glyph_box(l) for l in out if not any(l is m for m in c)] + [(p.x0, p.y0, p.x1, p.y1) for j, e in
                                                                                 enumerate(eqs) if j != k for p in e
                                                                                 if not _is_op(p)]
            results.append(_formula(eq, page, left, size, render, store, avoid))
        if not results or any(r is None for r in results):
            continue  # all equations of the cluster convert, or the lines stay as they are
        gone = {id(l) for l in c}
        out = [l for l in out if id(l) not in gone]
        for r in results:
            if isinstance(r, Line):
                out.append(r)
            else:
                page.images.append(r)
                rendered += 1
    page.lines = out
    return rendered


def _formula(pieces: list[_Piece], page: PageData, left: float, size: float, render, store,
             avoid: list[tuple] = ()) -> Line | ImageItem | None:
    """One displayed equation: a "dmath" text line (one row), a rendered picture (two-dimensional), or None when the
    pieces are not a formula."""
    # equation number at the right, connecting word at the left
    label = ""
    body = sorted(pieces, key=lambda p: p.x0)
    eq = [p for p in body if EQNO_RE.match(p.text.strip())]
    if eq:
        e = max(eq, key=lambda p: p.x1)
        rest = [p for p in body if p is not e]
        if rest and e.x0 - max(p.x1 for p in rest) >= 1.0 * size:
            label = e.text.strip()
            body = rest
    lead = ""
    words = [p for p in body if _LEAD_RE.fullmatch(p.text.strip()) and not any(s.math or s.italic for s in p.spans)]
    if words:
        w = min(words, key=lambda p: p.x0)
        rest = [p for p in body if p is not w]
        if rest and w.x0 <= left + 2.5 * size and min(p.x0 for p in rest) - w.x1 >= 2.0 * size:
            lead = w.text.strip()
            body = rest
    tot = ml = strong = 0
    for p in body:
        a, b, s_ = _mathish(p.spans)
        tot, ml, strong = tot + a, ml + b, strong + s_
    rows = _rows(body)
    stacked = any(min(p.x1, q.x1) > max(p.x0, q.x0) for i, r in enumerate(rows) for r2 in rows[i + 1:] for p in r for q in r2)
    if not tot or ml < 0.6 * tot or (strong == 0 and not stacked) or _prose_words([s for p in body for s in p.spans]) > 4:
        return None
    if len(body) == 1 and len(body[0].text.strip()) <= 2 and not label:
        return None  # a lone symbol: a stray glyph, a list mark, a page number
    if not any(s.math for p in body for s in p.spans) and not any(c in _REL for p in body for c in p.text):
        return None  # no math font and no relation: table cells ("65B  68.2  50.0  56.6"), not a formula
    tall = any(p.y1 - p.y0 > 1.6 * size for p in body)
    big = any(c in BIG for p in body for c in p.text)
    bx0, by0 = min(p.x0 for p in body), min(p.y0 for p in body)
    bx1, by1 = max(p.x1 for p in body), max(p.y1 for p in body)
    if not (stacked or tall or big):
        line = _rebuild(Line([], (bx0, by0, bx1, by1), page.number), [(p.x0, [_copy(s) for s in p.spans]) for p in body])
        line.spans = ([Span(lead + " ", size)] if lead else []) + line.spans + ([Span("  " + label, size)] if label else [])
        line.kind = "dmath"
        return line
    if by1 - by0 > MAX_HEIGHT_SHARE * page.height:
        return None
    # the crop may reach halfway to the neighbouring lines (never into their boxes), at most 1 em past the glyph boxes
    lim = [max(0.0, bx0 - size), max(0.0, by0 - size), min(page.width, bx1 + size), min(page.height, by1 + size)]
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    for x0, y0, x1, y1 in list(avoid) + [(p.x0, p.y0, p.x1, p.y1) for p in pieces if p not in body]:
        if min(y1, by1) - max(y0, by0) > 0.5 * (y1 - y0):  # beside the formula, on its rows (equation number, note)
            if (x0 + x1) / 2 < cx:
                lim[0] = max(lim[0], min((x1 + bx0) / 2 if x1 < bx0 else x1, cx))
            else:
                lim[2] = min(lim[2], max((x0 + bx1) / 2 if x0 > bx1 else x0, cx))
        elif min(x1, lim[2]) > max(x0, lim[0]):
            if (y0 + y1) / 2 < cy:
                lim[1] = max(lim[1], min((y1 + by0) / 2 if y1 < by0 else y1, cy))
            else:
                lim[3] = min(lim[3], max((y0 + by1) / 2 if y0 > by1 else y0, cy))
    try:
        asset = render(tuple(lim), DPI)
        if asset is not None:
            asset, rect = _trim(asset, lim, (bx0, by0, bx1, by1), 0.25 * size)
    except Exception:  # noqa: BLE001 - keep the text when the region cannot be rendered
        asset = None
    if asset is None:
        return None
    iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
    return ImageItem(rect, iid, page.number, "formula", alt=(linearise(body) or "formula")[:500], label=label, lead=lead,
                     width_em=round((rect[2] - rect[0]) / max(size, 1.0), 2))


def _trim(asset, lim, ink, pad: float):
    """Crop the rendering of the allowed region `lim` to the formula: start from its glyph boxes `ink`, grow while a
    border row / column still has ink (large delimiters and radicals reach past the boxes their font metrics give),
    then add `pad` of white, all within `lim`. Returns (asset, rectangle in page coordinates)."""
    from PIL import Image

    from .backends.common import asset_from_pil

    img = Image.open(io.BytesIO(asset.data)).convert("L")
    sx, sy = img.width / max(lim[2] - lim[0], 1e-6), img.height / max(lim[3] - lim[1], 1e-6)
    mask = img.point(lambda v: 255 if v < INK else 0)
    W, H = img.size
    box = [max(0, math.floor((ink[0] - lim[0]) * sx)), max(0, math.floor((ink[1] - lim[1]) * sy)),
           min(W, math.ceil((ink[2] - lim[0]) * sx)), min(H, math.ceil((ink[3] - lim[1]) * sy))]
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return None, None
    def grow():
        grown = True
        while grown:
            grown = False
            if box[0] > 0 and mask.crop((box[0], box[1], box[0] + 1, box[3])).getbbox():
                box[0] -= 1
                grown = True
            if box[1] > 0 and mask.crop((box[0], box[1], box[2], box[1] + 1)).getbbox():
                box[1] -= 1
                grown = True
            if box[2] < W and mask.crop((box[2] - 1, box[1], box[2], box[3])).getbbox():
                box[2] += 1
                grown = True
            if box[3] < H and mask.crop((box[0], box[3] - 1, box[2], box[3])).getbbox():
                box[3] += 1
                grown = True

    px, py = round(pad * sx), round(pad * sy)
    for _ in range(2):  # the padding may reach ink with no text behind it (CMEX parentheses): take it in too
        grow()
        box[:] = [max(0, box[0] - px), max(0, box[1] - py), min(W, box[2] + px), min(H, box[3] + py)]
    grow()
    rect = (lim[0] + box[0] / sx, lim[1] + box[1] / sy, lim[0] + box[2] / sx, lim[1] + box[3] / sy)
    return asset_from_pil(img.crop(tuple(box))), rect
