"""Book metadata printed on the first pages, for PDFs whose metadata is empty (scans, most OCR'd books).

* Title: the largest type on the cover / title page, kept only when it is confirmed: printed on two of the first pages,
  or repeated as a running head through the book.
* Editors: the names under "Volume coordonné par", "Sous la direction de", "Edited by", ... (role `edt`).
* Publisher, year, ISBN: the copyright page ("© Éditions X, 2017", "ISBN : 978-..."); an ISBN is kept only when its
  check digit is right, and may come from the file name.
* File-name fallback without download-site prefixes and ISBN suffixes ("dokumen.pub_x-978...").
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .ir import PageData

FIRST_PAGES = 6
EDITORS_RE = re.compile(r"(?i)^\s*(?:volume |ouvrage |textes? )?(?:coordonn[ée]e?s? par|sous la direction de|"
                        r"dirig[ée]e?s? par|r[ée]unis? par|edited by|ed\. by|herausgegeben von)\s*:?\s*(.*)$")
NAME_RE = re.compile(r"^[A-ZÀ-Ý][\w'’.\-]*(?:[ -][A-ZÀ-Ýa-zà-ÿ][\w'’.\-]*){1,4}$")
ISBN_RE = re.compile(r"(?<![\d-])(97[89][-– ]?(?:\d[-– ]?){9}\d|(?:\d[-– ]?){9}[\dXx])(?![\d-])")
COPYRIGHT_RE = re.compile(r"©\s*(?:copyright\s*)?([^,©\d]{3,80}?)\s*,?\s*((?:1[5-9]|20)\d\d)\b")
SITE_PREFIX_RE = re.compile(r"(?i)^(?:dokumen\.pub|z-lib(?:\.org)?|libgen(?:\.\w+)?|ebin\.pub|vdoc\.pub|pdfcoffee(?:\.com)?)[_ -]+")


@dataclass
class BookMeta:
    title: str = ""
    editors: list[str] = field(default_factory=list)
    publisher: str = ""
    year: str = ""
    isbn: str = ""


def key(text: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", t)


def isbn_ok(digits: str) -> bool:
    d = digits.upper()
    if len(d) == 13 and d.isdigit():
        return sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d)) % 10 == 0
    if len(d) == 10 and d[:9].isdigit() and (d[9].isdigit() or d[9] == "X"):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d)) % 11 == 0
    return False


def find_isbn(text: str) -> str:
    for m in ISBN_RE.finditer(text):
        d = re.sub(r"[^\dXx]", "", m.group(1)).upper()
        if isbn_ok(d):
            return d
    return ""


def _title_block(page: PageData, body: float) -> tuple[str, float]:
    """The lines set in the page's largest type (>= 1.4 x body), in reading order, and that size."""
    lines = [l for l in page.lines if l.text.strip()]
    if not lines:
        return "", 0.0
    big = max(l.size for l in lines)
    if big < 1.4 * body:
        return "", 0.0
    top = sorted((l for l in lines if l.size >= 0.85 * big), key=lambda l: (l.y0, l.x0))
    return re.sub(r"\s+", " ", " ".join(l.text.strip() for l in top)).strip(), big


def _similar(a: str, b: str) -> bool:
    from .openings import similar
    return similar(a, b, 0.8)


def from_pages(pages: list[PageData], body: float, running: Counter | None = None) -> BookMeta:
    meta = BookMeta()
    first = pages[:FIRST_PAGES]
    sized = [(p.number, *_title_block(p, body)) for p in first]
    blocks = [(pno, t) for pno, t, _ in sized]
    best = None
    for pno, cand in blocks:
        if not (2 <= len(cand) <= 200) or not re.search(r"[^\W\d_]{2}", cand):
            continue
        score = sum(1 for q, other in blocks if q != pno and other and _similar(cand, other))
        k = key(cand)
        if running and len(k) >= 6 and any(n >= 3 and (k in r or (len(r) >= 6 and r in k)) for r, n in running.items()):
            score += 2
        if score >= 1 and (best is None or score > best[0]):
            best = (score, cand)
    if best:
        meta.title = best[1]
    else:  # printed once, but in display type on one of the first pages
        big = [(t, sz) for pno, t, sz in sized if pno <= 3 and sz >= 2.0 * body and 2 <= len(t) <= 200
               and re.search(r"[^\W\d_]{2}", t)]
        if big:
            meta.title = max(big, key=lambda x: x[1])[0]
    for p in first:
        lines = [l.text.strip() for l in sorted(p.lines, key=lambda l: (l.y0, l.x0)) if l.text.strip()]
        for i, t in enumerate(lines):
            m = EDITORS_RE.match(t)
            if not m:
                continue
            names = [n.strip() for n in re.split(r"\s*(?:,|;| et | and |\|)\s*", m.group(1)) if n.strip()]
            for nxt in lines[i + 1:]:
                if not NAME_RE.match(nxt) or len(nxt) > 60:
                    break
                names.append(nxt)
            meta.editors = [n for n in names if NAME_RE.match(n)][:12]
            break
        if meta.editors:
            break
    text = "\n".join(l.text for p in pages[:8] + pages[-3:] for l in p.lines)
    meta.isbn = find_isbn(text)
    m = COPYRIGHT_RE.search(text)
    if m:
        pub = m.group(1).strip(" .,:;-")
        if re.search(r"[^\W\d_]{3}", pub) and not re.match(r"(?i)^(tous droits|all rights)", pub):
            meta.publisher = pub
        meta.year = m.group(2)
    return meta


FILE_ISBN_RE = re.compile(r"(?<!\d)(?:97[89](?:[-_ ]?\d){10}|(?:\d[-_ ]?){9}[\dXx])(?![\dXx])")


def title_from_filename(stem: str) -> str:
    """'dokumen.pub_histoire-du-travail-9780306406157' -> 'histoire du travail'."""
    s = SITE_PREFIX_RE.sub("", stem)
    s = FILE_ISBN_RE.sub(" ", s)
    s = re.sub(r"[_\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def isbn_from_filename(stem: str) -> str:
    for m in FILE_ISBN_RE.finditer(stem):
        d = re.sub(r"[^\dXx]", "", m.group(0)).upper()
        if isbn_ok(d):
            return d
    return ""
