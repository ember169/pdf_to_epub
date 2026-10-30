"""The cover: which page, which picture, and the cover page's own text.

* Page: page 1, unless it is blank (specks only), then the first page among the first 3 that is not; a weak page 1
  (a bookplate or a stamp: little ink, no display type) gives way to page 2 or 3 only when that page clearly is a cover
  (a full-bleed picture or display type). When unsure, page 1.
* Picture: the page's one full-page raster image as embedded (re-encoded only when it is not a JPEG, too large or too
  heavy) when no text is drawn over it (a title set over a framed background needs the rendering), otherwise the page
  rendered 1600 px high; JPEG quality 85, lowered until it fits in 1 MB; grey stays grey.
* Text: a cover page whose text is only the title / creators / publisher / year (now in the metadata) is not repeated
  at the start of the book; any other text (an abstract on page 1 of a paper) stays.
"""
from __future__ import annotations

import io
import re

from .backends.common import MAX_IMAGE_DIM
from .ir import Heading, ImageAsset, PageData, Paragraph

HEIGHT = 1600  # px
MAX_BYTES = 1_000_000
BLANK = 0.004  # share of inked pixels: a blank page with specks
WEAK = 0.03  # a bookplate / stamp page
STRONG = 0.25  # a full-bleed picture


def _ink(thumb) -> float:
    g = thumb.convert("L")
    return sum(g.histogram()[:200]) / max(1, g.width * g.height)


def choose(pages: list[PageData], thumbs: dict[int, object], body: float) -> int | None:
    """The cover page number among the first 3, or None (all blank)."""
    first = [p for p in pages[:3] if p.number in thumbs]
    if not first:
        return None
    ink = {p.number: _ink(thumbs[p.number]) for p in first}
    display = {p.number: any(l.size >= 2.0 * body and l.text.strip() for l in p.lines) for p in first}
    nonblank = [p.number for p in first if ink[p.number] >= BLANK]
    if not nonblank:
        return None
    one = first[0].number
    if one not in nonblank:
        return nonblank[0]
    if ink[one] < WEAK and not display[one]:
        strong = [n for n in nonblank[1:] if ink[n] >= STRONG or display[n]]
        if strong:
            return strong[0]
    return one


def _jpeg(img) -> ImageAsset | None:
    from PIL import Image, ImageChops, ImageStat

    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    if img.mode == "RGB":  # a scan in grey stays grey
        r, g, b = img.split()
        if max(ImageStat.Stat(ImageChops.difference(r, g)).mean[0], ImageStat.Stat(ImageChops.difference(g, b)).mean[0]) < 1.5:
            img = img.convert("L")
    if img.height > HEIGHT or img.width > MAX_IMAGE_DIM:
        img.thumbnail((MAX_IMAGE_DIM, HEIGHT), Image.LANCZOS)
    for q in (85, 78, 70, 62, 55):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    return ImageAsset(buf.getvalue(), "image/jpeg", img.width, img.height)


def picture(page: PageData, store, render) -> ImageAsset | None:
    """The cover picture of `page`. `render(dpi)` renders the page (PIL image)."""
    from PIL import Image

    full = [iid for iid in page.scan_ids if iid in store.assets]
    visible_text = bool(page.lines) and not (page.ocr_layer or page.source == "ocr")
    if len(full) == 1 and not visible_text:  # one picture covering the page, no text drawn over it: as embedded
        a = store.assets[full[0]]
        if a.media_type == "image/jpeg" and len(a.data) <= MAX_BYTES and a.height >= 800 and a.height <= HEIGHT:
            return a
        try:
            return _jpeg(Image.open(io.BytesIO(a.data)))
        except Exception:  # noqa: BLE001 - fall back to a rendering
            pass
    try:
        return _jpeg(render(HEIGHT * 72.0 / max(page.height, 1.0)))
    except Exception:  # noqa: BLE001
        return None


def _words(text: str) -> list[str]:
    from .openings import _key  # accents and case folded

    return [_key(w) for w in re.findall(r"[^\W\d_]{3,}", text) if _key(w)]


def drop_cover_text(blocks: list, page: int, known: list[str]) -> tuple[list, int]:
    """Without the cover page's blocks when all their words are in `known` (title, creators, publisher, year).
    Returns (blocks, words removed)."""
    vocab = {w for k in known if k for w in _words(k)}
    on_page = [b for b in blocks if getattr(b, "page", 0) == page]
    if not on_page or not vocab:
        return blocks, 0
    words = []
    for b in on_page:
        if not isinstance(b, (Paragraph, Heading)):
            return blocks, 0  # a table, a figure, notes: the page holds more than its title
        words += _words("".join(r.text for r in b.runs))
    if not words or len(words) > 40 or any(w not in vocab for w in words):
        return blocks, 0
    gone = {id(b) for b in on_page}
    removed = sum(len(re.findall(r"\S+", "".join(r.text for r in b.runs))) for b in on_page)
    return [b for b in blocks if id(b) not in gone], removed
