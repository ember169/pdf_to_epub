"""Layout analysis: running header/footer removal, footnote zones, column-aware reading order, paragraph splitting."""
from __future__ import annotations

import difflib
import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .ir import ImageItem, Line, PageData, Span, TableItem

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
BULLET_RE = re.compile(r"^\s*([•·▪▫◦●○■□‣⁃∙➢➤▶►–—‒−]|[-*])\s+(?=\S)")
GLYPH_BULLET_RE = re.compile(r"^\s*[•·▪▫◦●○■□‣⁃∙➢➤▶►]\s*(?=\S)")
NUM_RE = re.compile(r"^\s*(\(?\d{1,3}[.)]|\([a-z]\)|[a-z][.)])\s+(?=\S)")
TERMINAL_RE = re.compile(r"[.!?…:»”\"’)\]]$")
PAGE_NO_RE = re.compile(
    r"^\W*(?:p(?:age|\.)?\s*)?(?:\d{1,5}|[ivxlcdm]{1,7})(?:\s*(?:/|of|sur)\s*\d{1,5})?\W*$", re.I
)
FN_MARK_RE = re.compile(r"^\s*(\d{1,3}|[*†‡§¶]{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)(?=[\s.)\]]|$)[.)\]]?")
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


@dataclass
class Ctx:
    body_size: float = 11.0
    median_height: float = 13.0
    gap_norm: float = 0.1  # median inter-line gap / font size inside paragraphs
    vocab: Counter = field(default_factory=Counter)
    hyph_vocab: Counter = field(default_factory=Counter)
    npages: int = 0
    detect_columns: bool = True


def body_size(pages: list[PageData]) -> float:
    cnt: Counter = Counter()
    for p in pages:
        for l in p.lines:
            for s in l.spans:
                if s.text.strip() and not s.sup and not s.sub:
                    cnt[round(s.size * 2) / 2] += len(s.text.strip())
    return cnt.most_common(1)[0][0] if cnt else 11.0


def compute_ctx(pages: list[PageData], detect_columns: bool) -> Ctx:
    ctx = Ctx(npages=len(pages), detect_columns=detect_columns)
    ctx.body_size = body_size(pages)
    heights = []
    gaps = []
    vocab: Counter = Counter()
    hyph_vocab: Counter = Counter()
    for p in pages:
        ls = sorted(p.lines, key=lambda l: (l.y0, l.x0))
        for l in ls:
            if abs(l.size - ctx.body_size) <= 0.8:
                heights.append(l.height)
            tl = l.text.lower()
            for w in re.findall(r"[^\W\d_]{2,}", tl):
                vocab[w] += 1
            for w in re.findall(r"(?<![\w-])[^\W\d_]+-[^\W\d_]+(?![\w-])", tl[:-1] if tl.endswith("-") else tl):
                hyph_vocab[w] += 1
        for i, a in enumerate(ls):
            if abs(a.size - ctx.body_size) > 0.8:
                continue
            # the next line below in the same column (in (y, x) order the other column's line usually comes first)
            for b in ls[i + 1:i + 10]:
                ov = min(a.x1, b.x1) - max(a.x0, b.x0)
                if b.y0 <= a.y0 + 0.5 * a.height or ov < 0.5 * min(a.x1 - a.x0, b.x1 - b.x0):
                    continue
                if abs(b.size - ctx.body_size) <= 0.8:
                    g = b.y0 - a.y1
                    if -0.5 * a.height < g < 1.5 * ctx.body_size:
                        gaps.append(g / ctx.body_size)
                break
    ctx.vocab = vocab
    ctx.hyph_vocab = hyph_vocab
    if heights:
        ctx.median_height = statistics.median(heights)
    if gaps:
        ctx.gap_norm = statistics.median(gaps)
    return ctx


def snap_ocr_sizes(page: PageData, tol: float = 0.15) -> None:
    """OCR text (Tesseract, or an invisible OCR layer) gets a size per line from the glyph boxes, which jitters by
    10-15 % between body lines and would split paragraphs. Lines within `tol` of the page's body size get that size."""
    acc: Counter = Counter()
    for l in page.lines:
        acc[round(l.size * 2) / 2] += len(l.text.strip())
    if not acc:
        return
    total = sum(acc.values())
    run = 0
    med = 0.0
    for size in sorted(acc):
        run += acc[size]
        if run >= total / 2:
            med = size
            break
    for l in page.lines:
        if med and abs(l.size - med) <= tol * med:
            for s in l.spans:
                if not (s.sup or s.sub):
                    s.size = med


_WORD_RE = re.compile(r"[^\W\d_]+")


def drop_ocr_noise(pages: list[PageData], ctx: Ctx) -> int:
    """OCR of ornaments, plates and smudges yields lines like "TSeAd ab oe aa" or "ener * KK xk *". On OCR pages, drop
    lines whose letters mostly belong to words the book never uses elsewhere AND that look like noise (very short
    tokens or many symbols). A real short line ("fathers.") has normal word lengths and is kept."""
    dropped = 0
    for p in pages:
        if not (p.source == "ocr" or p.ocr_layer):
            continue
        keep = []
        for l in p.lines:
            t = l.text.strip()
            letters = sum(c.isalpha() for c in t)
            words = _WORD_RE.findall(t.lower())
            if letters >= 3 and words:
                known = sum(len(w) for w in words if len(w) >= 2 and ctx.vocab.get(w, 0) >= 3)
                mean_len = letters / len(words)
                symbols = sum(1 for c in t if not (c.isalnum() or c.isspace() or c in ".,;:'’!?-«»\"()")) / max(1, len(t))
                short_tokens = mean_len < 3.5 and max(len(w) for w in words) <= 5
                if known < 0.35 * letters and (short_tokens or symbols > 0.2):
                    dropped += 1
                    continue
            keep.append(l)
        p.lines = keep
    return dropped


# ---------------------------------------------------------------------------
# Running headers / footers
# ---------------------------------------------------------------------------
def _norm_key(text: str) -> str:
    t = re.sub(r"\d+", "#", text.strip().lower())
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = re.sub(r"[\s.,;:'’\"«»|_^-]+", "", t)  # OCR shifts spaces and misreads accents / punctuation in running heads
    bare = t.strip("#")  # the folio may sit on either side of the head (verso / recto): same key
    return bare if bare else t


def _merge_misread_heads(keyed: list[list[tuple[object, tuple]]]) -> None:
    """Map the outermost margin line of a page to a recurring head key when it reads almost the same (OCR misreads such
    as "KOMAN" or a page number read "3f" would otherwise break the chain of identical keys)."""
    count: Counter = Counter(k for entries in keyed for _, k in entries)
    need = 3 if len(keyed) < 20 else 4  # short documents (scanned excerpts) have few pages to agree
    frequent = [k for k, c in count.items() if c >= need and len(k[1]) >= 6 and not k[1].startswith("img")]
    if not frequent:
        return
    for entries in keyed:
        for band in ("t", "b"):
            same = [i for i, (o, k) in enumerate(entries) if k[0] == band and isinstance(o, Line)]
            if not same:
                continue
            pick = min if band == "t" else max
            i = pick(same, key=lambda i: entries[i][0].y0 if band == "t" else entries[i][0].y1)
            obj, key = entries[i]
            if count[key] >= need:
                continue
            best, score = None, 0.8
            for fk in frequent:
                if fk[0] == band and abs(len(fk[1]) - len(key[1])) <= 0.3 * len(fk[1]):
                    r = difflib.SequenceMatcher(None, fk[1], key[1]).ratio()
                    if r >= score:
                        best, score = fk, r
            if best is not None:
                entries[i] = (obj, best)


def remove_running(pages: list[PageData], warnings: list[str], heads: Counter | None = None) -> int:
    """Drop running headers/footers and page numbers: text that recurs in the top/bottom band on neighbouring pages.
    `heads` (optional) counts the removed running lines by normalised text (folios and punctuation stripped)."""
    n = len(pages)
    if n == 0:
        return 0
    bs = body_size(pages)
    pos: dict[tuple, dict[int, float]] = {}  # key -> {page number: y}
    keyed: list[list[tuple[object, tuple]]] = []
    for p in pages:
        H = p.height
        entries = []
        for l in p.lines:
            band = "t" if l.y1 < 0.15 * H else "b" if l.y0 > 0.85 * H else None
            if band and l.size <= bs * 1.2:
                entries.append((l, (band, _norm_key(l.text))))
        for im in p.images:
            band = "t" if im.bbox[3] < 0.15 * H else "b" if im.bbox[1] > 0.85 * H else None
            if band and im.xref:
                entries.append((im, (band, f"img{im.xref}")))
        keyed.append(entries)
    _merge_misread_heads(keyed)
    for p, entries in zip(pages, keyed):
        for o, k in entries:
            pos.setdefault(k, {}).setdefault(p.number, o.bbox[1])
    height = {p.number: p.height for p in pages}
    ocr_pages = {p.number for p in pages if p.source == "ocr" or p.ocr_layer}

    def chained(key, pno) -> bool:
        """Is `pno` part of a run of >= 3 pages carrying this key at about the same height, with gaps <= 2?"""
        where = pos.get(key, {})
        if pno not in where or len(where) < 3:
            return False
        med = statistics.median(where.values())
        pg = sorted(q for q, y in where.items() if abs(y - med) <= (0.05 if q in ocr_pages else 0.02) * height[q])
        if pno not in pg:
            return False
        i = pg.index(pno)
        lo = i
        while lo > 0 and pg[lo] - pg[lo - 1] <= 2:
            lo -= 1
        hi = i
        while hi < len(pg) - 1 and pg[hi + 1] - pg[hi] <= 2:
            hi += 1
        return hi - lo + 1 >= 3

    removed = 0
    for p, entries in zip(pages, keyed):
        drop_lines: set[int] = set()
        drop_imgs: set[int] = set()
        for obj, key in entries:
            if n >= 3 and chained(key, p.number):
                (drop_lines if isinstance(obj, Line) else drop_imgs).add(id(obj))
                if heads is not None and isinstance(obj, Line):
                    heads[re.sub(r"[^a-z]", "", key[1])] += 1
        # isolated page numbers, even when not repeated (e.g. first page)
        H = p.height
        folios = []
        for l in p.lines:
            if (l.y1 < 0.09 * H or l.y0 > 0.91 * H) and len(l.text.strip()) <= 12 and PAGE_NO_RE.match(l.text.strip()):
                drop_lines.add(id(l))
                folios.append(l)
        # a short margin line on the same row as the page number or as a chained running head is a running head too,
        # even if it never forms a chain itself (short chapters break the verso / recto sequence; "Chapitre IV" changes)
        anchors = folios + [l for l in p.lines if id(l) in drop_lines and (l.y1 < 0.15 * H or l.y0 > 0.85 * H)]
        for f in anchors:
            for l in p.lines:
                if id(l) in drop_lines or l.size > bs * 1.2 or len(l.text.strip()) > 80:
                    continue
                if not (l.y1 < 0.15 * H or l.y0 > 0.85 * H):
                    continue
                if min(l.y1, f.y1) - max(l.y0, f.y0) >= 0.5 * min(l.height, f.height):
                    drop_lines.add(id(l))
        before = len(p.lines)
        p.lines = [l for l in p.lines if id(l) not in drop_lines]
        p.images = [im for im in p.images if id(im) not in drop_imgs]
        removed += before - len(p.lines)
    return removed


# ---------------------------------------------------------------------------
# Footnotes
# ---------------------------------------------------------------------------
@dataclass
class RawNote:
    marker: str
    lines: list[Line]
    page: int
    orphan: bool = False


def _norm_marker(m: str) -> str:
    return m.translate(_SUPERSCRIPT_DIGITS)


def _strip_marker(line: Line, n_chars: int) -> Line:
    """Remove the first n_chars non-space characters of the line (the footnote marker)."""
    spans: list[Span] = []
    todo = n_chars
    for s in line.spans:
        if todo <= 0:
            spans.append(s)
            continue
        t = s.text
        stripped = t.lstrip()
        lead = len(t) - len(stripped)
        take = min(todo, len(stripped))
        todo -= take
        rest = stripped[take:]
        if rest.strip():
            spans.append(Span(rest.lstrip() if todo == 0 and take else rest, s.size, s.bold, s.italic, False, False, s.mono, s.bbox, s.link))
        _ = lead
    return Line(spans, line.bbox, line.page)


def split_footnotes(page: PageData, ctx: Ctx) -> tuple[list[RawNote], list[Line]]:
    body = ctx.body_size
    small = body * 0.94
    cand = [l for l in page.lines if l.y0 > page.height * 0.45 and 0 < l.size <= small]
    starts = [l for l in cand if FN_MARK_RE.match(l.text)]
    if not starts:
        return [], page.lines
    first = min(starts, key=lambda l: l.y0)
    zone = [l for l in page.lines if l.y0 >= first.y0 - 1 and 0 < l.size <= small]
    zone_ids = {id(l) for l in zone}
    rest = [l for l in page.lines if id(l) not in zone_ids]
    refs = {_norm_marker(s.text.strip()) for l in rest for s in l.spans if s.sup and s.text.strip()}
    refs |= {_norm_marker(m) for l in rest for m in re.findall(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+", l.text)}

    good: list[RawNote] = []
    bad: list[RawNote] = []
    for flow in xycut(zone, ctx, True):
        notes: list[RawNote] = []
        cur: RawNote | None = None
        for l in sorted(flow.items, key=lambda l: (l.y0, l.x0)):
            m = FN_MARK_RE.match(l.text)
            if m:
                marker = _norm_marker(m.group(1))
                stripped = _strip_marker(l, len(m.group(1).strip()))
                if cur is not None:
                    notes.append(cur)
                cur = RawNote(marker, [stripped], page.number)
            elif cur is not None:
                cur.lines.append(l)
            else:
                bad.append(RawNote("", [l], page.number))
        if cur is not None:
            notes.append(cur)
        matched = [n for n in notes if n.marker in refs]
        if matched:
            good += matched
            bad += [n for n in notes if n.marker not in refs]
            continue
        nums = [int(n.marker) for n in notes if n.marker.isdigit()]
        if len(notes) >= 2 and len(nums) == len(notes) and all(b - a == 1 for a, b in zip(nums, nums[1:])):
            for n in notes:
                n.orphan = True
            good += notes
        else:
            bad += notes
    if not good:
        return [], page.lines
    # lines of rejected notes go back into the body flow (they are probably captions or table notes)
    back = [l for n in bad for l in n.lines]
    return good, rest + back


# ---------------------------------------------------------------------------
# Reading order (XY-cut)
# ---------------------------------------------------------------------------
@dataclass
class Flow:
    items: list
    kind: str = "band"  # "col" | "band"


def _bb(it):
    return it.bbox


def _merge_intervals(iv: list[tuple[float, float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _nchars(items) -> float:
    ls = [len(i.text) for i in items if isinstance(i, Line)]
    return statistics.mean(ls) if ls else 99.0


def _prose_gutter(items: list, gaps: list[tuple[float, float]]) -> tuple[float, float] | None:
    """The vertical gap with running text on both sides (>= 3 lines of >= 25 characters each side, and most of the
    text lines of each side), best balanced: a column gutter."""
    best, score = None, 0
    for g in gaps:
        cut = (g[0] + g[1]) / 2
        left = [i for i in items if isinstance(i, Line) and (_bb(i)[0] + _bb(i)[2]) / 2 <= cut]
        right = [i for i in items if isinstance(i, Line) and (_bb(i)[0] + _bb(i)[2]) / 2 > cut]
        lp = sum(1 for i in left if len(i.text.strip()) >= 25)
        rp = sum(1 for i in right if len(i.text.strip()) >= 25)
        if lp >= 3 and rp >= 3 and min(lp, rp) > score:
            best, score = g, min(lp, rp)
    return best


def _bands_between_wide(bands: list[list], items: list) -> list[list]:
    """Horizontal cuts only around full-width elements (titles, author blocks, wide figures / tables, their captions):
    the two-column text between two of them stays one band, so its columns are found as a whole instead of being
    sliced at every blank row shared by both columns (which glued a left-column line to a right-column table row)."""
    if len(bands) < 3:
        return bands
    x0 = min(_bb(i)[0] for i in items)
    x1 = max(_bb(i)[2] for i in items)
    w = max(x1 - x0, 1.0)

    def wide(band) -> bool:
        return any(_bb(i)[2] - _bb(i)[0] >= 0.6 * w for i in band)

    groups: list[list[list]] = []
    for band in bands:
        if groups and not wide(band) and not wide(groups[-1][-1]):
            groups[-1].append(band)
        else:
            groups.append([band])
    out: list[list] = []
    for g in groups:
        merged = [i for band in g for i in band]
        if len(g) > 1:
            iv = _merge_intervals([(_bb(i)[0], _bb(i)[2]) for i in merged])
            gaps = [(iv[k][1], iv[k + 1][0]) for k in range(len(iv) - 1)]
            if _prose_gutter(merged, gaps) is None:  # no running text in two columns (a table of labels / values)
                out += g
                continue
        out.append(merged)
    return out if len(out) > 1 else bands


def xycut(items: list, ctx: Ctx, allow_cols: bool, depth: int = 0) -> list[Flow]:
    if not items:
        return []
    if len(items) == 1 or depth > 40:
        return [Flow(sorted(items, key=lambda i: (_bb(i)[1], _bb(i)[0])))]
    min_gap = max(7.0, 0.6 * ctx.body_size)
    # --- vertical cut (columns)
    if allow_cols and len(items) >= 4:
        merged = _merge_intervals([(_bb(i)[0], _bb(i)[2]) for i in items])
        gaps = [(merged[k][1], merged[k + 1][0]) for k in range(len(merged) - 1) if merged[k + 1][0] - merged[k][1] >= min_gap]
        gutter = _prose_gutter(items, gaps)
        if gutter is not None:  # columns of running text: cut there first (a table's cell gaps come later, inside)
            cut = (gutter[0] + gutter[1]) / 2
            sides = [[i for i in items if (_bb(i)[0] + _bb(i)[2]) / 2 <= cut], [i for i in items if (_bb(i)[0] + _bb(i)[2]) / 2 > cut]]
            flows = []
            for side in sides:
                sub = xycut(side, ctx, allow_cols, depth + 1)
                for f in sub:
                    f.kind = "col"
                flows += sub
            return flows
        while gaps:
            cuts = [(a + b) / 2 for a, b in gaps]
            sides: list[list] = [[] for _ in range(len(cuts) + 1)]
            for it in items:
                cx = (_bb(it)[0] + _bb(it)[2]) / 2
                sides[sum(1 for c in cuts if cx > c)].append(it)
            bad = None
            for k, s in enumerate(sides):
                if len(s) < 2 or (_nchars(s) < 8 and len(s) >= 2 and all(isinstance(i, Line) for i in s)):
                    bad = k
                    break
            if bad is None:
                flows: list[Flow] = []
                for s in sides:
                    sub = xycut(s, ctx, allow_cols, depth + 1)
                    for f in sub:
                        f.kind = "col"
                    flows += sub
                return flows
            # drop the narrowest gap next to the offending side
            adj = [g for g in (bad - 1, bad) if 0 <= g < len(gaps)]
            drop = min(adj, key=lambda g: gaps[g][1] - gaps[g][0])
            gaps.pop(drop)
    # --- horizontal cut (bands)
    hmin = max(1.5, 0.3 * ctx.median_height)
    merged = _merge_intervals([(_bb(i)[1], _bb(i)[3]) for i in items])
    cuts = [(merged[k][1] + merged[k + 1][0]) / 2 for k in range(len(merged) - 1) if merged[k + 1][0] - merged[k][1] >= hmin]
    if not cuts:
        return [Flow(sorted(items, key=lambda i: (round(_bb(i)[1], 1), _bb(i)[0])))]
    bands: list[list] = [[] for _ in range(len(cuts) + 1)]
    for it in items:
        cy = (_bb(it)[1] + _bb(it)[3]) / 2
        bands[sum(1 for c in cuts if cy > c)].append(it)
    if allow_cols:
        bands = _bands_between_wide(bands, items)
    flows = []
    pending: list = []
    for band in bands:
        if not band:
            continue
        sub = xycut(band, ctx, allow_cols, depth + 1)
        if len(sub) == 1 and sub[0].kind == "band":
            pending += sub[0].items
        else:
            if pending:
                flows.append(Flow(pending, "band"))
                pending = []
            flows += sub
    if pending:
        flows.append(Flow(pending, "band"))
    return flows


# ---------------------------------------------------------------------------
# Paragraph building
# ---------------------------------------------------------------------------
@dataclass
class RawBlock:
    kind: str  # "text" | "image" | "table"
    page: int
    y0: float
    lines: list[Line] = field(default_factory=list)
    item: ImageItem | TableItem | None = None
    left: float = 0.0
    right: float = 0.0
    break_before: str | None = None
    ocr: bool = False  # from an OCR page / OCR text layer: sizes are estimates, no bold / italic
    space_above: float | None = None  # gap to the previous line of the same flow (None: first in its flow)
    centred: bool = False
    math: bool = False  # a one-row display formula (`Line.kind == "dmath"`)

    @property
    def text(self) -> str:
        return " ".join(l.text.strip() for l in self.lines)

    @property
    def size(self) -> float:
        acc: Counter = Counter()
        for l in self.lines:
            for s in l.spans:
                if s.text.strip():
                    acc[round(s.size, 1)] += len(s.text.strip())
        return acc.most_common(1)[0][0] if acc else 0.0

    @property
    def min_x0(self) -> float:
        return min(l.x0 for l in self.lines)

    @property
    def max_x1(self) -> float:
        return max(l.x1 for l in self.lines)

    @property
    def first_indent(self) -> bool:
        return bool(self.lines) and self.lines[0].x0 - self.left > 0.7 * max(self.size, 1)

    @property
    def mono(self) -> bool:
        return bool(self.lines) and all(l.is_mono for l in self.lines)


def fix_dropcaps(lines: list[Line], ctx: Ctx) -> list[Line]:
    caps = [l for l in lines if 0 < len(l.text.strip()) <= 2 and l.size >= 1.8 * ctx.body_size]
    if not caps:
        return lines
    out = list(lines)
    for d in caps:
        best = None
        for n in lines:
            if n is d or n.size > d.size / 1.5 or n.x0 < d.x1 - 3:
                continue
            if not (d.y0 - 2 <= n.y0 <= d.y1) or n.x0 - d.x1 > 3 * ctx.body_size:
                continue
            if best is None or n.y0 < best.y0:
                best = n
        if best is None or best not in out:
            continue
        sp = [Span(s.text, best.size, s.bold, s.italic, False, False, s.mono, s.bbox) for s in d.spans]
        # keep the first line's own height: the cap's full height would make it overlap (and swallow) the next lines
        merged = Line(sp + best.spans, (d.x0, best.y0, max(d.x1, best.x1), best.y1), best.page)
        out[out.index(best)] = merged
        if d in out:
            out.remove(d)
    return out


def join_rows(items: list) -> list:
    """Lines of the same visual row that were not separated into columns become one line (left to right)."""
    res: list = []
    i = 0
    n = len(items)
    while i < n:
        it = items[i]
        if not isinstance(it, Line):
            res.append(it)
            i += 1
            continue
        row = [it]
        j = i + 1
        while j < n and isinstance(items[j], Line) and it.kind != "dmath" and items[j].kind != "dmath":
            ov = min(it.y1, items[j].y1) - max(it.y0, items[j].y0)
            b = items[j]
            side_by_side = all(b.x0 >= r.x1 - 2 or b.x1 <= r.x0 + 2 for r in row)  # one row = disjoint in x
            if ov >= 0.5 * min(it.height, b.height) and side_by_side:
                row.append(items[j])
                j += 1
            else:
                break
        if len(row) > 1:
            row.sort(key=lambda l: l.x0)
            a = row[0]
            spans = list(a.spans)
            x1, y0, y1 = a.x1, a.y0, a.y1
            for b in row[1:]:
                gap = b.x0 - x1
                if a.is_mono and b.is_mono:  # code: keep the horizontal distance as spaces
                    spans.append(Span(" " * max(1, round(gap / (0.6 * max(a.size, 1.0)))), a.size, mono=True))
                elif gap > 0.1 * max(a.size, 1.0):
                    spans.append(Span(" ", a.size))
                spans += b.spans
                x1, y0, y1 = max(x1, b.x1), min(y0, b.y0), max(y1, b.y1)
            it = Line(spans, (a.x0, y0, x1, y1), a.page)
        res.append(it)
        i = j
    return res


def _col_bounds(lines: list[Line], ctx: Ctx, fallback: tuple[float, float]) -> tuple[float, float]:
    body = [l for l in lines if abs(l.size - ctx.body_size) <= 1.0 and len(l.text.strip()) >= 25]
    if len(body) < 3:
        body = [l for l in lines if len(l.text.strip()) >= 3] or lines
        if len(body) < 2:
            return fallback
    c = Counter(round(l.x0 / 2) * 2 for l in body)
    mode = c.most_common(1)[0][0]
    xs = sorted(l.x0 for l in body if abs(l.x0 - mode) <= 3)
    left = statistics.median(xs) if xs else mode
    right = max(l.x1 for l in body)
    return left, right


def is_centered(l: Line, left: float, right: float, size: float) -> bool:
    offl, offr = l.x0 - left, right - l.x1
    return offl >= 1.5 * size and offr >= 1.5 * size and abs(offl - offr) <= 1.2 * size and (l.x1 - l.x0) < 0.85 * (right - left)


def _is_break(prev: Line, cur: Line, left: float, right: float, ctx: Ctx, ocr: bool = False) -> bool:
    size = max(prev.size, 1.0)
    if abs(prev.size - cur.size) > max(0.8, 0.07 * size):
        return True
    if (prev.bold_ratio > 0.8) != (cur.bold_ratio > 0.8):
        return True
    pm, cm = prev.is_mono, cur.is_mono
    if pm != cm:
        return True
    gap = cur.y0 - prev.y1
    if pm and cm:  # code: keep blank lines and indentation changes inside one block
        return gap > 3 * size
    ptext = prev.text.rstrip()
    ends = bool(TERMINAL_RE.search(ptext))
    if gap > max(0.25 * size, (ctx.gap_norm + 0.28) * size):
        # OCR line positions jitter by half a line: there a plain gap only ends a paragraph after a sentence
        if not ocr or ends or gap > 1.5 * size:
            return True
    short = (right - prev.x1) > max(0.2 * (right - left), 5 * size)
    ctext = cur.text
    if GLYPH_BULLET_RE.match(ctext) or (BULLET_RE.match(ctext) and cur.x0 - left < 3 * size and (ends or short)):
        return True
    if NUM_RE.match(ctext) and (ends or short):
        return True
    indent_cur = cur.x0 - left
    indent_prev = prev.x0 - left
    if indent_cur > 0.7 * size and indent_prev <= 0.7 * size and indent_cur < 5 * size and (ends or short):
        return True
    if is_centered(cur, left, right, size) and is_centered(prev, left, right, size):
        if abs(cur.x0 - prev.x0) > 0.6 * size or abs(cur.x1 - prev.x1) > 0.6 * size:
            return True
    if ends and short:
        return True
    return False


def split_flow(items: list, ctx: Ctx, page: PageData, fallback: tuple[float, float]) -> list[RawBlock]:
    items = join_rows(items)
    lines = [i for i in items if isinstance(i, Line)]
    left, right = _col_bounds(lines, ctx, fallback)
    blocks: list[RawBlock] = []
    cur: list[Line] = []

    ocr = page.source == "ocr" or page.ocr_layer
    prev_y1: list[float | None] = [None]

    def flush():
        nonlocal cur
        if cur:
            size = max(cur[0].size, 1.0)
            above = None if prev_y1[0] is None else cur[0].y0 - prev_y1[0]
            centred = all(is_centered(l, left, right, size) for l in cur)
            blocks.append(RawBlock("text", page.number, cur[0].y0, cur, None, left, right, None, ocr, above, centred))
            prev_y1[0] = cur[-1].y1
            cur = []

    for it in items:
        if isinstance(it, Line):
            if not it.text.strip():
                continue
            if it.kind == "dmath":  # a display formula is a block of its own
                flush()
                cur.append(it)
                flush()
                blocks[-1].math = True
                continue
            if cur and _is_break(cur[-1], it, left, right, ctx, page.source == "ocr" or page.ocr_layer):
                flush()
            cur.append(it)
        else:
            flush()
            kind = "table" if isinstance(it, TableItem) else "image"
            blocks.append(RawBlock(kind, page.number, it.bbox[1], [], it, left, right))
            prev_y1[0] = it.bbox[3]
    flush()
    return blocks


def page_blocks(page: PageData, ctx: Ctx) -> tuple[list[RawBlock], list[RawNote]]:
    notes, lines = split_footnotes(page, ctx)
    lines = fix_dropcaps(lines, ctx)
    items: list = list(lines) + list(page.images) + list(page.tables)
    flows = xycut(items, ctx, ctx.detect_columns)
    fb = _col_bounds([l for l in lines], ctx, (0.0, page.width))
    blocks: list[RawBlock] = []
    for fi, f in enumerate(flows):
        bl = split_flow(f.items, ctx, page, fb)
        if bl:
            bl[0].break_before = "page" if not blocks else "column"
            blocks += bl
    return blocks, notes
