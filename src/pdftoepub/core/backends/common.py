"""Backend-independent helpers shared by all PDF backends (no PDF library is imported here)."""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field

from ..ir import ImageAsset, ImageItem, Line, Span, TableItem

MAX_IMAGE_DIM = 1600
MAX_RENDER_PIXELS = 50_000_000  # page renders (OCR 300 dpi, figures 200 dpi, cover) never exceed this many pixels
MAX_DECODE_PIXELS = 12_000_000  # embedded bitmaps larger than this are not decoded at their declared size


def limit_pillow() -> None:
    """Set Pillow's decompression-bomb limit explicitly instead of relying on the library default: Image.open() of an
    image above 2 x MAX_IMAGE_PIXELS (= MAX_RENDER_PIXELS) raises DecompressionBombError, which callers turn into a
    warning."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_RENDER_PIXELS // 2


def clamp_scale(w_pt: float, h_pt: float, dpi: float, max_pixels: int = MAX_RENDER_PIXELS) -> tuple[float, bool]:
    """Render scale for a w x h pt page at `dpi`, reduced so the bitmap has at most `max_pixels` (a MediaBox can be
    200 x 200 inches: 300 dpi would be 3.6 gigapixels). Returns (scale, clamped)."""
    scale = dpi / 72.0
    px = max(w_pt, 1.0) * max(h_pt, 1.0) * scale * scale
    if px <= max_pixels:
        return scale, False
    return scale * (max_pixels / px) ** 0.5 * 0.995, True  # margin: pixel sizes are rounded up
BOLD_RE = re.compile(r"(bold|black|heavy|semibold|demi|extrabold|ultra)|[-,]bd\b|[-,]b$", re.I)
ITALIC_RE = re.compile(r"(italic|oblique|slanted|kursiv)|[-,]it\b|[-,]i$", re.I)
MONO_RE = re.compile(
    r"mono|courier|consolas|menlo|monaco|typewriter|lucida ?console|fixedsys|inconsolata|cousine|fira ?code|source ?code|code ?pro"
    r"|cascadia|iosevka|jetbrains|anonymous ?pro|ubuntu ?mono|cmtt|nimbusmon|andale|(?:^|[-_, ])(?:code|hack|terminal|fixed|consolas)(?:$|[-_, ])",
    re.I,
)
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}
_CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")  # + lone surrogates (broken ToUnicode)
CID_RE = re.compile(r"\(cid:\d+\)")


@dataclass
class ImageStore:
    """Deduplicating store of processed images shared by all pages."""

    assets: dict[str, ImageAsset] = field(default_factory=dict)
    by_key: dict[object, str | None] = field(default_factory=dict)
    by_hash: dict[str, str] = field(default_factory=dict)

    def add(self, data: bytes, media_type: str, w: int, h: int) -> str:
        digest = hashlib.sha1(data).hexdigest()[:16]
        if digest in self.by_hash:
            return self.by_hash[digest]
        iid = f"img{len(self.assets) + 1:04d}"
        self.assets[iid] = ImageAsset(data, media_type, w, h)
        self.by_hash[digest] = iid
        return iid


def clean_text(t: str) -> str:
    for k, v in _LIGATURES.items():
        t = t.replace(k, v)
    t = _CTRL_RE.sub("", t)
    return t.replace("\u00a0", " ").replace("\u2028", " ").replace("\u2029", " ")


_PUA_RE = re.compile(r"[-]")
_LIBERTINE_RE = re.compile(r"libertine|biolinum", re.I)


# Adobe Symbol pieces of tall delimiters (top / middle / extension / bottom) used by typeset math: one run -> one char
_DELIM_PIECES = {**{c: "(" for c in range(0xF8EB, 0xF8EE)}, **{c: "[" for c in range(0xF8EE, 0xF8F1)},
                 **{c: "{" for c in range(0xF8F1, 0xF8F5)}, 0xF8F5: "", **{c: ")" for c in range(0xF8F6, 0xF8F9)},
                 **{c: "]" for c in range(0xF8F9, 0xF8FC)}, **{c: "}" for c in range(0xF8FC, 0xF8FF)},
                 0xF8E5: "", 0xF8E6: "", 0xF8E7: ""}
_DELIM_RUN_RE = re.compile("[--][--\\s]*")


def _delims(m) -> str:
    out = ""
    for ch in m.group(0):
        d = _DELIM_PIECES.get(ord(ch), "") if not ch.isspace() else ""
        if d and not out.endswith(d):
            out += d
    trail = " " if m.group(0)[-1].isspace() else ""
    return out + trail


def map_pua(t: str, font: str = "") -> str:
    """Private-use code points that some fonts' ToUnicode maps give for small caps, mapped back to letters.

    Adobe "corporate use" small caps / old-style figures (U+F721-U+F7FE = ASCII/Latin-1 + 0xF700) are a de-facto
    standard; Linux Libertine / Biolinum put small caps a-z at U+E051-U+E06A. Other layouts are left as they are.
    """
    if not _PUA_RE.search(t):
        return t
    t = _DELIM_RUN_RE.sub(_delims, t)
    lib = bool(_LIBERTINE_RE.search(font))

    def sub(m):
        cp = ord(m.group(0))
        if 0xF721 <= cp <= 0xF7FE:
            return chr(cp - 0xF700)
        if lib and 0xE051 <= cp <= 0xE06A:
            return chr(cp - 0xE051 + ord("a"))
        return m.group(0)

    return _PUA_RE.sub(sub, t)


# Spacing accents drawn as separate glyphs before the letter (old TeX OT1 fonts): "esp`ece" -> "espèce"
_SPACING_ACCENTS = {"`": "̀", "ˋ": "̀", "´": "́", "ˊ": "́", "ˆ": "̂",
                    "˜": "̃", "¯": "̄", "˘": "̆", "˙": "̇", "¨": "̈",
                    "˚": "̊", "˝": "̋", "ˇ": "̌", "¸": "̧"}
_ACCENT_RE = re.compile("([" + "".join(_SPACING_ACCENTS) + "])([A-Za-zıȷ])")


def fix_spacing_accents(t: str) -> str:
    if not any(a in t for a in _SPACING_ACCENTS):
        return t

    def sub(m):
        acc, letter = m.group(1), m.group(2)
        if acc == "`" and letter not in "aeiouAEIOU":
            return m.group(0)  # a backtick before a consonant is a quote / code, not a grave accent
        base = {"ı": "i", "ȷ": "j"}.get(letter, letter)
        out = unicodedata.normalize("NFC", base + _SPACING_ACCENTS[acc])
        return out if len(out) == 1 else m.group(0)

    return _ACCENT_RE.sub(sub, t)


# math fonts: TeX (CM / AMS / Euler / txfonts / newtx / Latin Modern Math), STIX, Cambria Math, MathJax, MathTime,
# Adobe Symbol. Body digits and operators often come from the text font, so this flags only part of a formula.
MATH_FONT_RE = re.compile(
    r"^(cmmi|cmbsy|cmsy|cmex|cmmib|msam|msbm|eufm|eufb|eusm|eusb|eurm|eurb|rsfs|wasy|esint|stmary|txsy|txex|txmi|"
    r"pxsy|pxex|pxmi|ntxmi|ntxsy|ntxexx|zxmi|rtxmi|lmmath|latinmodernmath|stix\w*math|stixmath|cambriamath|mathjax|"
    r"xits\w*math|asanamath|mtsy|mtex|mtmi|tex-cm(ex|sy|mi)|symbol(mt)?$)", re.I)


def is_math_font(font: str) -> bool:
    name = re.sub(r"[\s_-]", "", font.split("+")[-1])
    return bool(MATH_FONT_RE.match(name))


def is_ocr_font(font: str) -> bool:
    """Invisible text layers written by Tesseract (Internet Archive, OCRmyPDF) use GlyphLessFont, flagged fixed-pitch."""
    return "glyphless" in font.lower()


def style_from_name(font: str, flags: int = 0) -> tuple[bool, bool, bool]:
    """(bold, italic, mono) from a font name and optional MuPDF-style flags."""
    name = font.split("+")[-1]
    if is_ocr_font(name):
        return False, False, False
    bold = bool(flags & 16) or bool(BOLD_RE.search(name))
    italic = bool(flags & 2) or bool(ITALIC_RE.search(name))
    mono = bool(flags & 8) or bool(MONO_RE.search(name))
    return bold, italic, mono

def merge_row_fragments(lines: list[Line], max_gap: float = 0.45) -> list[Line]:
    """Glue fragments of one visual line that the PDF stored as separate text lines (e.g. split by font change).
    `max_gap` (em) is raised for OCR layers, whose words are placed one by one across justified gaps."""
    if len(lines) < 2:
        return lines
    lines = sorted(lines, key=lambda l: (round(l.y0, 0), l.x0))
    out: list[Line] = []
    used = [False] * len(lines)
    for i, a in enumerate(lines):
        if used[i]:
            continue
        cur = a
        for j in range(i + 1, min(i + 12, len(lines))):
            b = lines[j]
            if used[j]:
                continue
            ov = min(cur.y1, b.y1) - max(cur.y0, b.y0)
            if ov < 0.6 * min(cur.height, b.height):
                continue
            gap = b.x0 - cur.x1
            sz = max(cur.size, b.size, 1.0)
            if -2 <= gap <= max_gap * sz:
                spans = list(cur.spans)
                if gap > 0.12 * sz and not cur.text.endswith(" ") and not b.text.startswith(" "):
                    spans.append(Span(" ", spans[-1].size if spans else sz))
                spans += b.spans
                cur = Line(spans, (min(cur.x0, b.x0), min(cur.y0, b.y0), max(cur.x1, b.x1), max(cur.y1, b.y1)), cur.page)
                used[j] = True
        out.append(cur)
    return out


def encode_image(img, prefer_jpeg: bool) -> tuple[bytes, str, int, int]:
    from PIL import Image

    if max(img.size) > MAX_IMAGE_DIM:
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)
    has_alpha = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
    if img.mode == "CMYK" or img.mode.startswith("I") or img.mode == "F":
        img = img.convert("RGB")
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        has_alpha = img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250
    buf = io.BytesIO()
    if has_alpha:
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", img.width, img.height
    if img.mode in ("RGBA", "LA"):
        img = img.convert("RGB") if img.mode == "RGBA" else img.convert("L")
    if prefer_jpeg and img.mode in ("RGB", "L"):
        img.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg", img.width, img.height
    img.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    if len(data) > 600_000 and img.mode in ("RGB", "L"):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg", img.width, img.height
    return data, "image/png", img.width, img.height


def overlap(a, b) -> float:
    """Fraction of the smaller rect covered by the intersection."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    sm = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / sm if sm > 0 else 0.0


def center_in(line: Line, rect) -> bool:
    """rect: (x0, y0, x1, y1)"""
    cx, cy = (line.x0 + line.x1) / 2, (line.y0 + line.y1) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def page_text_quality(lines: list[Line], bad_chars: int = 0) -> tuple[int, bool]:
    """Return (non-space char count, is_garbage). `bad_chars` counts unmapped glyphs removed by the backend."""
    text = "".join(l.text for l in lines)
    chars = [c for c in text if not c.isspace()]
    n = len(chars)
    if n + bad_chars < 25:
        return n, False
    bad = bad_chars + sum(1 for c in chars if c == "\ufffd" or 0xE000 <= ord(c) <= 0xF8FF)
    alpha = sum(1 for c in chars if c.isalpha())
    garbage = bad / (n + bad_chars) > 0.25 or (n >= 120 and alpha / n < 0.35)
    return n, garbage


def cell_text(lines: list[Line], rect) -> str:
    """Text of all spans whose centre falls in rect=(x0,y0,x1,y1), in reading order."""
    parts: list[tuple[float, float, str]] = []
    for l in lines:
        for s in l.spans:
            if not s.text.strip():
                continue
            cx, cy = (s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2
            if rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1:
                parts.append((round(l.y0 / 3), s.bbox[0], s.text))
    parts.sort()
    return re.sub(r"\s+", " ", " ".join(p[2].strip() for p in parts)).strip()


def table_from_rows(rows: list[list[str]], bbox, pno: int, lines: list[Line], page_area: float):
    """Validate extracted table rows; returns (TableItem | None, indices of consumed lines)."""
    rows = [r for r in rows if any(r)]
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return None, set()
    if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 0.92 * page_area:
        return None, set()
    cells_n = sum(len(r) for r in rows)
    filled = sum(1 for r in rows for c in r if c)
    if filled < 0.5 * cells_n:
        return None, set()
    inside = [i for i, l in enumerate(lines) if center_in(l, bbox)]
    if not inside:
        return None, set()
    row_h = (bbox[3] - bbox[1]) / len(rows)
    first = [lines[i] for i in inside if lines[i].y0 < bbox[1] + row_h]
    header = bool(first) and all(l.bold_ratio > 0.6 for l in first)
    return TableItem(tuple(bbox), rows, pno, header), set(inside)


# ---------------------------------------------------------------------------
# Ruled tables from line segments (used by backends without a table finder)
# ---------------------------------------------------------------------------
def _merge_positions(vals: list[float], tol: float = 2.5) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def ruled_tables_from_segments(hsegs, vsegs, lines: list[Line], pno: int, page_w: float, page_h: float):
    """hsegs: [(x0, x1, y)], vsegs: [(x, y0, y1)] in top-left page coordinates. Complete grids only."""
    hs = [s for s in hsegs if s[1] - s[0] >= 8]
    vs = [s for s in vsegs if s[2] - s[1] >= 8]
    if len(hs) < 3 or len(vs) < 3:
        return [], lines
    # cluster segments that touch (union-find over a coarse proximity test)
    segs = [("h", s, (s[0], s[2], s[1], s[2])) for s in hs] + [("v", s, (s[0], s[1], s[0], s[2])) for s in vs]
    parent = list(range(len(segs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tol = 3.0
    for i in range(len(segs)):
        bi = segs[i][2]
        for j in range(i + 1, len(segs)):
            bj = segs[j][2]
            if bi[0] - tol <= bj[2] and bj[0] - tol <= bi[2] and bi[1] - tol <= bj[3] and bj[1] - tol <= bi[3]:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i, sg in enumerate(segs):
        groups.setdefault(find(i), []).append(sg)
    tables = []
    taken: set[int] = set()
    page_area = page_w * page_h
    for grp in groups.values():
        gh = [g[1] for g in grp if g[0] == "h"]
        gv = [g[1] for g in grp if g[0] == "v"]
        ys = _merge_positions([s[2] for s in gh])
        xs = _merge_positions([s[0] for s in gv])
        if len(ys) < 3 or len(xs) < 3:
            continue
        x_lo, x_hi, y_lo, y_hi = xs[0], xs[-1], ys[0], ys[-1]
        rows = []
        for ri in range(len(ys) - 1):
            row = []
            for ci in range(len(xs) - 1):
                row.append(cell_text(lines, (xs[ci], ys[ri], xs[ci + 1], ys[ri + 1])))
            rows.append(row)
        item, consumed = table_from_rows(rows, (x_lo, y_lo, x_hi, y_hi), pno, lines, page_area)
        if item is not None and not (consumed & taken):
            tables.append(item)
            taken |= consumed
    return tables, [l for i, l in enumerate(lines) if i not in taken]


# ---------------------------------------------------------------------------
# Vector figures
# ---------------------------------------------------------------------------
def cluster_rects(rects: list[tuple[float, float, float, float]], gap: float = 6.0) -> list[tuple[float, float, float, float]]:
    """Merge rectangles closer than `gap` into clusters (single-link)."""
    boxes = [list(r) for r in rects]
    merged = True
    while merged and len(boxes) > 1:
        merged = False
        out: list[list[float]] = []
        for b in boxes:
            for o in out:
                if b[0] - gap <= o[2] and o[0] - gap <= b[2] and b[1] - gap <= o[3] and o[1] - gap <= b[3]:
                    o[0], o[1], o[2], o[3] = min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def figures_from_clusters(clusters, pno: int, page_w: float, page_h: float, lines: list[Line],
                          images: list[ImageItem], tables: list[TableItem], render, store: ImageStore,
                          shapes: list[tuple[float, float, float, float]] | None = None):
    """Rasterise clusters of vector drawings with little text inside; drop the text lines they contain.

    `render(rect) -> ImageAsset | None` renders a page region. `shapes` (the drawing rectangles the clusters were
    built from) lets a shaded / framed text box (code listing, callout) be told apart from a chart: a few shapes,
    one of them covering the whole cluster, with text inside, stays text.
    """
    page_area = page_w * page_h
    figures: list[ImageItem] = []
    removed: set[int] = set()
    for rect in clusters:
        x0, y0, x1, y1 = max(rect[0], 0), max(rect[1], 0), min(rect[2], page_w), min(rect[3], page_h)
        w, h = x1 - x0, y1 - y0
        if w < 50 or h < 40 or w * h < 3500 or w * h > 0.8 * page_area:
            continue
        if w > 12 * h or h > 12 * w:
            continue
        box = (x0, y0, x1, y1)
        if any(overlap(box, t.bbox) > 0.3 for t in tables) or any(overlap(box, im.bbox) > 0.5 for im in images):
            continue
        inside = [i for i, l in enumerate(lines) if center_in(l, box)]
        if len(inside) > 14 or sum(len(lines[i].text) for i in inside) > 450:
            continue
        if shapes is not None and inside and _is_text_box(box, shapes, [lines[i] for i in inside]):
            continue
        pad = (max(x0 - 3, 0), max(y0 - 3, 0), min(x1 + 3, page_w), min(y1 + 3, page_h))
        try:
            asset = render(pad)
        except Exception:  # noqa: BLE001
            continue
        if asset is None:
            continue
        iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
        figures.append(ImageItem(pad, iid, pno, "figure"))
        removed.update(inside)
    return figures, [l for i, l in enumerate(lines) if i not in removed]


def _is_text_box(box, shapes, inside: list[Line]) -> bool:
    x0, y0, x1, y1 = box
    area = max((x1 - x0) * (y1 - y0), 1.0)
    members = [s for s in shapes if x0 - 1 <= (s[0] + s[2]) / 2 <= x1 + 1 and y0 - 1 <= (s[1] + s[3]) / 2 <= y1 + 1]
    if not members or len(members) > 6:
        return False
    big = max((s[2] - s[0]) * (s[3] - s[1]) for s in members)
    text_lines = [l for l in inside if len(l.text.strip()) >= 3]
    return big >= 0.85 * area and len(text_lines) >= 1


def asset_from_pil(img, prefer_jpeg: bool = False) -> ImageAsset:
    data, mt, w, h = encode_image(img, prefer_jpeg)
    return ImageAsset(data, mt, w, h)


def cover_from_pil(img) -> ImageAsset | None:
    """JPEG snapshot used only as the EPUB cover image."""
    from PIL import Image

    try:
        img = img.convert("RGB")
        if max(img.size) > 1400:
            img.thumbnail((1400, 1400), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82, optimize=True)
        return ImageAsset(buf.getvalue(), "image/jpeg", img.width, img.height)
    except Exception:  # noqa: BLE001
        return None
