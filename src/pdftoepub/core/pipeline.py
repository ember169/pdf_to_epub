"""Orchestration: PDF -> (extract, OCR) -> layout -> structure -> EPUB. Entry point: `run`."""
from __future__ import annotations

import hashlib
import re
import threading
import uuid
from contextlib import nullcontext
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

from ..api import ConversionError, ConvertOptions, ConvertResult, ProgressCb, ProgressEvent
from . import endnotes, formulas, frontmatter, layout, ocr, ocrfix, openings, printedtoc, structure
from .backends import get_backend
from .backends.common import ImageStore, cover_from_pil, limit_pillow, page_text_quality
from .epub import write_epub
from .ir import Chapter, Document, Figure, Heading, ImageAsset, ListBlock, PageData, Paragraph, Table

# MuPDF keeps global state: with the PyMuPDF backend, calls into a document take turns process-wide (one call at a
# time, released during OCR). The default backend needs no job-level lock: pdfminer is pure Python with per-document
# state, and its pdfium calls hold backends.base.PDFIUM_LOCK only for the duration of each call.
_PDF_LOCK = threading.RLock()
_LANG_OK = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
MAX_WARNINGS = 60


def run(pdf_path: Path, epub_path: Path, options: ConvertOptions, progress: ProgressCb | None = None,
        max_pages: int | None = None) -> ConvertResult:
    """Convert one PDF. `max_pages` (not part of the public API; used by core.isolation) rejects longer documents."""
    try:
        return _run(Path(pdf_path), Path(epub_path), options, progress, max_pages)
    except ConversionError:
        raise
    except MemoryError as exc:
        raise ConversionError("The PDF is too large to convert with the available memory.") from exc
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback type to the user
        raise ConversionError(f"The PDF could not be converted ({type(exc).__name__}).") from exc


def _emit(cb: ProgressCb | None, stage: str, page: int = 0, total: int = 0, message: str = "") -> None:
    if cb:
        cb(ProgressEvent(stage, page, total, message))


def _check_pdf(path: Path) -> None:
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
    except OSError as exc:
        raise ConversionError("The uploaded file could not be read.") from exc
    if b"%PDF-" not in head:
        raise ConversionError("This file is not a PDF document.")


def _normalize_ocr_sizes(pages: list[PageData]) -> None:
    def mode(ps):
        c: Counter = Counter()
        for p in ps:
            for l in p.lines:
                for s in l.spans:
                    if s.text.strip():
                        c[round(s.size * 2) / 2] += len(s.text.strip())
        return c.most_common(1)[0][0] if c else None

    native = mode([p for p in pages if p.source == "native"])
    ocrm = mode([p for p in pages if p.source == "ocr"])
    if native and ocrm and abs(native - ocrm) > 0.4:
        k = native / ocrm
        for p in pages:
            if p.source == "ocr":
                for l in p.lines:
                    for s in l.spans:
                        s.size *= k


def _scan_is_redundant(pd: PageData, thumb) -> tuple[bool, bool]:
    """(junk, inverted) for a scanned page with little text. The page image is junk when, outside its text lines, it
    holds no more than specks: a blank page, or a picture of text the layer already has. A mostly dark page is read
    as white on black (inverted) first."""
    img = thumb.convert("L")
    sx, sy = img.width / max(pd.width, 1.0), img.height / max(pd.height, 1.0)
    inverted = ImageStat.Stat(img).mean[0] < 110
    if inverted:  # the dark block only (scans keep a white margin around it), then white on black -> black on white
        dark = img.point(lambda v: 255 if v < 128 else 0)
        rows = _longest_run(v > 150 for v in dark.resize((1, img.height), Image.BOX).tobytes())
        cols = _longest_run(v > 150 for v in dark.resize((img.width, 1), Image.BOX).tobytes())
        dx, dy = max(2, round(0.03 * img.width)), max(2, round(0.03 * img.height))  # scans are a little skewed
        box = (cols[0] + dx, rows[0] + dy, cols[1] - dx, rows[1] - dy) if rows and cols else None
        if box and box[2] > box[0] and box[3] > box[1]:
            block = Image.new("L", img.size, 0)  # black outside the block: no ink once inverted
            block.paste(img.crop(box), box[:2])
            img = block
        img = ImageOps.invert(img)
    ink = img.point(lambda v: 255 if v < 128 else 0)
    if pd.lines:
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        for l in pd.lines:
            m = 0.5 * l.size
            draw.rectangle(((l.x0 - m) * sx, (l.y0 - m) * sy, (l.x1 + m) * sx, (l.y1 + m) * sy), fill=255)
        ink = ImageChops.subtract(ink, mask)
    left = sum(ink.histogram()[128:]) / max(1, img.width * img.height)
    return left < 0.005, inverted


def _uniform(store: ImageStore, iid: str) -> bool:
    asset = store.assets.get(iid)
    if asset is None:
        return False
    try:
        import io

        im = Image.open(io.BytesIO(asset.data)).convert("L")
        im.thumbnail((200, 200))
        return ImageStat.Stat(im).stddev[0] < 6
    except Exception:  # noqa: BLE001
        return False


def _longest_run(flags) -> tuple[int, int] | None:
    """[start, end) of the longest run of true values."""
    best, start = None, None
    flags = list(flags) + [False]
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def _extract_all(doc, options: ConvertOptions, progress, warnings: list[str], store: ImageStore, lock=nullcontext()):
    n = doc.page_count
    pages: list[PageData] = []
    engine = None
    engine_checked = False
    ocr_pages = 0
    skipped_ocr = 0
    ocr_off_pages = 0
    for pno in range(1, n + 1):
        _emit(progress, "extract", pno, n)
        try:
            with lock:
                pd = doc.extract_page(pno, options.image_mode, store, warnings)
        except Exception as exc:  # noqa: BLE001
            pd = PageData(pno, 595.0, 842.0)
            warnings.append(f"Page {pno} could not be read ({type(exc).__name__}) and was skipped.")
        nchars, garbage = page_text_quality(pd.lines, pd.bad_chars)
        scan = any(im.kind == "scan" for im in pd.images)
        needs_ocr = False
        textless = garbage or (nchars < 20 and (scan or (pd.has_graphics and not pd.images)))
        if options.ocr == "force":
            needs_ocr = True
        elif options.ocr == "auto":
            needs_ocr = textless
        elif textless:
            ocr_off_pages += 1
        if needs_ocr:
            if not engine_checked:
                engine, warn = ocr.find_engine(options.ocr_langs)
                engine_checked = True
                if warn:
                    warnings.append(warn)
                if engine is not None and engine.warning:
                    warnings.append(engine.warning)
            if engine is None:
                skipped_ocr += 1
                pd.ocr_failed = True
                if garbage:
                    pd.lines = []
            else:
                _emit(progress, "ocr", pno, n, "Recognising text")
                try:
                    with lock:
                        image = doc.render_page(pno, ocr.OCR_DPI, gray=True)
                    lines = ocr.ocr_image(engine, image, pno)  # tesseract runs without any lock
                    del image
                except Exception:  # noqa: BLE001
                    lines = None
                if lines is None:
                    warnings.append(f"Page {pno}: OCR failed; the page content may be missing.")
                    pd.ocr_failed = True
                elif lines:
                    pd.lines = lines
                    pd.source = "ocr"
                    pd.tables = []
                    pd.images = [im for im in pd.images if im.kind not in ("scan", "figure")]
                    ocr_pages += 1
        elif scan and nchars >= 150:
            pd.images = [im for im in pd.images if im.kind != "scan"]  # searchable scan: the text layer is the content
        if any(im.kind == "scan" for im in pd.images) and options.image_mode != "none" \
                and page_text_quality(pd.lines, 0)[0] < 150:
            try:
                with lock:
                    thumb = doc.render_page(pno, 50, gray=True)
                junk, inverted = _scan_is_redundant(pd, thumb)
            except Exception:  # noqa: BLE001 - keep the page image when it cannot be judged
                junk, inverted = False, False
            if inverted and options.ocr != "off" and pd.source != "ocr":  # white on black (part dividers): OCR it inverted
                if not engine_checked:
                    engine, warn = ocr.find_engine(options.ocr_langs)
                    engine_checked = True
                    if warn:
                        warnings.append(warn)
                if engine is not None:
                    try:
                        with lock:
                            image = doc.render_page(pno, ocr.OCR_DPI, gray=True)
                        lines = ocr.ocr_image(engine, ImageOps.invert(image), pno)
                        del image
                    except Exception:  # noqa: BLE001
                        lines = None
                    lines = [l for l in lines or [] if sum(c.isalpha() for c in l.text) >= 2  # not specks ("»")
                             or re.fullmatch(r"\s*[IVXLC\d]{1,4}\s*[.·-]?\s*", l.text)]
                    letters = sum(c.isalpha() for l in lines for c in l.text)
                    if lines and letters >= 0.6 * sum(c.isalpha() for l in pd.lines for c in l.text):
                        pd.lines, pd.source, pd.ocr_layer = lines, "ocr", False
                        ocr_pages += 1
            if junk:  # blank, specks, or a picture of text the layer already holds
                pd.images = [im for im in pd.images if im.kind != "scan"]
            else:  # a uniform layer of the scan (an all-black mask) is no picture either
                pd.images = [im for im in pd.images if im.kind != "scan" or not _uniform(store, im.image_id)]
        if pd.source == "native" and options.image_mode != "none":
            def render(rect, dpi, pno=pno):
                with lock:
                    return doc.render_region(pno, rect, dpi, gray=True)
            try:
                formulas.process_page(pd, render, store)
            except Exception:  # noqa: BLE001 - formulas then stay as plain text lines
                pass
        pages.append(pd)
    if skipped_ocr:
        warnings.append(f"{skipped_ocr} page(s) have no usable text layer and OCR is unavailable; scanned page images were kept instead.")
    if ocr_off_pages:
        warnings.append(f"{ocr_off_pages} page(s) have no usable text layer and OCR is turned off; scanned page images were kept instead.")
    return pages, ocr_pages


def _run(pdf_path: Path, epub_path: Path, options: ConvertOptions, progress: ProgressCb | None,
         max_pages: int | None = None) -> ConvertResult:
    if not pdf_path.is_file():
        raise ConversionError("The uploaded file could not be found.")
    _check_pdf(pdf_path)
    limit_pillow()
    warnings: list[str] = []
    store = ImageStore()
    backend, bwarn = get_backend()
    if bwarn:
        warnings.append(bwarn)

    lock = _PDF_LOCK if backend.needs_global_lock else nullcontext()
    with lock:
        doc = backend.open(pdf_path)
    try:
        with lock:
            n = doc.page_count
            meta = doc.metadata()
        if max_pages and n > max_pages:
            raise ConversionError(f"This PDF has {n} pages; the limit is {max_pages}.")
        toc_raw = []
        try:
            with lock:
                toc_raw = doc.toc()
        except Exception:  # noqa: BLE001
            warnings.append("The PDF outline could not be read; chapters were detected from headings.")
        pages, ocr_pages = _extract_all(doc, options, progress, warnings, store, lock)
        cover = None
        if options.image_mode != "none":
            p0 = pages[0]
            if p0.lines or p0.images or p0.tables:
                try:
                    with lock:
                        cover = cover_from_pil(doc.render_page(1, 110))
                except Exception:  # noqa: BLE001
                    cover = None
        warnings.extend(w for w in getattr(doc, "warnings", []) if w not in warnings)
    finally:
        with lock:
            doc.close()

    # ------------------------------------------------------------------ analyse
    _emit(progress, "analyze", 0, n, "Analysing layout")
    if not any(p.lines or p.images or p.tables for p in pages):
        if any(p.has_graphics for p in pages):
            raise ConversionError("No text could be extracted from this PDF. If it is a scan, enable OCR (Tesseract must be installed).")
        raise ConversionError("This PDF appears to contain no text or images.")
    _normalize_ocr_sizes(pages)
    for p in pages:
        if p.source == "ocr" or p.ocr_layer:
            layout.snap_ocr_sizes(p)
    fol = printedtoc.folios(pages)  # printed page numbers, before running heads and folios are removed
    printed_toc, toc_pages = printedtoc.parse(pages)
    running: Counter = Counter()
    if options.drop_headers_footers:
        layout.remove_running(pages, warnings, running)
    ctx = layout.compute_ctx(pages, options.detect_columns)
    layout.drop_ocr_noise(pages, ctx)
    printed = frontmatter.from_pages(pages, ctx.body_size, running)
    ctx.sparse_pages = {p.number for p in pages if (p.source == "ocr" or p.ocr_layer)
                        and page_text_quality(p.lines, 0)[0] < 150}

    raw = []
    notes: dict[int, list] = {}
    for i, p in enumerate(pages, 1):
        _emit(progress, "analyze", i, n)
        try:
            blocks, ns = layout.page_blocks(p, ctx)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Page {p.number}: layout analysis failed ({type(exc).__name__}); page skipped.")
            continue
        raw += blocks
        if ns:
            notes[p.number] = ns
    if not raw:
        raise ConversionError("No readable text was found in this PDF.")
    raw = endnotes.extract(raw, notes, {p.number: p.width for p in pages})

    model = structure.build_heading_model(raw, ctx)
    toc = structure.clean_toc(toc_raw, n)
    offset = printedtoc.page_offset(fol) if printed_toc and not toc else None
    if offset is None and printed_toc and not toc:
        offset = printedtoc.offset_from_titles(printed_toc, pages, toc_pages)
    # a flat list of titles carries less than the page-layout openings (scans): numbered chapters or parts are needed
    use_printed = offset is not None and len(printed_toc) >= 3 and (
        sum(e.kind == "chapter" for e in printed_toc) >= 3 or sum(e.kind == "part" for e in printed_toc) >= 2)
    plan = None
    if not toc and not use_printed:  # scanned books: chapters from the page layout and the printed table of contents
        plan = openings.plan(raw, pages, ctx, running, structure.clean_text_field(options.title)
                             or structure.clean_meta_title(meta.get("title")) or printed.title or "")
    blocks, footnotes = structure.convert_blocks(raw, ctx, notes, model, plan)
    blocks = structure.inline_display_math(blocks)
    blocks = structure.merge_across_breaks(blocks, ctx)
    blocks = structure.merge_code_blocks(blocks)
    blocks = structure.group_lists(blocks)
    blocks = structure.attach_captions(blocks)
    blocks = structure.merge_adjacent_headings(blocks)
    split_level = None
    if use_printed:  # the printed contents: one spine document per part / chapter, its sections in the navigation
        blocks, entries = printedtoc.apply(blocks, printed_toc, toc_pages, offset, n)
        toc = structure.clean_toc([(lv, t, p, max(y, 0.0)) for lv, t, p, y in entries], n)
        split_level = max(e.level for e in printed_toc)
    if sum(p.source == "ocr" or p.ocr_layer for p in pages) >= 0.5 * len(pages):
        ocrfix.correct(blocks)
    if not blocks:
        raise ConversionError("No readable text was found in this PDF.")

    # ------------------------------------------------------------------ metadata
    # every candidate is sanitised; one that ends up empty (control characters only, lone surrogates) falls through
    title = (structure.clean_text_field(options.title) or structure.clean_meta_title(meta.get("title"))
             or structure.clean_text_field(printed.title) or _guess_title(blocks, pdf_path))
    author = structure.clean_text_field(options.author) or structure.clean_text_field(meta.get("author"))
    if re.fullmatch(r"(?i)(anonymous|unknown|unspecified|author|user|admin(istrator)?|n/?a)", author or ""):
        author = ""  # a tool's placeholder (reportlab writes "anonymous"), not a name
    creators = [] if author else [(n, "edt") for n in (structure.clean_text_field(e) for e in printed.editors) if n]
    sample = " ".join(structure.plain(b.runs) for b in blocks if isinstance(b, Paragraph))[:30000]
    lang = options.language if options.language and _LANG_OK.match(options.language) else structure.detect_language(sample)

    chapters = structure.build_chapters(blocks, toc, n, title, warnings, split_level)
    for ch in chapters:  # a reference and its endnote in the same document
        endnotes.link(ch.blocks)
    structure.resolve_links(chapters)
    labels = printedtoc.page_labels(fol, n)
    if not labels and use_printed:  # the contents' page numbers fixed the offset
        labels = {p: str(p + offset) for p in range(1, n + 1) if p + offset >= 1}
    structure.mark_pages(chapters, labels)
    _attach_orphan_notes(chapters, footnotes)

    # ------------------------------------------------------------------ build
    _emit(progress, "build", n, n, "Writing EPUB")
    used = {b.image_id for ch in chapters for b in ch.blocks if isinstance(b, Figure)}
    used |= {r.image[0] for ch in chapters for b in ch.blocks if isinstance(b, Paragraph) for r in b.runs if r.image}
    images = {k: v for k, v in store.assets.items() if k in used}
    doc_ir = Document(title, author, lang, chapters, images, cover, warnings, creators,
                      structure.clean_text_field(printed.publisher) or "", printed.year,
                      printed.isbn or frontmatter.isbn_from_filename(pdf_path.stem), labels)
    ident = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, _fingerprint(pdf_path) + "|" + title))
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    write_epub(doc_ir, footnotes, epub_path, ident)
    _emit(progress, "done", n, n)
    return ConvertResult(epub_path, title, n, len(chapters), ocr_pages, _cap(warnings))


def _cap(w: list[str]) -> list[str]:
    seen: list[str] = []
    for x in w:
        if x not in seen:
            seen.append(x)
    if len(seen) > MAX_WARNINGS:
        extra = len(seen) - MAX_WARNINGS
        seen = seen[:MAX_WARNINGS] + [f"... and {extra} more warnings"]
    return seen


def _fingerprint(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()


def _guess_title(blocks, pdf_path: Path) -> str:
    for b in blocks[:12]:
        if isinstance(b, Heading) and b.level == 1 and b.page <= 2:
            t = structure.clean_text_field(structure.plain(b.runs))
            if 2 <= len(t) <= 200:
                return t
    stem = structure.clean_text_field(frontmatter.title_from_filename(pdf_path.stem))  # may hold surrogate escapes
    return stem or "Untitled"


def _attach_orphan_notes(chapters: list[Chapter], footnotes: dict) -> None:
    """Notes without a detectable in-text reference go to the end of the chapter containing their page."""
    orphans = sorted((f for f in footnotes.values() if f.orphan), key=lambda f: (f.page, f.id))
    if not orphans or not chapters:
        return
    last_pages = [max((b.page for b in ch.blocks), default=0) for ch in chapters]
    for fn in orphans:
        idx = next((i for i, lp in enumerate(last_pages) if lp >= fn.page), len(chapters) - 1)
        chapters[idx].footnotes.append(fn)
