"""A printed table of contents ("Sommaire", "Table des matières", "Contents") as the book's structure, for PDFs
without an outline.

1. `parse`: the contents pages (a "Sommaire" heading near the start or the end of the book, then rows ending with
   page numbers) -> entries: parts ("Deuxième partie" + title), numbered chapters ("5." + author line + title lines),
   other entries ("Introduction", "Épilogue"), and the section lists printed under a chapter in smaller type
   ("Une histoire longue | Les luttes | …").
2. `folios` + `page_offset`: printed page numbers read from the running heads / page numbers of every page, voted into
   one printed -> PDF offset.
3. `apply`: on the converted blocks: the contents pages are dropped (the navigation replaces them); each entry's
   opening page gets one heading (multi-line titles merged, chapter number in front, author lines turned into a byline
   paragraph); the result is a list of `TocEntry` (parts level 1, chapters inside a part level 2, sections one level
   below) that `structure.build_chapters` splits on, like a PDF outline.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from .ir import Heading, PageData, Paragraph, Run
from .openings import _key, similar

TOC_HEAD_RE = re.compile(r"(?i)^\s*(sommaire|table des mati[eè]res|table|contents|table of contents|inhalt"
                         r"(?:sverzeichnis)?|[íi]ndice)\s*$")
ORDINALS = {"premiere": 1, "première": 1, "deuxieme": 2, "deuxième": 2, "seconde": 2, "troisieme": 3, "troisième": 3,
            "quatrieme": 4, "quatrième": 4, "cinquieme": 5, "cinquième": 5, "sixieme": 6, "sixième": 6,
            "septieme": 7, "septième": 7, "huitieme": 8, "huitième": 8, "neuvieme": 9, "neuvième": 9,
            "dixieme": 10, "dixième": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5}
PART_RE = re.compile(r"(?i)^\s*(?:(\w+)\s+partie|(?:partie|part|livre|book)\s+([ivxlc]+|\d+|\w+))\s*[.:]?\s*$")
CHAPTER_RE = re.compile(r"^\s*(\d{1,2})\s*[.)]\s*(.*)$")
PAGE_RE = re.compile(r"^(.*?)[\s.…·_]*\b(\d{1,4})\s*$")
NAME_WORD_RE = re.compile(r"^(?:[A-ZÀ-Ý][\w'’\-.]*|[A-Z]\.|de|du|des|da|van|von|der|le|la|et|and|&|bell)$")


@dataclass
class Entry:
    kind: str  # "part" | "chapter" | "other"
    title: str
    printed: int
    number: int | None = None
    label: str = ""  # "Deuxième partie"
    authors: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    pdf_page: int = 0
    level: int = 1


@dataclass
class Row:
    text: str
    size: float
    page: int
    y0: float
    number: int | None


def _roman(s: str) -> int | None:
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    s = s.lower()
    if not s or any(c not in vals for c in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        total += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return total


def _rows(page: PageData) -> list[Row]:
    """Lines of the page grouped into rows (the page number column is a separate line in most layers)."""
    lines = sorted((l for l in page.lines if l.text.strip()), key=lambda l: (l.y0 + l.y1) / 2)
    rows: list[list] = []
    for l in lines:
        cy = (l.y0 + l.y1) / 2
        if rows and abs(cy - rows[-1][0]) <= 0.45 * max(l.size, 1.0):
            rows[-1][1].append(l)
        else:
            rows.append([cy, [l]])
    out = []
    for _, ls in rows:
        ls.sort(key=lambda l: l.x0)
        text = re.sub(r"\s+", " ", " ".join(l.text.strip() for l in ls)).strip()
        num = None
        m = PAGE_RE.match(text)
        if m and ls[-1].x1 >= 0.55 * page.width and (len(ls) > 1 or ls[-1].x1 - ls[-1].x0 < 0.9 * page.width):
            num, text = int(m.group(2)), m.group(1).strip()
        words = [l for l in ls if not re.fullmatch(r"\d{1,4}", l.text.strip())] or ls
        out.append(Row(text, max(l.size for l in words), page.number, min(l.y0 for l in ls), num))
    # rows the table detector took ("Les corps | 11"): back as rows, in the page's prevailing size
    size = statistics.median([r.size for r in out]) if out else 10.0
    for t in page.tables:
        x0, y0, x1, y1 = t.bbox
        h = (y1 - y0) / max(1, len(t.rows))
        for i, cells in enumerate(t.rows):
            cells = [c.strip() for c in cells if c.strip()]
            if not cells:
                continue
            num = int(cells[-1]) if len(cells) > 1 and re.fullmatch(r"\d{1,4}", cells[-1]) else None
            text = " ".join(cells[:-1] if num is not None else cells)
            out.append(Row(text, size, page.number, y0 + i * h, num))
    out.sort(key=lambda r: r.y0)
    return out


def find_toc_pages(pages: list[PageData]) -> list[int]:
    n = len(pages)
    cands = [p for p in pages if p.number <= 15 or p.number > n - 15]
    for p in cands:
        top = sorted((l for l in p.lines if l.text.strip()), key=lambda l: l.y0)[:3]
        if not any(TOC_HEAD_RE.match(l.text) for l in top):
            continue
        found = [p.number]
        if sum(r.number is not None for r in _rows(p)) < 3:
            continue
        for q in pages[p.number:p.number + 6]:  # continuation pages: mostly rows with page numbers
            rs = _rows(q)
            if sum(r.number is not None for r in rs) < 3:
                break
            found.append(q.number)
        return found
    return []


def _author_prefix(text: str, authors: list[str]) -> tuple[str, str] | None:
    """("Sara Farris", "Les fondements …") when `text` starts with the authors' names and goes on with more words."""
    if not authors:
        return None
    import difflib

    want = _key(" ".join(authors))
    words = text.split()
    best, score = None, 0.85
    for n in range(1, min(len(words), 12)):
        k = _key(" ".join(w for w in words[:n] if w.lower() not in ("et", "and", "&", "|")))
        if len(k) > len(want) + 4:
            break
        r = difflib.SequenceMatcher(None, k, want).ratio()
        if r > score:  # the closest prefix, not the longest that passes
            best, score = n, r
    if best is None or best >= len(words):
        return None
    return re.sub(r"\s*\|\s*", ", ", " ".join(words[:best])).strip(" ,"), " ".join(words[best:])


def _authors(line: str) -> list[str]:
    words = line.replace(",", " ").split()
    if not words or len(words) > 12 or not all(NAME_WORD_RE.match(w) for w in words):
        return []
    return [a.strip() for a in re.split(r"\s*(?:,| et | and | & )\s*", line) if a.strip()]


def parse(pages: list[PageData]) -> tuple[list[Entry], list[int]]:
    toc_pages = find_toc_pages(pages)
    if not toc_pages:
        return [], []
    rows = []
    for p in pages:
        if p.number in toc_pages:
            rs = _rows(p)
            if p.number == toc_pages[0]:
                head = next((i for i, r in enumerate(rs) if TOC_HEAD_RE.match(r.text)), -1)
                rs = rs[head + 1:]
            rows += rs
    sizes = [r.size for r in rows if r.number is not None]
    if len(sizes) < 3:
        return [], toc_pages
    entry_size = statistics.median(sizes)
    entries: list[Entry] = []
    buf: list[str] = []
    label = ""
    sec: list[str] = []

    def flush_sections():
        if sec and entries:
            text = re.sub(r"(\w)- (\w)", r"\1\2", " ".join(sec))
            entries[-1].sections += [s.strip(" .") for s in re.split(r"\s*[|¦\[\]]\s*", text) if len(s.strip(" .")) >= 3]
        sec.clear()

    for r in rows:
        if r.number is None and r.size < 0.85 * entry_size and not PART_RE.match(r.text):
            sec.append(r.text)  # a section list, in smaller type
            continue
        flush_sections()
        if r.number is None:
            if PART_RE.match(r.text) and not buf:
                label = r.text.strip(" .:")
            else:
                buf.append(r.text)
            continue
        lines = [x for x in buf + [r.text] if x]
        buf = []
        if not lines:
            continue
        e = Entry("other", "", r.number)
        m = CHAPTER_RE.match(lines[0])
        if label:
            e.kind, e.label = "part", label
            m2 = PART_RE.match(label)
            word = (m2.group(1) or m2.group(2) or "").lower() if m2 else ""
            e.number = ORDINALS.get(word) or (int(word) if word.isdigit() else _roman(word))
            e.title = " ".join(lines)
            label = ""
        elif m:
            e.kind, e.number = "chapter", int(m.group(1))
            rest = ([m.group(2).strip()] if m.group(2).strip() else []) + lines[1:]
            if len(rest) >= 2 and _authors(rest[0]):
                e.authors, rest = _authors(rest[0]), rest[1:]
            e.title = " ".join(rest)
        else:
            e.title = " ".join(lines)
        e.title = re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"\s+", " ", e.title)).strip(" .")
        if e.title:
            entries.append(e)
    flush_sections()
    # levels: parts 1, the chapters after a part 2, the rest 1 (introduction, epilogue, front matter)
    in_part = False
    for i, e in enumerate(entries):
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        if e.kind == "part":
            in_part = True
        elif e.kind == "other":
            # a divider page ("Introduction", "Épilogue") right before a numbered chapter holds it, like a part
            in_part = nxt is not None and nxt.kind == "chapter" and 0 <= nxt.printed - e.printed <= 2
        e.level = 2 if e.kind == "chapter" and in_part else 1
    return entries, toc_pages


# ---------------------------------------------------------------------------------------------------- page numbers
def folios(pages: list[PageData]) -> dict[int, int]:
    """Printed page number of each page, from a number at either end of a line in the top or bottom band."""
    out = {}
    for p in pages:
        band = [l for l in p.lines if l.y1 <= 0.1 * p.height or l.y0 >= 0.9 * p.height]
        for l in sorted(band, key=lambda l: l.y0):
            t = l.text.strip()
            m = re.match(r"^(\d{1,4})\b", t) or re.search(r"\b(\d{1,4})$", t)
            if m and not re.fullmatch(r"(1[5-9]|20)\d\d", m.group(1)):
                out[p.number] = int(m.group(1))
                break
    return out


def page_offset(fol: dict[int, int]) -> int | None:
    """printed - PDF page, voted; None without a clear majority."""
    votes = Counter(v - k for k, v in fol.items())
    if not votes:
        return None
    off, n = votes.most_common(1)[0]
    if n >= 3 and n >= 0.3 * len(fol):
        return off
    return None


def offset_from_titles(entries: list[Entry], pages: list[PageData], toc_pages: list[int]) -> int | None:
    """printed - PDF page from the entries' titles found near the top of a page (when the folios are unreadable)."""
    votes: Counter = Counter()
    for e in entries:
        if len(_key(e.title)) < 6:
            continue
        for p in pages:
            if p.number in toc_pages:
                continue
            top = sorted((l for l in p.lines if l.text.strip()), key=lambda l: l.y0)[:8]
            text = [l.text.strip() for l in top]
            joined = [" ".join(text[i:i + 2]) for i in range(len(text))]
            if any(similar(t, e.title, 0.85) for t in text + joined):
                votes[e.printed - p.number] += 1
    if not votes:
        return None
    off, n = votes.most_common(1)[0]
    return off if n >= 2 and n >= 0.5 * sum(votes.values()) else None


def page_labels(fol: dict[int, int], npages: int) -> dict[int, str]:
    """PDF page -> printed page number, when the folios agree on one offset (page-list navigation)."""
    if len(fol) < max(3, 0.3 * npages):
        return {}
    votes = Counter(v - k for k, v in fol.items())
    off, n = votes.most_common(1)[0]
    if n < 0.5 * len(fol):
        return {}
    return {p: str(p + off) for p in range(1, npages + 1) if p + off >= 1}


# ---------------------------------------------------------------------------------------------------- applying
def _text(b) -> str:
    return "".join(r.text for r in b.runs).strip()


def apply(blocks: list, entries: list[Entry], toc_pages: list[int], offset: int, npages: int):
    """Returns (blocks, toc entries as (level, title, page, y)). Blocks of the contents pages are dropped."""
    blocks = [b for b in blocks if getattr(b, "page", 0) not in toc_pages]
    first_page = min((e.printed - offset for e in entries if 1 <= e.printed - offset <= npages), default=0)
    blocks = [Paragraph(b.runs, "p", b.page, b.y0, b.break_before, size=b.size) if isinstance(b, Heading)
              and b.page < first_page else b for b in blocks]  # title / series / imprint pages: no navigation entries
    by_page: dict[int, list[int]] = {}
    for i, b in enumerate(blocks):
        by_page.setdefault(b.page, []).append(i)
    vocab = Counter(w for b in blocks if isinstance(b, Paragraph) for w in re.findall(r"[^\W\d_]+", _text(b).lower()))

    def plausible(text: str) -> float:  # OCR misreads are rare words in the book's own text
        words = re.findall(r"[^\W\d_]+", text.lower())
        return sum(math.log1p(min(vocab[w], 50)) for w in words) / max(1, len(words))

    toc = []
    replaced: dict[int, list] = {}  # block index -> replacement blocks
    dropped: set[int] = set()
    for e in entries:
        page = e.printed - offset
        if not 1 <= page <= npages:
            continue
        e.pdf_page = page
        idxs = [i for p in (page, page + 1) for i in by_page.get(p, [])][:14]
        best = None  # (score, start, end)
        akey = _key(" ".join(e.authors))

        def is_author(t: str) -> bool:
            k = _key(t)
            return bool(e.authors) and len(k) >= 4 and len(k) <= 1.5 * len(akey) + 4 and (
                similar(t, " ".join(e.authors), 0.75) or k in akey
                or all(_key(x)[:6] in k for x in e.authors if len(_key(x)) >= 6))

        lead = {}  # block index -> (author words, title words): one block printing the authors, then the title

        for a, ia in enumerate(idxs):
            if not isinstance(blocks[ia], (Heading, Paragraph)) or ia in dropped or is_author(_text(blocks[ia])):
                continue
            split = _author_prefix(_text(blocks[ia]), e.authors)
            if split:
                lead[ia] = split
            text = ""
            for b_ in range(a, min(a + 4, len(idxs))):
                ib = idxs[b_]
                if ib in dropped or not isinstance(blocks[ib], (Heading, Paragraph)) or len(_text(blocks[ib])) > 200:
                    break
                text = (text + " " + (lead[ib][1] if ib in lead else _text(blocks[ib]))).strip()
                k1, k2 = _key(text), _key(e.title)
                if similar(text, e.title, 0.8) or (len(k2) >= 8 and k2 in k1 and len(k1) <= 1.4 * len(k2)):
                    score = (blocks[ia].page == page, -a)
                    if best is None or score > best[0]:
                        best = (score, a, b_)
                    break
        title = (f"{e.number}. " if e.kind == "chapter" and e.number else "") + e.title
        if e.kind == "part":
            title = f"{e.label} — {e.title}" if e.label else e.title
        if best is not None:
            _, a, b_ = best
            first = blocks[idxs[a]]
            body = re.sub(r"\s+", " ", " ".join(lead[i][1] if i in lead else _text(blocks[i])
                                                for i in idxs[a:b_ + 1])).strip()
            body = CHAPTER_RE.sub(lambda m: m.group(2), body) if e.kind == "chapter" else body
            body = re.sub(r"^[IVX\d]{1,4}\s*[.·-]\s+", "", body) if e.kind == "part" else body
            accents = lambda t: sum(1 for c in t if c.isalpha() and not c.isascii())  # noqa: E731
            if _key(body) == _key(e.title):  # the same letters: OCR drops accents more than it adds them
                better = accents(body) > accents(e.title)
            else:
                # fewer misreads; a margin, so that the heading's own occurrence ("Epiloguc" once) does not decide
                better = similar(body, e.title, 0.8) and plausible(body) > plausible(e.title) + 0.7
            if body and better:
                title = ((f"{e.number}. " if e.kind == "chapter" and e.number else "")
                         + (f"{e.label} — " if e.kind == "part" and e.label else "") + body)
            h = Heading(1, [Run(title)], first.page, first.y0, getattr(first, "size", 0.0), first.break_before)
            replaced[idxs[a]] = [h]
            if idxs[a] in lead:  # the authors printed in the same block as the title
                replaced[idxs[a]].append(Paragraph([Run(lead[idxs[a]][0])], "byline", first.page, first.y0))
            dropped.update(idxs[a + 1:b_ + 1])
            anchor_i = idxs[a]
            # a part divider: its label / number line ("3.", "Deuxième partie") above the title goes too
            for j in idxs[:a]:
                if blocks[j].page == first.page and len(_text(blocks[j])) <= 30 and (
                        PART_RE.match(_text(blocks[j])) or re.fullmatch(r"[\dIVX]{1,4}\s*[.·-]?", _text(blocks[j]))):
                    dropped.add(j)
        else:  # not found (a misread divider): the heading opens the page
            if not by_page.get(page):
                continue
            anchor_i = by_page[page][0]
            first = blocks[anchor_i]
            h = Heading(1, [Run(title)], page, max(0.0, first.y0 - 1), 0.0, "page")
            replaced[anchor_i] = [h] + replaced.get(anchor_i, [first])
        # names printed just above the title ("A | B", "A et B"): a byline even when the contents gives no author
        if not e.authors and best is not None and e.kind == "chapter":
            above = [j for j in idxs[:best[1]] if j not in dropped and blocks[j].page == blocks[anchor_i].page][-2:]
            for j in above:
                t = _text(blocks[j])
                parts = [x for x in re.split(r"\s*\|\s*", t) if x.strip()]
                if len(t) <= 160 and parts and all(_authors(x) for x in parts):
                    blk = blocks[j]
                    replaced[j] = [Paragraph([Run(", ".join(parts))], "byline", blk.page, blk.y0, blk.break_before)]
        # author lines near the title: a byline paragraph, not a heading
        if e.authors:
            for j in idxs:
                if j in dropped or j == anchor_i or blocks[j].page != blocks[anchor_i].page:
                    continue
                t = _text(blocks[j])
                if len(t) <= 120 and is_author(t):
                    blk = blocks[j]
                    by = Paragraph([Run(re.sub(r"\s*\|\s*", ", ", t))], "byline", blk.page, blk.y0, blk.break_before)
                    replaced[j] = [by]
        toc.append((e, h))
    out = []
    for i, b in enumerate(blocks):
        if i in dropped:
            continue
        out.extend(replaced.get(i, [b]))
    # a byline printed above the title moves below it
    for k in range(len(out) - 1):
        if isinstance(out[k], Paragraph) and out[k].kind == "byline" and isinstance(out[k + 1], Heading) \
                and any(h is out[k + 1] for _, h in toc):
            out[k], out[k + 1] = out[k + 1], out[k]
    # sections listed under an entry: its headings between it and the next entry
    pos = {id(h): i for i, h in enumerate(out) if isinstance(h, Heading)}
    starts = sorted(pos[id(h)] for _, h in toc if id(h) in pos) + [len(out)]
    result = []
    sec_level = max(e.level for e in entries) + 1  # below the split level: navigation entries, not documents
    gone: set[int] = set()
    for e, h in toc:
        i0 = pos.get(id(h))
        result.append((e.level, _text(h), h.page, h.y0))
        if i0 is None:
            continue
        i1 = next(s_ for s_ in starts if s_ > i0)
        k = i0 + 1
        rank = min((b.level for b in out[i0 + 1:i1] if isinstance(b, Heading)), default=2)  # with "Notes" & co.
        for s_title in e.sections:
            for j in range(k, i1):
                cand = [out[j]] + ([out[j + 1]] if j + 1 < i1 and isinstance(out[j + 1], Heading) else [])
                if not isinstance(cand[0], (Heading, Paragraph)) or getattr(cand[0], "kind", "") == "byline" \
                        or len(_text(cand[0])) > 200:
                    continue
                for n_ in (1, 2):  # a section title set on two lines
                    if n_ > len(cand):
                        break
                    text = " ".join(_text(c) for c in cand[:n_])
                    if similar(text, s_title, 0.8):
                        b = cand[0]
                        out[j] = Heading(rank, [Run(text)], b.page, b.y0, getattr(b, "size", 0.0), b.break_before)
                        if n_ == 2:
                            gone.add(id(out[j + 1]))
                        result.append((sec_level, text, b.page, b.y0))
                        k = j + n_
                        break
                else:
                    continue
                break
    return [b for b in out if id(b) not in gone], result
