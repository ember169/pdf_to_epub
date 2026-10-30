"""Chapters of scanned books, from the page layout.

A scan has no outline and its OCR font sizes are estimates, so the size-based heading model cannot tell a chapter title
from body text (that produced dozens of bogus chapters, and the strict OCR rules that replaced it found none). Printed
books mark a chapter in other ways, and this module combines them:

* the chapter-opening page: the text starts lower than on ordinary pages ("sink"), with one or more short, centred,
  capitalised lines above the first paragraph; a half-title page with the same title may precede it;
* label patterns: "CHAPTER IV", "Chapitre premier", "LIVRE II", "I.", "II." alone on a line;
* consistency: an opening counts only if the book has at least three of them (one centred line at the top of one page
  is not a pattern), or if it matches the printed table of contents;
* the printed table of contents: entries with page numbers, matched (fuzzy title + page offset) to the openings, and
  used to find an opening the layout alone missed.

Openings preceded by a half-title page (or set much larger than the others) are chapters and the others sections; a
book without that distinction gets one chapter per opening. Roman numerals alone on a centred line in mid-page are
numbered parts inside a chapter. The result is a `Plan` that `structure.convert_blocks` applies.
"""
from __future__ import annotations

import difflib
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .ir import PageData
from .layout import Ctx, RawBlock

_ROMAN = r"(?=[IVXLC])M{0,3}(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})"
_WORDS_EN = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|first|second|third|fourth|fifth|last"
_WORDS_FR = "premier|première|un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|dernier|dernière"
_NUM = rf"(?:{_ROMAN}|\d{{1,3}}|{_WORDS_EN}|{_WORDS_FR})"
LABEL_RE = re.compile(rf"^(?:chapter|chapitre|chap\.|book|livre|part|partie|section|canto|kapitel)\s+{_NUM}\b\.?", re.I)
NUMERAL_RE = re.compile(rf"^{_ROMAN}\s*[.:—–-]?$")
_TOC_LINE_RE = re.compile(r"^(?P<t>[^\d]*?[^\W\d_]{3}[^\d]*?)[\s.·•■…_,;:-]*(?P<n>\d{1,4})\s*\.?$")
_TOC_TITLE_RE = re.compile(r"^(table(\s+des\s+mati[eè]res)?|contents|table of contents|sommaire)\W*$", re.I)


@dataclass
class Plan:
    """Headings to force (`id(RawBlock)` of the first block -> (level, blocks merged into the heading, replacement text
    or None)), blocks to drop
    (half-title pages repeating the next title) and whether other OCR headings must stay out of chapter splitting."""

    forced: dict[int, tuple[int, list[RawBlock], str | None]] = field(default_factory=dict)
    skip: set[int] = field(default_factory=set)
    chapters: int = 0


@dataclass
class _Cand:
    page: int
    groups: list[list[RawBlock]]  # title lines, split into sub-groups at large gaps
    title: int  # index of the chapter-title sub-group
    score: int = 0
    major: bool = False
    toc: bool = False


def _key(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z]", "", t.encode("ascii", "ignore").decode())


def similar(a: str, b: str, need: float = 0.75) -> bool:
    a, b = _key(a), _key(b)
    if len(a) < 3 or len(b) < 3:
        return False
    short, long_ = sorted((a, b), key=len)
    if short in long_ and len(short) >= 0.6 * len(long_):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= need


def _caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) >= 0.7 * len(letters)


def _title_case(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", text)
    big = [w for w in words if len(w) > 3]
    return 0 < len(words) <= 9 and all(w[0].isupper() for w in big) and text[:1].isupper()


def _title_like(b: RawBlock) -> bool:
    if b.kind != "text" or len(b.lines) > 2:
        return False
    t = " ".join(b.text.split())
    if not t or len(t) > 80 or t.endswith(("-", ",", ";")) or re.search(r"(?i)copyright|©|\b1[5-9]\d\d\b", t):
        return False
    if NUMERAL_RE.match(t) or LABEL_RE.match(t):
        return True
    return sum(c.isalpha() for c in t) >= 2 and (_caps(t) or _title_case(t))


def _body_like(b: RawBlock, min_lines: int = 2) -> bool:
    if b.kind != "text" or len(b.lines) < min_lines:
        return False
    return statistics.mean(len(l.text.strip()) for l in b.lines) >= 25


class _Geometry:
    """Per-page text column (from long lines; else the median of pages with the same parity) and the usual top of the
    text, to measure centring and the sink of chapter-opening pages."""

    def __init__(self, pages: list[PageData], by_page: dict[int, list[RawBlock]]):
        self.cols: dict[int, tuple[float, float]] = {}
        parity: dict[int, list[tuple[float, float]]] = {0: [], 1: []}
        for p in pages:
            long_ = [l for l in p.lines if len(l.text.strip()) >= 35]
            if len(long_) >= 3:
                c = (statistics.median(l.x0 for l in long_), statistics.median(l.x1 for l in long_))
                self.cols[p.number] = c
                parity[p.number % 2].append(c)
        self.default = {k: (statistics.median(a for a, _ in v), statistics.median(b for _, b in v)) if v else None
                        for k, v in parity.items()}
        height = {p.number: p.height for p in pages}
        tops = []
        for pno, bs in by_page.items():
            text = [b for b in bs if b.kind == "text"]
            if len(text) >= 2 and _body_like(text[0]):
                tops.append(text[0].y0 / height[pno])
        self.top = statistics.median(tops) if tops else 0.1

    def col(self, pno: int, page: PageData) -> tuple[float, float]:
        return self.cols.get(pno) or self.default.get(pno % 2) or (0.1 * page.width, 0.9 * page.width)

    def centred(self, b: RawBlock, pno: int, page: PageData) -> bool:
        left, right = self.col(pno, page)
        w = right - left
        if w <= 0:
            return False
        # (a short, title-like line spanning the whole column is letter-spaced display type: centred too)
        return all(abs((l.x0 + l.x1) / 2 - (left + right) / 2) <= 0.09 * w for l in b.lines)


def _groups(blocks: list[RawBlock], body: float) -> list[list[RawBlock]]:
    """Split the title lines into sub-groups at gaps of more than ~2.5 lines (title / subtitle / section)."""
    out: list[list[RawBlock]] = []
    prev = None
    for b in blocks:
        if prev is None or b.y0 - prev.lines[-1].y1 > 2.5 * body:
            out.append([b])
        else:
            out[-1].append(b)
        prev = b
    return out


def _text(blocks: list[RawBlock]) -> str:
    return " ".join(" ".join(b.text.split()) for b in blocks)


def _parse_toc(pages: list[PageData]) -> list[tuple[str, int]]:
    """Entries ("title", printed page) of a printed table of contents: a page (or two) with many lines ending in a page
    number, mostly increasing, or headed TABLE / CONTENTS."""
    entries: list[tuple[str, int]] = []
    prev_toc = False
    for p in pages:
        lines = sorted(p.lines, key=lambda l: (l.y0, l.x0))
        found = []
        for l in lines:
            t = " ".join(l.text.split())
            m = _TOC_LINE_RE.match(t)
            if m and not t.startswith(("—", "-", "–")) and len(m.group("t").strip()) >= 4:
                found.append((m.group("t").strip(" .·•■…_,;:-"), int(m.group("n"))))
        headed = any(_TOC_TITLE_RE.match(" ".join(l.text.split())) for l in lines[:3])
        nums = [n for _, n in found]
        rising = sum(1 for a, b in zip(nums, nums[1:]) if b >= a) >= 0.7 * max(1, len(nums) - 1)
        if (len(found) >= 5 or (headed and len(found) >= 3) or (prev_toc and len(found) >= 3)) and rising:
            entries += found
            prev_toc = True
        else:
            prev_toc = False
    return entries


def plan(raw: list[RawBlock], pages: list[PageData], ctx: Ctx, running: Counter | None = None,
         doc_title: str = "") -> Plan | None:
    """Chapter plan for a book whose pages are mostly OCR, or None when the layout shows no consistent pattern."""
    ocr = [p for p in pages if p.source == "ocr" or p.ocr_layer]
    if len(ocr) < max(8, 0.5 * len(pages)):  # short excerpts and born-digital books keep the size-based model
        return None
    page_of = {p.number: p for p in pages}
    by_page: dict[int, list[RawBlock]] = {}
    for b in raw:
        by_page.setdefault(b.page, []).append(b)
    geo = _Geometry(pages, by_page)
    body = ctx.body_size
    running = running or Counter()
    texts = {pno: [b for b in bs if b.kind == "text"] for pno, bs in by_page.items()}
    order = sorted(texts)

    # ---- candidates: title-like centred lines opening a page, above body text
    cands: dict[int, _Cand] = {}
    half: dict[int, list[RawBlock]] = {}  # half-title pages: page -> its blocks
    for pno in order:
        tb = texts[pno]
        page = page_of[pno]
        head = []
        for b in tb:
            if len(head) < 4 and _title_like(b) and (geo.centred(b, pno, page) or NUMERAL_RE.match(b.text.strip())
                                                     or LABEL_RE.match(b.text.strip())):
                head.append(b)
            else:
                break
        if not head:
            continue
        rest = tb[len(head):]
        if not rest:
            if len(_text(head)) <= 80 and not NUMERAL_RE.match(_text(head)):
                half[pno] = head
            continue
        if not any(_body_like(b, 3) for b in rest[:2]):  # a paragraph follows (not an imprint or a dedication)
            continue
        sink = head[0].y0 / page.height - geo.top
        if sink < 0.03:
            continue
        groups = _groups(head, body)
        t = 0
        # the book's own title repeated above the first chapter ("AN ISLAND PLANT." over "I. / THE ROOTS."): the doc
        # title, or a running head used across the book (a chapter's own running head repeats its title: kept)
        while t < len(groups) - 1 and (running.get(_key(_text(groups[t])), 0) >= max(3, 0.25 * len(pages))
                                       or (doc_title and similar(_text(groups[t]), doc_title, 0.85))):
            t += 1
        c = _Cand(pno, groups, t)
        title = _text(groups[t])
        c.score = (2 if sink >= 0.06 else 1) + 1  # sink, centred
        c.score += _caps(title) + (2 if LABEL_RE.match(title) or NUMERAL_RE.match(_text(groups[t][:1])) else 0)
        c.score += max(b.size for b in groups[t]) >= 1.25 * body
        gap_after = rest[0].y0 - head[-1].lines[-1].y1
        c.score += gap_after >= 4 * body
        cands[pno] = c

    # ---- half-title pages: the same title on the next page with text marks a major opening; the copy is dropped
    skip: set[int] = set()
    for pno, blocks in half.items():
        nxt = next((q for q in order if pno < q <= pno + 3 and q in cands), None)
        if nxt in cands and similar(_text(blocks), _text(cands[nxt].groups[cands[nxt].title]), 0.6):
            cands[nxt].major = True
            cands[nxt].score += 2
            skip.update(id(b) for b in blocks)

    # ---- printed table of contents: confirm openings, find the ones the layout missed
    toc = _parse_toc(pages)
    if toc:
        votes = Counter()
        for title, n in toc:
            for c in cands.values():
                if similar(title, _text(c.groups[c.title]), 0.7):
                    votes[c.page - n] += 1
        offset, n_votes = votes.most_common(1)[0] if votes else (None, 0)
        if offset is not None and n_votes >= 2:
            for title, n in toc:
                target = n + offset
                hit = next((c for q, c in cands.items() if abs(q - target) <= 1
                            and similar(title, _text(c.groups[c.title]), 0.7)), None)
                if hit is not None:
                    hit.toc = True
                    hit.score += 2
                    continue
                for q in (target, target + 1, target + 2):
                    if q in half:  # the half-title: its opening page follows
                        continue
                    tb = texts.get(q, [])
                    first = next((b for b in tb[:2] if _title_like(b) and similar(title, b.text, 0.7)), None)
                    if first is not None and q not in cands:
                        cands[q] = _Cand(q, [[first]], 0, score=3, toc=True)
                        break

    accepted = []
    for c in sorted(cands.values(), key=lambda c: c.page):
        if c.score < 3:
            continue
        if accepted and similar(_text(c.groups[c.title]), _text(accepted[-1].groups[accepted[-1].title]), 0.85):
            skip.update(id(b) for g in c.groups for b in g)  # the chapter's title again: its running head (after plates)
            continue
        accepted.append(c)
    if len(accepted) < 3 and sum(c.toc for c in accepted) < 2:
        return None

    # ---- levels: majors (half-title / much larger title) are chapters, the rest sections, when both kinds exist
    sizes = {c.page: max(b.size for b in c.groups[c.title]) for c in accepted}
    small = [s for s in sizes.values() if s < 1.15 * body]
    for c in accepted:
        if not c.major and small and sizes[c.page] >= 1.3 * body and len(small) >= 2:
            c.major = True
    majors = [c for c in accepted if c.major]
    split_minors = len(majors) >= 2 and len(majors) < len(accepted)
    pl = Plan(skip=skip)
    fixed = _repair_numerals(accepted)
    for c in accepted:
        level = 2 if split_minors and not c.major else 1
        pl.chapters += level == 1
        pl.forced[id(c.groups[c.title][0])] = (level, c.groups[c.title], fixed.get(c.page))
        skip.update(id(b) for b in c.groups[c.title][1:])
        for j, g in enumerate(c.groups[c.title + 1:], 1):  # "DE LA CRITIQUE" / "POLÉMIQUES" / "A M. CHARLES BIGOT"
            pl.forced[id(g[0])] = (min(level + j, 3), g, None)
            skip.update(id(b) for b in g[1:])

    # ---- numbered parts in mid-page: "IV" alone on a centred line, above text
    deepest = max(v[0] for v in pl.forced.values())
    for pno in order:
        tb = texts[pno]
        for i, b in enumerate(tb[:-1]):
            if id(b) in pl.forced or id(b) in skip or not NUMERAL_RE.match(b.text.strip()):
                continue
            above = b.space_above if b.space_above is not None else 99.0
            if above >= 1.2 * body and geo.centred(b, pno, page_of[pno]) and _body_like(tb[i + 1]):
                pl.forced[id(b)] = (min(deepest + 1, 4), [b], None)
    return pl


def _roman(n: int) -> str:
    out = ""
    for v, r in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                 (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + r, n - v
    return out


def _from_roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = re.sub(r"[^IVXLCDM]", "", s)
    total = 0
    for a, b in zip(s, s[1:] + " "):
        total += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return total


def _repair_numerals(accepted: list[_Cand]) -> dict[int, str]:
    """Chapter numbers set alone above the title ("II." / "THE GREEN BRANCHES.") that OCR misread ("BE:" for "III."):
    when the neighbouring openings carry roman numerals n-1 (and n+1), the garbled token is replaced by n. Returns
    page -> full heading text for the repaired openings."""
    firsts = []
    for c in accepted:
        g = c.groups[c.title]
        lines = [l for b in g for l in b.lines]
        first = " ".join(lines[0].text.split()) if lines else ""
        firsts.append((c, lines, first, NUMERAL_RE.match(first) is not None and len(lines) > 1))
    if sum(1 for *_, num in firsts if num) < 2:
        return {}
    out = {}
    for i, (c, lines, first, num) in enumerate(firsts):
        if num or len(lines) < 2 or len(first) > 4 or any(ch.islower() for ch in first):
            continue
        prev = firsts[i - 1] if i else None
        nxt = firsts[i + 1] if i + 1 < len(firsts) else None
        if prev is None or not prev[3]:
            continue
        n = _from_roman(prev[2]) + 1
        if nxt is not None and nxt[3] and _from_roman(nxt[2]) != n + 1:
            continue
        rest = " ".join(" ".join(l.text.split()) for l in lines[1:])
        out[c.page] = f"{_roman(n)}. {rest}"
    return out
