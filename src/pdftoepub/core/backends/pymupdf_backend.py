"""Optional PyMuPDF backend (AGPL-3.0). The only module in the project that imports `pymupdf`.

Selected only with PDFTOEPUB_BACKEND=pymupdf and when `pip install pdftoepub[pymupdf]` was done.
"""
from __future__ import annotations

import io

import pymupdf

from ...api import ConversionError
from ..ir import ImageItem, Line, PageData, Span, TableItem
from ..tables import detect_text_tables
from .base import PdfBackend, PdfDocument
from .common import (MAX_DECODE_PIXELS, ImageStore, asset_from_pil, cell_text, clamp_scale, clean_text, encode_image,
                     repair_mojibake, _SPACING_ACCENTS,
                     figures_from_clusters, fix_spacing_accents, is_ocr_font, map_pua, merge_row_fragments,
                     is_math_font, style_from_name, table_from_rows)

pymupdf.TOOLS.mupdf_display_errors(False)


class PyMuPDFBackend(PdfBackend):
    name = "pymupdf"
    needs_global_lock = True  # MuPDF keeps global state: one call into a document at a time, process-wide

    @classmethod
    def available(cls) -> bool:
        return True

    def open(self, path) -> "PyMuPDFDocument":
        try:
            doc = pymupdf.open(str(path))
        except Exception as exc:  # noqa: BLE001 - PyMuPDF raises a variety of types
            raise ConversionError("This file could not be read as a PDF.") from exc
        if not doc.is_pdf:
            doc.close()
            raise ConversionError("This file is not a PDF document.")
        if doc.needs_pass and not doc.authenticate(""):
            doc.close()
            raise ConversionError("This PDF is password-protected; remove the password and try again.")
        if doc.page_count == 0:
            doc.close()
            raise ConversionError("This PDF has no pages.")
        return PyMuPDFDocument(doc)


class PyMuPDFDocument(PdfDocument):
    name = "pymupdf"

    def __init__(self, doc):
        self.doc = doc
        self.page_count = doc.page_count
        self.warnings: list[str] = []

    def metadata(self) -> dict[str, str]:
        m = self.doc.metadata or {}
        return {"title": repair_mojibake(m.get("title") or ""), "author": repair_mojibake(m.get("author") or "")}

    def toc(self):
        out = []
        for e in self.doc.get_toc(simple=False):
            y = 0.0
            if len(e) > 3 and isinstance(e[3], dict) and e[3].get("to") is not None:
                y = float(e[3]["to"].y)
            out.append((int(e[0]), str(e[1]), int(e[2]), y))
        return out

    def render_page(self, pno: int, dpi: float, gray: bool = False):
        from PIL import Image

        page = self.doc[pno - 1]
        scale, clamped = clamp_scale(page.rect.width, page.rect.height, dpi)
        if clamped and (msg := f"Page {pno} is very large; it was rendered at reduced resolution.") not in self.warnings:
            self.warnings.append(msg)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace="gray" if gray else None, alpha=False)
        return Image.frombytes("L" if gray else "RGB", (pix.width, pix.height), pix.samples)

    def close(self) -> None:
        self.doc.close()

    # ------------------------------------------------------------------ page
    def extract_page(self, pno: int, image_mode: str, store: ImageStore, warnings: list[str]) -> PageData:
        page = self.doc[pno - 1]
        rect = page.rect
        pd = PageData(pno, float(rect.width), float(rect.height))
        n_draw = 0
        try:
            n_draw = len(page.get_cdrawings())
            pd.has_graphics = bool(page.get_images()) or n_draw > 0
        except Exception:  # noqa: BLE001
            pd.has_graphics = False
        pd.lines = self._lines(page, pno)
        pd.ocr_layer = self._ocr_chars > 0.5 * max(1, self._all_chars)
        tables: list[TableItem] = []
        if n_draw >= 4:  # ruled tables need ruling lines
            tables, pd.lines = self._ruled_tables(page, pno, pd.lines)
        more, pd.lines = detect_text_tables(pd.lines, pno, pd.width)
        pd.tables = tables + more
        if image_mode != "none":
            pd.images = self._images(page, pno, store, warnings)
            if n_draw >= 3:
                figs, pd.lines = self._figures(page, pno, pd, store)
                pd.images += figs
        return pd

    def _links(self, page):
        out = []
        try:
            links = page.get_links()
        except Exception:  # noqa: BLE001
            return out
        for lk in links:
            r = pymupdf.Rect(lk["from"])
            kind = lk.get("kind")
            if kind == pymupdf.LINK_URI and lk.get("uri"):
                out.append((r, ("url", lk["uri"])))
            elif kind == pymupdf.LINK_GOTO and lk.get("page", -1) >= 0:
                to = lk.get("to")
                out.append((r, ("page", int(lk["page"]) + 1, float(to.y) if to is not None else 0.0)))
        return out

    def _lines(self, page, pno: int) -> list[Line]:
        flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES & ~pymupdf.TEXT_PRESERVE_LIGATURES
        plain = page.get_text("text", flags=flags | pymupdf.TEXT_INHIBIT_SPACES)
        nchar = sum(1 for c in plain if not c.isspace() or c == " ")
        if plain.count(" ") >= 20 and plain.count(" ") >= 0.06 * nchar:
            # the layer has its own space glyphs (OCR layers, most word processors): they are the word boundaries, and
            # the gap-based spaces MuPDF adds would split letter-spaced words ("B e r n a r d")
            data = _spaced_text(page.get_text("rawdict", flags=flags | pymupdf.TEXT_INHIBIT_SPACES))
        else:
            data = page.get_text("dict", flags=flags)
        links = self._links(page)
        lines: list[Line] = []
        self._ocr_chars = self._all_chars = 0
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for ln in block.get("lines", []):
                dx, dy = ln.get("dir", (1, 0))
                if abs(dy) > 0.2 or dx < 0.8:  # vertical / rotated text (watermarks, margin text)
                    continue
                raw = [s for s in ln.get("spans", []) if s.get("text") is not None and clean_text(s["text"]) != ""]
                visible = [s for s in raw if s["text"].strip()]
                if not visible:
                    continue
                ref = max(visible, key=lambda s: s["size"])
                base_y = ref["origin"][1]
                maxsize = ref["size"]
                all_flagged_sup = all(s["flags"] & 1 for s in visible)
                spans: list[Span] = []
                for s in raw:
                    bold, italic, mono = style_from_name(s["font"], s["flags"])
                    text = map_pua(clean_text(s["text"]), s["font"])
                    if not mono:
                        text = fix_spacing_accents(text)
                    small = s["size"] < 0.86 * maxsize
                    oy = s["origin"][1]
                    sup = small and oy <= base_y - 0.12 * maxsize
                    sub = small and not sup and oy >= base_y + 0.12 * maxsize
                    # MuPDF's superscript flag: trusted for markers ("12", "*"), not for a run of text or a full-size
                    # operator that merely sits on another baseline of a multi-row "line" (formulas)
                    if (not all_flagged_sup and (s["flags"] & 1) and 0 < len(s["text"].strip()) <= 3
                            and len(visible) > 1 and (s["size"] < 0.95 * maxsize or s["text"].strip().isdigit())):
                        sup = True
                    if not s["text"].strip():
                        bold = italic = sup = sub = False
                    link = None
                    if links and s["text"].strip():
                        r = pymupdf.Rect(s["bbox"])
                        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
                        for lr, target in links:
                            if lr.x0 <= cx <= lr.x1 and lr.y0 <= cy <= lr.y1:
                                link = target
                                break
                    self._all_chars += len(text)
                    if is_ocr_font(s["font"]):
                        self._ocr_chars += len(text)
                    spans.append(Span(text, float(s["size"]), bold, italic, sup, sub, mono, tuple(s["bbox"]), link,
                                      is_math_font(s["font"]) and bool(s["text"].strip())))
                for a, b in zip(spans, spans[1:]):  # a spacing accent in its own span ("G" "´" "EOM"): on its letter
                    if (len(a.text) == 1 and a.text in _SPACING_ACCENTS and b.text[:1].isalpha() and len(b.text) > 1
                            and not a.math and not b.math and abs(a.size - b.size) <= 0.5):  # not a hat in a formula
                        joined = fix_spacing_accents(a.text + b.text)
                        if joined != a.text + b.text:  # the accent combined with the letter
                            b.text, a.text = joined, ""
                spans = [sp for sp in spans if sp.text != ""] or spans
                lines.append(Line(spans, tuple(ln["bbox"]), pno))
        ocr_layer = self._ocr_chars > 0.5 * max(1, self._all_chars)
        return merge_row_fragments(lines, 2.0 if ocr_layer else 0.45)

    def _ruled_tables(self, page, pno: int, lines: list[Line]):
        try:
            try:
                finder = page.find_tables(use_layout=False)  # deterministic and much faster than the optional ML model
            except TypeError:  # older PyMuPDF without the switch
                finder = page.find_tables()
        except Exception:  # noqa: BLE001
            return [], lines
        page_area = page.rect.width * page.rect.height
        tables, taken = [], set()
        for t in finder.tables:
            try:
                raw_rows = t.extract()
                row_objs = list(t.rows)
            except Exception:  # noqa: BLE001
                continue
            rows = []
            for ri, rr in enumerate(raw_rows):
                cells = row_objs[ri].cells if ri < len(row_objs) else []
                out = []
                for ci, c in enumerate(rr):
                    cb = cells[ci] if ci < len(cells) else None
                    txt = cell_text(lines, tuple(cb)) if cb else ""
                    out.append(txt or clean_text(c or "").replace("\n", " ").strip())
                rows.append(out)
            item, consumed = table_from_rows(rows, tuple(t.bbox), pno, lines, page_area)
            if item is not None and not (consumed & taken):
                tables.append(item)
                taken |= consumed
        return tables, [l for i, l in enumerate(lines) if i not in taken]

    def _images(self, page, pno: int, store: ImageStore, warnings: list[str]) -> list[ImageItem]:
        items: list[ImageItem] = []
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:  # noqa: BLE001
            return items
        page_area = page.rect.width * page.rect.height
        for info in infos:
            r = pymupdf.Rect(info["bbox"]) & page.rect
            if r.is_empty or r.width < 14 or r.height < 14:
                continue
            xref = int(info.get("xref") or 0)
            kind = "scan" if r.width * r.height >= 0.7 * page_area else "image"
            iid = store.by_key.get(("x", xref)) if xref else None
            if iid is None:
                asset = None
                try:
                    tr = info.get("transform") or (1, 0, 0, 1, 0, 0)
                    simple = abs(tr[1]) < 1e-3 and abs(tr[2]) < 1e-3 and tr[0] > 0 and tr[3] > 0
                    pw, ph = int(info.get("width") or 0), int(info.get("height") or 0)
                    if pw * ph > MAX_DECODE_PIXELS:  # never decode a huge bitmap at its declared size
                        simple = False
                        warnings.append(f"Page {pno}: a very large image ({pw} x {ph} px) was rendered at reduced size.")
                    if xref and simple:
                        img, jpg = self._load_xref_image(xref)
                        if img is not None:
                            asset = asset_from_pil(img, jpg)
                    if asset is None:
                        asset = self._render_region(page, r, 150)
                except Exception as exc:  # noqa: BLE001
                    try:
                        asset = self._render_region(page, r, 150)
                    except Exception:  # noqa: BLE001
                        warnings.append(f"page {pno}: an image could not be extracted ({type(exc).__name__})")
                if asset is None:
                    continue
                iid = store.add(asset.data, asset.media_type, asset.width, asset.height)
                if xref:
                    store.by_key[("x", xref)] = iid
            items.append(ImageItem(tuple(r), iid, pno, kind, xref))
        return items

    def _load_xref_image(self, xref: int):
        from PIL import Image

        info = self.doc.extract_image(xref)
        if not info or not info.get("image"):
            return None, False
        img = Image.open(io.BytesIO(info["image"]))
        img.load()
        smask = info.get("smask") or 0
        if smask:
            m = self.doc.extract_image(smask)
            if m and m.get("image"):
                mask = Image.open(io.BytesIO(m["image"])).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size)
                img = img.convert("RGBA")
                img.putalpha(mask)
        return img, info.get("ext", "").lower() in ("jpeg", "jpg", "jpx")

    @staticmethod
    def _render_region(page, rect, dpi: int = 200, gray: bool = False):
        from PIL import Image

        rect = rect & page.rect
        if rect.is_empty or rect.width < 4 or rect.height < 4:
            return None
        scale, _ = clamp_scale(rect.width, rect.height, dpi)
        pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(scale, scale), alpha=False,
                              colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB)
        return asset_from_pil(Image.frombytes("L" if gray else "RGB", (pix.width, pix.height), pix.samples))

    def render_region(self, pno: int, rect, dpi: int = 200, gray: bool = False):
        return self._render_region(self.doc[pno - 1], pymupdf.Rect(rect), dpi, gray)

    def _figures(self, page, pno: int, pd: PageData, store: ImageStore):
        try:
            clusters = [tuple(pymupdf.Rect(r)) for r in page.cluster_drawings()]
            shapes = [tuple(pymupdf.Rect(d["rect"])) for d in page.get_cdrawings()]
        except Exception:  # noqa: BLE001
            return [], pd.lines
        return figures_from_clusters(
            clusters, pno, pd.width, pd.height, pd.lines, pd.images, pd.tables,
            lambda r: self._render_region(page, pymupdf.Rect(r), 200), store, shapes,
        )


def _spaced_text(data: dict) -> dict:
    """rawdict -> dict-like spans ("text"): the layer's own spaces, plus one where a gap is well above the line's
    letter spacing (a space glyph the layer lacks)."""
    for block in data.get("blocks", []):
        for ln in block.get("lines", []):
            chars = [c for s in ln.get("spans", []) for c in s.get("chars", [])]
            size = max((s["size"] for s in ln.get("spans", [])), default=10.0)
            gaps = sorted(g for a, b in zip(chars, chars[1:]) if a["c"].strip() and b["c"].strip()
                          and (g := b["bbox"][0] - a["bbox"][2]) < 0.25 * size)  # letter spacing, not word gaps
            track = max(0.0, gaps[(len(gaps) - 1) // 2]) if gaps else 0.0
            wide = max(0.18 * size, 2.5 * track + 0.05 * size)
            prev, prev_math = None, False
            for s in ln.get("spans", []):
                out = []
                math = is_math_font(s.get("font", ""))
                for c in s.get("chars", []):
                    # between math-font glyphs the usual narrow gap is a space (formulas have no space glyphs)
                    need = 0.12 * size if (math or prev_math) else wide
                    if prev is not None and c["c"].strip() and prev["c"].strip() and c["bbox"][0] - prev["bbox"][2] >= need:
                        out.append(" ")
                    out.append(c["c"])
                    prev, prev_math = c, math
                s["text"] = "".join(out)
    return data
