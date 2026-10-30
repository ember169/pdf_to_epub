"""Default MIT-compatible backend: pdfminer.six (text, fonts, geometry, outline, links) + pypdfium2 (rendering, images).

pdfminer has no raster support, so embedded images, vector-figure rasterisation, OCR/cover rendering come from pypdfium2
(Apache-2.0 / BSD-3). If pypdfium2 cannot open a file the text pipeline still works; images are then skipped with a warning.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from contextlib import suppress

from pdfminer.high_level import extract_pages  # noqa: F401  (kept for debugging / parity checks)
from pdfminer.layout import (LAParams, LTAnno, LTChar, LTCurve, LTFigure, LTImage, LTLine, LTRect, LTTextLine,
                             LTTextLineHorizontal)
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdocument import PDFDocument as MinerDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from ...api import ConversionError
from ..ir import ImageItem, Line, PageData, Span
from ..tables import detect_text_tables
from .base import PDFIUM_LOCK, PdfBackend, PdfDocument
from .common import MAX_DECODE_PIXELS as _MAX_DECODE
from .common import (CID_RE, MAX_IMAGE_DIM, ImageStore, asset_from_pil, clamp_scale, clean_text, cluster_rects,
                     figures_from_clusters, fix_spacing_accents, is_ocr_font, map_pua, merge_row_fragments,
                     ruled_tables_from_segments, style_from_name)

logging.getLogger("pdfminer").setLevel(logging.ERROR)
MAX_CLUSTER_RECTS = 1500
MAX_DECODE_PIXELS = _MAX_DECODE  # larger embedded bitmaps are rendered at output size instead of decoded in full
MAX_IMAGES_PER_PAGE = 300
# Per-page guards: pdfminer is pure Python, so a pathological page (huge content stream, 10^6 glyphs or paths) could
# otherwise stall a conversion for a very long time. Over budget, the page is kept as a picture with a warning.
PAGE_TIMEOUT = float(os.environ.get("PDFTOEPUB_PAGE_TIMEOUT", "60"))  # seconds of content-stream interpretation
MAX_PAGE_CHARS = 150_000  # a dense two-column page has ~10k
MAX_PAGE_PATHS = 50_000  # further vector paths are ignored (the page is still rendered by pdfium for figures)


class PageTooComplex(Exception):
    pass


class _Device(PDFPageAggregator):
    """Aggregator that also remembers font descriptor flags (bold / italic / fixed pitch) per font name,
    and enforces the per-page budget."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fontinfo: dict[str, tuple[int, float, float]] = {}
        self.deadline = float("inf")
        self.nchars = self.npaths = 0

    def begin_page(self, page, ctm):
        self.deadline = time.monotonic() + PAGE_TIMEOUT
        self.nchars = self.npaths = 0
        super().begin_page(page, ctm)

    def check_budget(self) -> None:
        if time.monotonic() > self.deadline:
            raise PageTooComplex(f"took more than {PAGE_TIMEOUT:g} s")

    def paint_path(self, gstate, stroke, fill, evenodd, path):
        self.npaths += 1
        if not self.npaths & 1023:
            self.check_budget()
        if self.npaths <= MAX_PAGE_PATHS:
            super().paint_path(gstate, stroke, fill, evenodd, path)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate):
        self.nchars += 1
        if self.nchars > MAX_PAGE_CHARS:
            raise PageTooComplex(f"has more than {MAX_PAGE_CHARS} characters")
        if not self.nchars & 1023:
            self.check_budget()
        name = getattr(font, "fontname", None)
        if name is not None and name not in self.fontinfo:
            flags, weight, angle = 0, 0.0, 0.0
            with suppress(Exception):
                d = getattr(font, "descriptor", None) or {}
                flags = int(resolve1(d.get("Flags", 0)) or 0)
                weight = float(resolve1(d.get("FontWeight", 0)) or 0)
                angle = float(resolve1(d.get("ItalicAngle", 0)) or 0)
            self.fontinfo[name] = (flags, weight, angle)
        adv = super().render_char(matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate)
        with suppress(Exception):  # the text rise (super/subscripts) is part of the bbox but not of `matrix`
            self.cur_item._objs[-1].baseline_y = matrix[5] + matrix[3] * rise
        return adv


def _copy_and_free(bm):
    """PIL copy of a pdfium bitmap, then free the bitmap now (caller holds PDFIUM_LOCK) rather than leaving it to a GC
    finaliser that could run on another thread. to_pil() shares the bitmap's buffer, so the copy comes first; that makes
    the explicit close safe, and `warn_on_close = False` (pypdfium2 >= 5.14) tells pypdfium2 so instead of logging
    "Explicitly closing <PdfBitmap ... @ foreign>. This is a potentially unsafe operation!" to the console."""
    pil = bm.to_pil()
    img = pil.copy()
    del pil
    bm.warn_on_close = False
    bm.close()
    return img


def _horizontal(c) -> bool:
    """Upright, left-to-right glyph (rotated axis labels and margin text are dropped, as on the PyMuPDF backend)."""
    a, b, cc, d = c.matrix[:4]
    return a > 0 and d > 0 and abs(b) <= 0.2 * a and abs(cc) <= 0.4 * d


class _Interpreter(PDFPageInterpreter):
    """Checks the page budget while parsing operands too (content streams made of paths or garbage, no glyphs)."""

    _ops = 0

    def push(self, obj) -> None:
        self._ops += 1
        if not self._ops & 4095:
            self.device.check_budget()
        self.argstack.append(obj)


class PdfMinerBackend(PdfBackend):
    name = "pdfminer"

    @classmethod
    def available(cls) -> bool:
        return True

    def open(self, path) -> "PdfMinerDocument":
        try:
            fp = open(path, "rb")
        except OSError as exc:
            raise ConversionError("The uploaded file could not be read.") from exc
        try:
            parser = PDFParser(fp)
            doc = MinerDocument(parser, password="")
            pages = list(PDFPage.create_pages(doc))
        except Exception as exc:  # noqa: BLE001
            fp.close()
            name = type(exc).__name__
            if "Password" in name or "Encryption" in name:
                raise ConversionError("This PDF is password-protected; remove the password and try again.") from exc
            raise ConversionError("This file could not be read as a PDF.") from exc
        if not pages:
            fp.close()
            raise ConversionError("This PDF has no pages.")
        return PdfMinerDocument(fp, doc, pages, path)


class PdfMinerDocument(PdfDocument):
    name = "pdfminer"

    def __init__(self, fp, doc, pages, path):
        self.fp, self.doc, self.pages = fp, doc, pages
        self.orig_rotate = [pg.rotate % 360 for pg in pages]
        for pg in pages:  # analyse the page in its native orientation (as PyMuPDF does); rendering still honours /Rotate
            pg.rotate = 0
        self.page_count = len(pages)
        self.rsrc = PDFResourceManager()
        self.device = _Device(self.rsrc, laparams=LAParams(
            line_overlap=0.5, char_margin=1.5, line_margin=0.5, word_margin=0.1, boxes_flow=None,
            detect_vertical=False, all_texts=True))
        self.interp = _Interpreter(self.rsrc, self.device)
        self.page_index = {p.pageid: i + 1 for i, p in enumerate(pages)}
        self.adv_stats: dict[str, list] = {}  # fontname -> [narrow advance sum, n, wide advance sum, n]
        self.pdfium = None
        self._render_cache: tuple | None = None
        self.warnings: list[str] = []
        try:
            import pypdfium2 as pdfium

            with PDFIUM_LOCK:
                self.pdfium = pdfium.PdfDocument(str(path))
        except Exception:  # noqa: BLE001
            self.pdfium = None

    # ------------------------------------------------------------------ metadata / outline
    def metadata(self) -> dict[str, str]:
        out = {"title": "", "author": ""}
        with suppress(Exception):
            info = resolve1(self.doc.info[0]) if self.doc.info else {}
            for k in ("title", "author"):
                v = resolve1(info.get(k.capitalize()))
                if isinstance(v, bytes):
                    out[k] = decode_text(v).strip()
                elif isinstance(v, str):
                    out[k] = v.strip()
        return out

    def _page_dims(self, page) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = page.mediabox
        w, h = abs(x1 - x0), abs(y1 - y0)
        if page.rotate % 180:
            w, h = h, w
        return w, h, min(x0, x1), min(y0, y1)

    def _resolve_dest(self, dest):
        """Return (page 1-based, y_top_left) or None."""
        dest = resolve1(dest)
        if isinstance(dest, PSLiteral):
            dest = dest.name
        if isinstance(dest, (bytes, str)):
            try:
                dest = resolve1(self.doc.get_dest(dest))
            except Exception:  # noqa: BLE001
                return None
        if isinstance(dest, dict):
            dest = resolve1(dest.get("D"))
        if not isinstance(dest, list) or not dest:
            return None
        ref = dest[0]
        if isinstance(ref, int):
            page_no = ref + 1
        else:
            page_no = self.page_index.get(getattr(ref, "objid", None))
        if not page_no or page_no > self.page_count:
            return None
        y = 0.0
        kind = resolve1(dest[1]).name if len(dest) > 1 and isinstance(resolve1(dest[1]), PSLiteral) else ""
        top = None
        if kind == "XYZ" and len(dest) > 3:
            top = resolve1(dest[3])
        elif kind in ("FitH", "FitBH") and len(dest) > 2:
            top = resolve1(dest[2])
        if isinstance(top, (int, float)):
            page = self.pages[page_no - 1]
            if page.rotate % 360 == 0:
                _, h, _, by0 = self._page_dims(page)
                y = max(h - (float(top) - by0), 0.0)
        return page_no, y

    def toc(self):
        out = []
        try:
            outlines = list(self.doc.get_outlines())
        except Exception:  # noqa: BLE001 - PDFNoOutlines and malformed outlines
            return out
        for level, title, dest, action, _se in outlines:
            try:
                if isinstance(title, bytes):
                    title = decode_text(title)
                target = None
                if dest is not None:
                    target = self._resolve_dest(dest)
                if target is None and action is not None:
                    a = resolve1(action)
                    if isinstance(a, dict) and a.get("D") is not None:
                        target = self._resolve_dest(a.get("D"))
                if target:
                    out.append((int(level), str(title).strip(), target[0], target[1]))
            except Exception:  # noqa: BLE001
                continue
        return out

    # ------------------------------------------------------------------ rendering
    def _render_full(self, pno: int, dpi: float, gray: bool, native: bool = False):
        """native=True undoes the page's /Rotate so the image matches the (unrotated) analysis coordinates."""
        if self.pdfium is None:
            raise RuntimeError("pypdfium2 could not open this PDF")
        key = (pno, round(dpi), gray, native)
        if self._render_cache and self._render_cache[0] == key:
            self.last_scale = self._render_cache[2]
            return self._render_cache[1]
        extra = (-self.orig_rotate[pno - 1]) % 360 if native else 0
        w, h, _, _ = self._page_dims(self.pages[pno - 1])
        scale, clamped = clamp_scale(w, h, dpi)
        if clamped:
            self.note(f"Page {pno} is very large; it was rendered at reduced resolution.")
        with PDFIUM_LOCK:
            page = self.pdfium[pno - 1]
            try:
                bm = page.render(scale=scale, grayscale=gray, rotation=extra)
                img = _copy_and_free(bm)
            finally:
                page.close()
        if gray and img.mode != "L":
            img = img.convert("L")
        self._render_cache = (key, img, scale)
        self.last_scale = scale
        return img

    def render_page(self, pno: int, dpi: float, gray: bool = False):
        img = self._render_full(pno, dpi, gray)
        self._render_cache = None  # large OCR renders are not kept
        return img

    def _render_region(self, pno: int, rect, dpi: int = 200):
        img = self._render_full(pno, dpi, False, native=True)
        s = self.last_scale  # the scale actually used (clamped for huge pages)
        box = (int(rect[0] * s), int(rect[1] * s), int(rect[2] * s), int(rect[3] * s))
        box = (max(box[0], 0), max(box[1], 0), min(box[2], img.width), min(box[3], img.height))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            return None
        return asset_from_pil(img.crop(box).convert("RGB"))

    def note(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def close(self) -> None:
        with suppress(Exception), PDFIUM_LOCK:
            if self.pdfium is not None:
                self.pdfium.close()
        with suppress(Exception):
            self.fp.close()

    # ------------------------------------------------------------------ page
    def extract_page(self, pno: int, image_mode: str, store: ImageStore, warnings: list[str]) -> PageData:
        page = self.pages[pno - 1]
        try:
            self.interp.process_page(page)
        except PageTooComplex as exc:
            return self._too_complex(pno, page, str(exc), image_mode, store, warnings)
        layout = self.device.get_result()
        W, H = float(layout.width), float(layout.height)
        pd = PageData(pno, W, H)
        text_lines: list[LTTextLine] = []
        hsegs: list[tuple[float, float, float]] = []
        vsegs: list[tuple[float, float, float]] = []
        rects: list[tuple[float, float, float, float]] = []
        flags = {"graphics": False}

        def walk(obj):
            if isinstance(obj, LTTextLine):
                if isinstance(obj, LTTextLineHorizontal):
                    text_lines.append(obj)
                return
            if isinstance(obj, LTImage):
                flags["graphics"] = True
                return
            if isinstance(obj, (LTLine, LTRect, LTCurve)):
                flags["graphics"] = True
                x0, y0, x1, y1 = obj.bbox
                top0, top1 = H - y1, H - y0
                rects.append((x0, top0, x1, top1))
                w, h = x1 - x0, y1 - y0
                if isinstance(obj, LTLine) or (isinstance(obj, LTRect) and (h < 2.5 or w < 2.5)):
                    if h < 2.5 and w >= 8:
                        hsegs.append((x0, x1, (top0 + top1) / 2))
                    elif w < 2.5 and h >= 8:
                        vsegs.append(((x0 + x1) / 2, top0, top1))
                elif isinstance(obj, LTRect):
                    hsegs.append((x0, x1, top0))
                    hsegs.append((x0, x1, top1))
                    vsegs.append((x0, top0, top1))
                    vsegs.append((x1, top0, top1))
                return
            if hasattr(obj, "__iter__"):
                for c in obj:
                    walk(c)

        for item in layout:
            walk(item)
        pd.has_graphics = flags["graphics"]
        nchar = nocr = 0
        for tl in text_lines:
            for c in tl:
                if isinstance(c, LTChar):
                    nchar += 1
                    nocr += is_ocr_font(str(c.fontname))
        pd.ocr_layer = nocr > 0.5 * nchar
        self._observe_advances(text_lines)
        links = self._links(page, H)
        fontinfo = self.device.fontinfo
        lines: list[Line] = []
        bad = 0
        for tl in text_lines:
            ln, nb = self._line(tl, H, fontinfo, links, pno)
            bad += nb
            if ln is not None:
                lines.append(ln)
        pd.bad_chars = bad
        lines = merge_row_fragments(lines)
        tables = []
        if len(hsegs) >= 3 and len(vsegs) >= 3:
            tables, lines = ruled_tables_from_segments(hsegs, vsegs, lines, pno, W, H)
        more, lines = detect_text_tables(lines, pno, W)
        pd.lines, pd.tables = lines, tables + more
        if image_mode != "none" and self.pdfium is not None:
            pd.images = self._images(page, pno, W, H, store, warnings)
            if 3 <= len(rects) <= MAX_CLUSTER_RECTS:
                clusters = cluster_rects(rects, 6.0)
                figs, pd.lines = figures_from_clusters(
                    clusters, pno, W, H, pd.lines, pd.images, pd.tables,
                    lambda r: self._render_region(pno, r, 200), store, rects)
                pd.images += figs
        return pd

    def _too_complex(self, pno: int, page, why: str, image_mode: str, store: ImageStore, warnings: list[str]) -> PageData:
        """Budget exceeded: drop the half-built layout and keep the page as one picture (pdfium renders fast)."""
        self.device.cur_item = None
        self.device._stack = []
        W, H, _, _ = self._page_dims(page)
        pd = PageData(pno, W, H)
        pd.has_graphics = True
        asset = None
        if image_mode != "none" and self.pdfium is not None:
            with suppress(Exception):
                asset = self._render_region(pno, (0, 0, W, H), 110)
        if asset is not None:
            iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
            pd.images = [ImageItem((0, 0, W, H), iid, pno, "figure")]
            warnings.append(f"Page {pno} is too complex to analyse ({why}); it is included as an image.")
        else:
            warnings.append(f"Page {pno} is too complex to analyse ({why}) and was skipped.")
        return pd

    # ---- fixed-pitch detection: identical advance for narrow (i l .) and wide (m w) glyphs
    _NARROW, _WIDE = set("il1I|.,:;!'"), set("mwMW@")

    def _observe_advances(self, text_lines) -> None:
        for tl in text_lines:
            for c in tl:
                if isinstance(c, LTChar) and c.size > 0 and getattr(c, "adv", 0) > 0:
                    t = c.get_text()
                    k = 0 if t in self._NARROW else 2 if t in self._WIDE else None
                    if k is not None:
                        st = self.adv_stats.setdefault(str(c.fontname), [0.0, 0, 0.0, 0])
                        st[k] += c.adv / c.size
                        st[k + 1] += 1

    def _fixed_pitch(self, fontname) -> bool:
        st = self.adv_stats.get(str(fontname))
        if not st or st[1] < 2 or st[3] < 2:
            return False
        narrow, wide = st[0] / st[1], st[2] / st[3]
        return wide > 0 and abs(narrow - wide) <= 0.04 * wide

    # ---- text
    def _line(self, tl, H: float, fontinfo, links, pno: int):
        chars = [c for c in tl if isinstance(c, LTChar)]
        vis = [c for c in chars if c.get_text().strip() and _horizontal(c)]
        if not vis:
            return None, 0
        lone_glyph = len(vis) == 1 and CID_RE.fullmatch(vis[0].get_text()) is not None  # an unmapped bullet drawn apart
        # a drop cap that pdfminer put on the first text line: give it the line's size and keep the line's own height
        dropcap = None
        if len(vis) >= 4 and vis[0] is chars[0]:
            rest = sorted(c.size for c in vis[1:])
            if vis[0].size >= 1.8 * rest[len(rest) // 2]:
                dropcap = vis[0]
                vis = vis[1:]
        ref = max(vis, key=lambda c: c.size)
        base, maxsize = getattr(ref, 'baseline_y', ref.matrix[5]), ref.size
        bad = 0
        spans: list[Span] = []
        cur_key = None
        cur: Span | None = None
        prev_x1 = None
        boxes: list[tuple[float, float, float, float]] = []
        for it in tl:
            if isinstance(it, LTAnno):
                t = it.get_text()
                if cur is not None and not cur.mono and t == " " and not cur.text.endswith(" "):
                    cur.text += " "
                continue
            if not isinstance(it, LTChar) or not _horizontal(it):
                continue
            txt = it.get_text()
            if CID_RE.fullmatch(txt):
                if not lone_glyph:
                    bad += 1
                    continue
                txt = "\u2022"
            txt = map_pua(clean_text(txt), str(it.fontname))
            if txt == "":
                continue
            if it is dropcap:
                x0, y0, x1, y1 = it.bbox
                cur_key = ("dropcap",)
                cur = Span(txt, float(maxsize), bbox=(x0, H - y1, x1, H - y0))
                spans.append(cur)
                boxes.append((x0, H - getattr(ref, "baseline_y", ref.matrix[5]) - maxsize, x0, H - getattr(ref, "baseline_y", ref.matrix[5])))
                prev_x1 = x1
                continue
            if txt.strip():
                small = it.size < 0.86 * maxsize
                oy = getattr(it, 'baseline_y', it.matrix[5])
                sup = small and oy >= base + 0.12 * maxsize
                sub = small and not sup and oy <= base - 0.12 * maxsize
                flags, weight, angle = fontinfo.get(it.fontname, (0, 0.0, 0.0))
                bold, italic, mono = style_from_name(str(it.fontname))
                if not is_ocr_font(str(it.fontname)):
                    bold = bold or bool(flags & 0x40000) or weight >= 600
                    italic = italic or angle != 0
                    mono = mono or bool(flags & 0x1) or self._fixed_pitch(it.fontname)
            else:
                sup = sub = bold = italic = False
                mono = cur.mono if cur else False
            x0, y0, x1, y1 = it.bbox
            bb = (x0, H - y1, x1, H - y0)
            boxes.append(bb)
            if mono and prev_x1 is not None and txt.strip():  # code: keep runs of spaces as printed
                adv = getattr(it, "adv", 0) or 0.6 * it.size
                n = int(round((x0 - prev_x1) / adv)) if adv > 0 else 0
                if 1 <= n <= 80:
                    txt = " " * n + txt
            elif (not mono and prev_x1 is not None and txt.strip() and cur is not None and cur.mono
                  and x0 - prev_x1 > 0.15 * it.size and not cur.text.endswith(" ")):
                txt = " " + txt  # prose resuming right after an inline code span
            prev_x1 = x1
            link = None
            if links and txt.strip():
                cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                for (lx0, ly0, lx1, ly1), target in links:
                    if lx0 <= cx <= lx1 and ly0 <= cy <= ly1:
                        link = target
                        break
            key = (round(it.size, 1), bold, italic, sup, sub, mono, link) if txt.strip() else cur_key
            if cur is None or key != cur_key:
                if not txt.strip() and cur is not None:
                    cur.text += txt
                    continue
                cur_key = key
                cur = Span(txt, float(it.size), bold, italic, sup, sub, mono, bb, link)
                spans.append(cur)
            else:
                cur.text += txt
                cur.bbox = (min(cur.bbox[0], bb[0]), min(cur.bbox[1], bb[1]), max(cur.bbox[2], bb[2]), max(cur.bbox[3], bb[3]))
        if not boxes or not spans:
            return None, bad
        for sp in spans:
            if not sp.mono:
                sp.text = fix_spacing_accents(sp.text)
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        return Line(spans, bbox, pno), bad

    # ---- links
    def _links(self, page, H: float):
        out = []
        try:
            annots = resolve1(page.annots) or []
        except Exception:  # noqa: BLE001
            return out
        for a in annots:
            try:
                a = resolve1(a)
                st = resolve1(a.get("Subtype"))
                if not (isinstance(st, PSLiteral) and st.name == "Link"):
                    continue
                x0, y0, x1, y1 = [float(resolve1(v)) for v in resolve1(a["Rect"])]
                _, _, bx0, by0 = self._page_dims(page)
                rect = (min(x0, x1) - bx0, H - (max(y0, y1) - by0), max(x0, x1) - bx0, H - (min(y0, y1) - by0))
                act = resolve1(a.get("A"))
                target = None
                if isinstance(act, dict):
                    s = resolve1(act.get("S"))
                    sname = s.name if isinstance(s, PSLiteral) else ""
                    if sname == "URI":
                        uri = resolve1(act.get("URI"))
                        uri = uri.decode("latin-1") if isinstance(uri, bytes) else str(uri)
                        target = ("url", uri)
                    elif sname == "GoTo":
                        d = self._resolve_dest(act.get("D"))
                        if d:
                            target = ("page", d[0], d[1])
                elif a.get("Dest") is not None:
                    d = self._resolve_dest(a.get("Dest"))
                    if d:
                        target = ("page", d[0], d[1])
                if target:
                    out.append((rect, target))
            except Exception:  # noqa: BLE001
                continue
        return out

    # ---- images (pypdfium2)
    def _images(self, page, pno: int, W: float, H: float, store: ImageStore, warnings: list[str]) -> list[ImageItem]:
        import pypdfium2.raw as pr

        _, _, bx0, by0 = self._page_dims(page)
        found: list[dict] = []
        # 1. under the pdfium lock: geometry, raw stream bytes and (small enough) decoded bitmaps, copied out
        with PDFIUM_LOCK:
            pp = self.pdfium[pno - 1]
            try:
                objs = list(pp.get_objects(filter=[pr.FPDF_PAGEOBJ_IMAGE], max_depth=10))
                if len(objs) > MAX_IMAGES_PER_PAGE:
                    warnings.append(f"Page {pno}: only the first {MAX_IMAGES_PER_PAGE} of {len(objs)} images were kept.")
                    objs = objs[:MAX_IMAGES_PER_PAGE]
                for obj in objs:
                    try:
                        l, b, r, t = obj.get_bounds()
                        rect = self._to_page_rect(l - bx0, b - by0, r - bx0, t - by0, H)
                        x0, y0, x1, y1 = max(rect[0], 0), max(rect[1], 0), min(rect[2], W), min(rect[3], H)
                        if x1 - x0 < 14 or y1 - y0 < 14:
                            continue
                        pw, ph = obj.get_px_size()
                        raw = None
                        with suppress(Exception):
                            raw = bytes(obj.get_data(decode_simple=False))
                        key = ("raw", hashlib.sha1(raw).hexdigest(), (pw, ph)) if raw else None
                        info = {"box": (x0, y0, x1, y1), "px": (pw, ph), "raw": raw, "key": key, "img": None, "jpeg": False}
                        if (key is None or store.by_key.get(key) is None) and pw * ph <= MAX_DECODE_PIXELS:
                            try:
                                bm = obj.get_bitmap(render=True)
                            except Exception:  # noqa: BLE001
                                bm = obj.get_bitmap()
                            info["img"] = _copy_and_free(bm)
                            with suppress(Exception):
                                info["jpeg"] = any("DCT" in str(f) for f in obj.get_filters())
                        found.append(info)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"page {pno}: an image could not be extracted ({type(exc).__name__})")
            except Exception:  # noqa: BLE001
                return []
            finally:
                pp.close()
        # 2. outside the lock: encoding, and huge bitmaps rendered from the page at output size
        items: list[ImageItem] = []
        for info in found:
            try:
                (x0, y0, x1, y1), (pw, ph), raw, key = info["box"], info["px"], info["raw"], info["key"]
                kind = "scan" if (x1 - x0) * (y1 - y0) >= 0.7 * W * H else "image"
                iid = store.by_key.get(key) if key else None
                if iid is None and info["img"] is None:
                    # huge bitmap (e.g. 11000 x 3600 px plot): decoding it costs hundreds of MB; render the page region
                    # at the output size instead (MAX_IMAGE_DIM long side)
                    dpi = max(36, min(200, int(MAX_IMAGE_DIM * 72 / max(x1 - x0, y1 - y0, 1))))
                    asset = self._render_region(pno, (x0, y0, x1, y1), dpi)
                    self._render_cache = None
                    if asset is not None:
                        warnings.append(f"Page {pno}: a very large image ({pw} x {ph} px) was rendered at reduced size.")
                        iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
                elif iid is None:
                    asset = asset_from_pil(info["img"], info["jpeg"])
                    iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
                if iid is None:
                    continue
                if key:
                    store.by_key[key] = iid
                xref = int(hashlib.sha1((raw or b"")[:4096] + str((pw, ph)).encode()).hexdigest()[:10], 16) if raw else 0
                items.append(ImageItem((x0, y0, x1, y1), iid, pno, kind, xref))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"page {pno}: an image could not be extracted ({type(exc).__name__})")
        return items

    @staticmethod
    def _to_page_rect(l, b, r, t, H):
        """User-space rect (origin = mediabox corner, y up) -> top-left page rect."""
        return (l, H - t, r, H - b)
