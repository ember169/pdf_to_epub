# pdftoepub — Specification

Goal: a self-hostable tool that converts a PDF into a **reflowable EPUB 3** (real text, headings, paragraphs,
images inline) — NOT page images. Text must scale with the reader's font size / screen. Exposed through a web front.

## Decisions (made by master session, 2026-10-29)

| Topic | Decision |
|---|---|
| Language | Python 3.12+ (dev machine has 3.14; Docker image pins 3.12) |
| License | **MIT** (project owner's decision, 2026-10-29). Every mandatory dependency must be permissive (MIT/BSD/Apache). PyMuPDF is AGPL → only allowed as an OPTIONAL backend (`pip install pdftoepub[pymupdf]`), never a hard dependency, never imported at module top-level outside `core/backends/pymupdf_backend.py`. |
| PDF parsing | Backend interface (`core/backends/base.py`) yielding per-page lines/spans (font name, size, bold/italic, bbox) + images. **Default backend (MIT-compatible): `pdfminer.six` (MIT) for text/fonts/bboxes + `pypdfium2` (Apache-2.0/BSD) for page rendering, image extraction fallback and OCR rasterisation.** Optional backend: PyMuPDF (faster, better), auto-selected if installed unless `PDFTOEPUB_BACKEND` says otherwise. Do NOT use `pymupdf4llm`. |
| OCR (scanned pages) | Tesseract via `pytesseract`-free subprocess or PyMuPDF OCR; only for pages with no text layer; optional, languages configurable (default `fra+eng`). Must degrade gracefully if tesseract missing. |
| EPUB writing | Hand-written EPUB 3 packager (zipfile + templates). No ebooklib. `mimetype` first & stored, nav.xhtml, OPF, NCX fallback, one XHTML per chapter, CSS with relative units only (`em`, `%`), no fixed px widths. |
| Web backend | FastAPI + uvicorn, in-process job queue (thread pool), job state on disk under `DATA_DIR`. |
| Web front | Single static page (vanilla HTML/JS/CSS, no build step) served by FastAPI. Drag-and-drop upload, progress, download, options (OCR on/off, language, title/author). |
| Deploy | Docker (multi-stage, non-root, tesseract-ocr + fra/eng langs installed) + docker-compose. Config via env vars. |
| Validation | `epubcheck` (jar in Docker/test image) must pass on every generated fixture. |

## Layout (ownership = which session may write where)

```
pyproject.toml                      master
SPEC.md                             master
src/pdftoepub/__init__.py           master (public API re-export)
src/pdftoepub/api.py                master (contract, frozen)
src/pdftoepub/core/                 SESSION core  — extraction, layout analysis, OCR, EPUB writer
src/pdftoepub/web/                  SESSION web   — FastAPI app, job manager, static/ front
src/pdftoepub/cli.py                SESSION web   — `pdftoepub in.pdf -o out.epub` and `pdftoepub serve`
deploy/ Dockerfile docker-compose.yml  SESSION deploy
tests/                              SESSION deploy (fixtures generator + epubcheck harness + e2e)
```

## Frozen contract (`src/pdftoepub/api.py`)

```python
convert(pdf_path, epub_path, options: ConvertOptions = ConvertOptions(),
        progress: Callable[[ProgressEvent], None] | None = None) -> ConvertResult
```
`ConvertOptions`: title, author, language, ocr ("auto"|"off"|"force"), ocr_langs, drop_headers_footers(bool, default True),
detect_columns(bool, default True), image_mode ("inline"|"none"). `ProgressEvent`: stage, page, total_pages, message.
`ConvertResult`: epub_path, title, page_count, chapter_count, ocr_pages, warnings.
Core implements `pdftoepub.core.pipeline.run(...)`; `api.convert` delegates to it. Web/CLI only ever call `api.convert`.

## Core pipeline requirements (SESSION core)

1. **Extract** per page: text blocks→lines→spans with font name, size, bold/italic flags, bbox; embedded images with bbox.
2. **Clean**: remove running headers/footers & page numbers (repeated text at same y-position across pages); dehyphenate
   line-end hyphens; join lines into paragraphs using vertical gaps + indentation; merge paragraphs that continue across pages.
3. **Reading order**: handle multi-column pages (XY-cut or column clustering); footnotes kept at end of the chapter or as EPUB3 `epub:type="footnote"` if detectable.
4. **Structure**: body font size = mode; headings = larger/bold clusters mapped to h1–h3; use PDF outline (bookmarks) as ground truth for chapters when present, else split on h1. Lists (bullets/numbers), blockquotes (indented), simple tables → real `<table>` (fallback: preformatted text).
5. **Inline**: bold/italic as `<strong>/<em>`, superscripts, links (internal → anchors, external → hrefs).
6. **Images**: extract embedded raster images (dedupe, recompress large ones to ≤ 1600px), place inline at correct position with `max-width:100%`. Vector figures: rasterise the region (PNG, 200dpi) as fallback.
7. **OCR**: pages with no/garbage text layer → render 300dpi → tesseract → same IR as native text.
8. **EPUB out**: metadata from PDF info (overridable), cover from page 1 (image), nav + NCX from chapters, `dc:language` detected or option, CSS using `em/%` only and `font-size` NOT set on body (inherit reader's setting).
9. Never crash on malformed PDFs: warnings in `ConvertResult.warnings`; raise `ConversionError` for unrecoverable (encrypted without password, not a PDF).

## Web API (SESSION web)

- `POST /api/jobs` multipart (`file`, options JSON) → `{id}` (limit `MAX_UPLOAD_MB`, default 100; reject non-PDF by magic bytes)
- `GET /api/jobs/{id}` → `{status: queued|running|done|error, stage, page, total_pages, warnings, error}`
- `GET /api/jobs/{id}/events` → SSE progress stream
- `GET /api/jobs/{id}/download` → `application/epub+zip`
- `DELETE /api/jobs/{id}`; background janitor deletes jobs older than `JOB_TTL_HOURS` (default 24)
- `GET /healthz`. Env: `DATA_DIR`, `MAX_UPLOAD_MB`, `JOB_TTL_HOURS`, `MAX_CONCURRENT_JOBS`, `AUTH_TOKEN` (optional bearer for public hosting).
- Until `core` lands, web session develops against a stub: if `pdftoepub.core.pipeline` import fails, `api.convert` falls back to a trivial stub EPUB (provided by master in api.py).

## Definition of done

- `pdftoepub book.pdf -o book.epub` produces epubcheck-clean, reflowable EPUB with real text for text PDFs and scanned PDFs (with OCR).
- `docker compose up` serves the front on :8000; upload→progress→download works.
- Test suite: generated fixtures (single/two-column, headings, footnotes, images, scanned) + epubcheck + assertions that no chapter is image-only and body text is present.

## Decisions — round 2 (2026-10-29, "accessible to everyone")

- Portable binaries are built **locally only** (no CI): macOS arm64 (native), Linux arm64/x86_64 (Docker), Windows x86_64 (attempt via Wine in Docker; fallback `packaging/build.ps1`).
- **Tesseract (eng+fra) is bundled** in every binary; system tesseract is only a fallback. `THIRD_PARTY_LICENSES` ships with binaries.
- Launching the binary with **no arguments** starts the web UI on 127.0.0.1 and opens the browser (double-click use). Server binds loopback by default.
- Front: WCAG 2.2 AA, FR/EN, offline, batch upload, EPUB preview.
- Quality is measured on a public-domain corpus (arXiv / Gutenberg / Internet Archive) fetched into `tests/.corpus/` (never committed); metrics in `tests/corpus/REPORT.md`.
