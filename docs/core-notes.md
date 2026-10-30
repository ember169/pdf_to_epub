# Notes for master (core session)

No change to `api.py` is required. `pdftoepub.core.pipeline.run` matches the contract; `ConversionError` is raised for every
unrecoverable case (also wraps unexpected exceptions).

Things other sessions / the Docker image should know:

* **Thread safety**: MuPDF is not thread-safe. `pipeline.run` serialises the PDF-touching phase (open/extract/OCR/render) with a
  module-level lock, so a thread pool is safe but PDF reading is effectively one-at-a-time. For real parallelism run jobs in processes.
* **Tesseract**: only the `tesseract` binary on PATH (+ language packs, `fra`/`eng` in the image). No pytesseract. Missing tesseract
  or missing languages -> warnings, never an error. The subprocess is run with `OMP_THREAD_LIMIT=1`.
* **Backends** (MIT decision): all PDF access is behind `core/backends/`. Default = pdfminer.six + pypdfium2 (`auto` also means pdfminer). `PDFTOEPUB_BACKEND=pymupdf` uses PyMuPDF only if installed (else warning + pdfminer). `pymupdf` is imported only in `backends/pymupdf_backend.py` (lazily, via `get_backend`). Core tests and `tests/` pass on both backends (136 passed).
* **pymupdf_layout** (installed in the dev venv, not a dependency) changes `find_tables`; core calls `find_tables(use_layout=False)`
  so behaviour is identical with/without it.
* **Runtime deps used**: pdfminer.six, pypdfium2, pillow (no lxml, no pymupdf at runtime). Dev/test only: lxml, reportlab, pypdf (core tests build encrypted/blank PDFs with pypdf), pymupdf (to test the optional backend).
* **Core tests** live in `src/pdftoepub/core/tests` (pyproject `testpaths = ["tests"]` does not pick them up; run
  `pytest src/pdftoepub/core/tests`). They generate PDFs with reportlab at test time (`core/_samples/make_samples.py`).
* epubcheck 5.4.0 (same pinned jar as `tests/epubcheck.py`) reported 0 errors/warnings on the generated book, no-outline book, two-column
  article (footnotes + image), OCR'd scan, and a 420-page real-world book.
* Cover image is in the manifest only (not in the spine) so no chapter is image-only. `ConvertResult.chapter_count` counts spine
  documents (front matter included).
* Typical speed: ~30 s for a 420-page text book without OCR; OCR costs ~1-3 s/page (tesseract 300 dpi).

## Corpus evaluation round (real-world PDFs)

* Harness: `tests/corpus/` (manifest.json, fetch.py, evaluate.py, REPORT.md). Files in `tests/.corpus/` (git- and docker-ignored:
  I added `tests/.corpus/` + `tests/corpus/out/` to `.gitignore` and `tests/.corpus`, `tests/corpus/out` to `.dockerignore`,
  otherwise `COPY tests` would put ~100 MB of PDFs into the test image). No pytest tests live in `tests/corpus/`, so the
  `tests/` suite is unchanged.
* New env var `PDFTOEPUB_PAGE_TIMEOUT` (seconds, default 60): per-page content-stream budget on the pdfminer backend; pages over
  budget (or >150k glyphs) are kept as an image with a warning "Page N is too complex to analyse (...)". No API change.
* `PageData.ocr_layer` (IR, internal) marks pages whose text is an invisible Tesseract layer (GlyphLessFont).

## Security / robustness audit fixes (items 4, 5, 6, 9, 11)

* **(4) Locking**: the job-wide `_PDF_LOCK` is gone for the default backend. pdfminer parsing, layout, OCR (tesseract) and
  packaging run fully in parallel. PDFium is *not* thread-safe even across documents (pypdfium2 docs), so every pdfium
  call (open, render, image objects, closing pages / bitmaps — closed explicitly so no GC finaliser runs pdfium on another
  thread) holds `core.backends.base.PDFIUM_LOCK`, for the duration of that call only. PyMuPDF (`needs_global_lock = True`)
  still takes turns process-wide, but per call and released during OCR. Tests: one job blocked inside OCR does not delay
  another; 4 concurrent jobs give byte-identical EPUB content to sequential runs.
* **(5) Memory**: every page render is clamped to 50 MP (`common.clamp_scale`, warning "Page N is very large; it was
  rendered at reduced resolution."); embedded bitmaps > 12 MP are never decoded at declared size (rendered from the page at
  output size, warning); max 300 images per page; `PIL.Image.MAX_IMAGE_PIXELS` set explicitly (25 MP → bomb error > 50 MP).
* **(6) Isolation** — for the web session:
  `from pdftoepub.core.isolation import convert_isolated`
  `convert_isolated(pdf, epub, options=None, progress=None, timeout_s=600, max_mem_mb=2048, max_pages=None) -> ConvertResult`
  Same result/exceptions as `pdftoepub.convert` (api unchanged); runs in a `spawn` child, progress events relayed through a
  pipe, `None` disables a limit. Breaches raise `ConversionError`: "took longer than N seconds", "needs more than N MB of
  memory", "This PDF has N pages; the limit is M.", or "stopped by the system / unexpectedly". Partial EPUB removed.
  Memory: parent RSS watchdog (psutil if installed, else /proc, else `ps`) + RLIMIT_AS backstop in the child on Linux
  (max(2×cap, cap+1 GB) virtual; macOS does not enforce RLIMIT_AS, Windows has no RLIMIT — the watchdog covers both, and on
  Windows only if psutil is installed). Child start-up costs ~0.5–1 s (imports). Test includes a 0.25 MB Flate bomb that
  inflates to 600 MB: stopped at a 250 MB cap.
  **Packaging requirement**: because the child is started with `spawn`, a PyInstaller binary must call
  `multiprocessing.freeze_support()` as the first statement under `if __name__ == "__main__":` in the entry script
  (`packaging/entry.py` already does this — keep it first), before anything else runs; otherwise the child re-executes the app instead of the worker.
* **(9)** Title / author / outline titles / file-name fallback are sanitised (`structure.clean_text_field`: lone surrogates,
  C0/C1 controls, zero-width and bidi-override chars removed, whitespace collapsed); an empty result falls through to the
  next candidate, finally "Untitled". Extracted body text also drops lone surrogates.
* **(11)** `structure.safe_url`: http(s)/ftp/mailto only; host IDNA-encoded and validated, path/query/fragment
  percent-encoded (existing %XX kept, stray % → %25), user info dropped, control chars removed; invalid → link dropped.

## OCR structure fix (frozen-binary report: body lines as h1/h2, a chapter per page)

* `ocr.line_size_px`: line size = median over words of box height / glyph-zone share (x-height, ascender/cap/accent,
  descender, both). Body-line jitter ~30 % → ≤ 11 % on the French excerpt.
* OCR headings need strong evidence (≥1.3× body and ≥2 pt, ≤2 lines, title-shaped, whitespace above or centred);
  chapters never split on OCR headings unless strong (≥1.5×, centred, ≤60 chars) or there is an outline.
* Running-head keys ignore a folio on either side; short documents (<20 pages) need 3 occurrences for misread matching.
* scan-only-en: 37 → 1 chapters, 37 → 1 headings; scan-only-fr: 11 → 1 chapters, 23 → 1 headings, running head removed,
  mid-sentence breaks 143 → 0 /1000. Details in tests/corpus/REPORT.md ("Round 2").
* pypdfium2 >= 5.14 logs "Explicitly closing <PdfBitmap … @ foreign>. This is a potentially unsafe operation!" on
  `close()` of pdfium-allocated bitmaps. Core now copies the pixels out, sets `bm.warn_on_close = False` (the documented
  opt-out for safe closes) and closes under PDFIUM_LOCK (`pdfminer_backend._copy_and_free`): no console output, and
  no GC finaliser on other threads. Binaries built before this change still print it, so rebuild.
* Corpus regression targets: `test_ocr_structure.py::test_real_scanned_excerpts_are_not_split_into_chapters` runs
  scan-only-en / scan-only-fr when `tests/.corpus` and tesseract eng / fra data exist (skipped in the Docker image).
