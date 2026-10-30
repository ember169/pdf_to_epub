# pdftoepub.core

`pipeline.run(pdf_path, epub_path, options, progress) -> ConvertResult` (called by `pdftoepub.api.convert`).
Output is a **reflowable EPUB 3** with real text: `<h1>`–`<h4>`, `<p>`, lists, tables, blockquotes, footnotes, inline
images. Page images are only used as a last-resort fallback for pages whose text cannot be recovered (OCR off or
unavailable), with a warning in `ConvertResult.warnings`.

```
backends/     PDF libraries behind one interface (base.py): `open(path) -> PdfDocument` with metadata(), toc(),
              extract_page(pno, ...) -> PageData, render_page(pno, dpi) -> PIL image, close()
  pdfminer_backend.py  DEFAULT (MIT-clean): pdfminer.six for text/fonts/geometry/outline/links/ruled tables,
                       pypdfium2 for embedded images, vector-figure / OCR / cover rendering
  pymupdf_backend.py   OPTIONAL (AGPL): the only module that imports pymupdf; used only with PDFTOEPUB_BACKEND=pymupdf
  common.py            backend-independent helpers (ImageStore, image encoding, span styling from font names, row-fragment
                       merging, grid -> table, vector-figure clustering/filtering, cover)
  __init__.py          get_backend(): $PDFTOEPUB_BACKEND = auto (= pdfminer) | pdfminer | pymupdf (falls back + warning if missing)
tables.py     borderless (whitespace-aligned) table detection on extracted lines
ocr.py        Tesseract through a subprocess (TSV output); pages are rendered at 300 dpi
layout.py     header/footer removal, footnote zones, XY-cut reading order, paragraph splitting  -> RawBlock
structure.py  RawBlock -> IR blocks (headings, lists, quotes, pre, tables, figures), dehyphenation, chapters, links
epub.py       hand-written EPUB 3 packager (mimetype stored first, nav.xhtml, content.opf, toc.ncx, style.css)
ir.py         dataclasses (see below)
pipeline.py   orchestration, progress events, error mapping, metadata
_samples/     reportlab generators for the synthetic test PDFs (`python -m pdftoepub.core._samples.make_samples DIR`)
tests/        pytest suite, run once per backend: `pytest src/pdftoepub/core/tests`
```

## IR (`ir.py`)

* Page level: `PageData(lines: list[Line], images: list[ImageItem], tables: list[TableItem])`;
  `Line(spans: list[Span], bbox)`; `Span(text, size, bold, italic, sup, sub, mono, bbox, link)`.
  Coordinates are PDF points, origin top-left. OCR pages produce the same `Line`/`Span` objects.
* Document level: `Document(title, author, language, chapters, images, cover)`;
  `Chapter(title, blocks, footnotes, sections)`; blocks are `Paragraph(runs, kind="p"|"blockquote"|"pre")`,
  `Heading(level 1..4, runs)`, `ListBlock(ordered, items)`, `Table(rows, header)`, `Figure(image_id, alt, caption)`;
  inline `Run(text, bold, italic, sup, sub, mono, link, noteref)`; `Footnote(id, marker, runs, orphan)`.
  `Run.link` is `("url", href)`, `("page", n, y)` (resolved to `("anchor", id)` once chapters exist).

## Pipeline and heuristics

1. **Extract** (`backends/`). Lines are kept only if horizontal (watermarks / rotated margin text dropped). Pages are analysed in their native orientation (`/Rotate` ignored, as PyMuPDF does).
   The notes below describe the PyMuPDF backend; the pdfminer backend yields the same IR:
   Fragments of one visual line are glued. Bold/italic/mono come from font flags **and** font-name patterns; superscript is
   "smaller than the line and raised" or the PDF flag. Links are attached to spans by rectangle hit-test (pdfminer: per character, so link text becomes its own span).
   pdfminer specifics: font flags come from the font descriptor (ForceBold / FontWeight / ItalicAngle / FixedPitch) captured in a custom device;
   super/subscripts use the text-rise-corrected baseline; unmapped glyphs `(cid:N)` are dropped and counted (`PageData.bad_chars`, feeds the
   garbage-text OCR trigger), except a lone one on its own line, which is a detached bullet and becomes `•`; ruled tables are rebuilt from
   LTLine/LTRect segments (complete grids only); images come from pypdfium2 page objects (rendered with their mask/transform, deduplicated by raw
   stream hash).
   Text clean-up (both backends): ligatures expanded; private-use code points that fonts' ToUnicode maps give for small
   caps mapped back to letters (Adobe U+F721–F7FE, Linux Libertine/Biolinum U+E051–E06A) and Symbol tall-delimiter pieces
   (U+F8EB–F8FE) collapsed to one `( [ { } ] )`; spacing accents drawn before the letter by old TeX OT1 fonts are composed
   (`esp`ece` → `espèce`, `fa¸con` → `façon`). Invisible OCR layers (Tesseract's `GlyphLessFont`, used by the Internet
   Archive and OCRmyPDF) never count as bold/italic/monospace and their pages are flagged `PageData.ocr_layer`. pdfminer: rotated
   glyphs (plot axis labels) are dropped like PyMuPDF's non-horizontal lines; a drop cap that pdfminer puts on the first text line
   gets the line's size and does not stretch the line's height.
   **Per-page budget (pdfminer)**: content-stream interpretation of one page is limited to `PDFTOEPUB_PAGE_TIMEOUT` seconds
   (default 60) and 150 000 glyphs; paths beyond 50 000 are ignored. Over budget, the page is kept as a 110 dpi picture with a
   warning instead of stalling the job.
   Images: dedup by xref and content hash, alpha/soft-mask merged, CMYK→RGB, downscaled to ≤1600 px, JPEG or PNG.
   Rotated/flipped images and images without xref are rasterised from the page instead. Vector drawings
   (`cluster_drawings`) with little text inside are rasterised at 200 dpi and become figures; the text inside is dropped — except
   shaded or framed text boxes (≤6 shapes, one covering the whole cluster: code listings, callouts), which stay text.
   Full-page images on pages that have a text layer (searchable scans) are ignored. Ruled tables come from
   `find_tables(use_layout=False)` (PyMuPDF) or from rule segments (pdfminer); cell text is rebuilt from our own spans.
2. **OCR** (`ocr.py`, `pipeline._extract_all`). Per page: `ocr="force"` → always; `"auto"` → page with <20 text chars and a
   scan-like image (or a garbage text layer: U+FFFD / private-use ratio, low alphabetic ratio); `"off"` → never.
   Missing tesseract or language data → warning, scanned pages kept as images. Languages are validated against
   `tesseract --list-langs`. OCR font sizes are rescaled so the OCR body size equals the native body size. On OCR pages and
   OCR-layer pages, line sizes within 15 % of the page's body size are snapped to it (glyph-box sizes jitter by 10–15 %, which
   would otherwise split every paragraph).
3. **Header/footer removal** (`layout.remove_running`). Lines/images in the top/bottom 15 % of the page whose normalised text
   (digits → `#`, spaces removed) recurs on a chain of ≥3 pages (gaps ≤2, so alternating verso/recto heads work) at about the same height
   and are not larger than 1.2× body size. Chapter-opening lines are kept (never on neighbouring pages / larger). Isolated page numbers in the
   outer 9 % are removed even when unique, and so is any short margin line on the same row as a page number or as a
   chained running head (short chapters break the verso/recto chain; chapter names in the head change every chapter).
4. **Footnotes** (`layout.split_footnotes`). Small-size lines (≤0.94× body) in the lower half starting with a marker
   (`1`, `*`, `†`, `¹`…). A note is accepted when a superscript with the same marker exists on the page; otherwise when a flow
   holds ≥2 consecutive numbered notes (`orphan`, listed at the end of the chapter without a link). Output:
   `<a epub:type="noteref">` + `<aside epub:type="footnote">` in a `<section epub:type="footnotes">` at the end of the chapter.
5. **Reading order** (`layout.xycut`). Recursive XY-cut: vertical cuts on x-gaps ≥ max(7 pt, 0.6×body) (both sides need ≥2
   items; narrow numeric columns like TOC page numbers are not columns), else horizontal cuts at gaps ≥0.3×line height. Items include
   lines, images, figures and tables, so spanning titles and figures stay in place. `detect_columns=False` disables vertical cuts.
6. **Paragraphs** (`layout.split_flow`). The typical leading is measured between a line and the next line below it in the same
   column. Lines are joined into one visual row only when they are side by side (disjoint in x).
   A new paragraph starts on: size/bold/mono change, vertical gap > typical leading+0.28 em,
   first-line indent (when the previous line ended a sentence or was short), bullet/number marker, a short line ending a sentence, or
   two differently-aligned centred lines. Drop caps are merged back. Paragraphs split by a column or page break are re-joined
   (`structure.merge_across_breaks`) when the first part has no terminal punctuation and the second is not indented, also across
   up to two figures/tables placed at the break when the continuation starts lower case.
7. **Dehyphenation** (`structure.join_runs`). Line-end hyphen is removed when the joined word occurs elsewhere in the document, or
   the next fragment starts lowercase; kept when the same hyphenated compound occurs mid-line elsewhere, before an uppercase letter
   (`Jean-Pierre`) or before French inversion pronouns (`est-il`). Soft hyphens always vanish.
8. **Structure** (`structure.py`). Body size = character-weighted mode. Heading candidates are blocks of ≤4 lines larger than
   1.12× body, or entirely bold single-line blocks (on OCR pages: ≥1.3× body and ≥2 pt larger, ≤2 lines, title-shaped — not
   starting lower case, not ending with a hyphen/comma or mid-word — and set apart by whitespace above or centring;
   OCR line sizes are the median over words of box height ÷ the glyph zones the word's letters cover); sizes are clustered (±0.75 pt) and ranked into h1–h4. Sizes that carry >15 % of
   the text are not heading sizes. Lists: consecutive `•`/`-`/`1.`/`a)` paragraphs (numbers must increase by 1; en/em dashes are
   left alone because they usually mark dialogue). Blockquote: ≥2 lines indented ≥1.4 em, not centred. Code: a line is monospace when ≥80 % of its characters are (font name patterns — Courier, Mono, Consolas, Menlo, Monaco, Inconsolata, Source Code, Fira Code, Hack, … —, font-descriptor FixedPitch flag, and on pdfminer a fixed-advance check: narrow `il1.` and wide `mw` glyphs with the same advance). Consecutive code lines (blank lines and indentation changes included, gap ≤3 em) form one block rendered `<pre><code>` with geometric indentation, blank lines and column alignment preserved, no dehyphenation or joining; blocks split by a page/column break are re-joined. Inline monospace spans in prose become `<code>`. CSS: `pre {white-space: pre-wrap; overflow-wrap: anywhere}`.
   Captions starting with Figure/Table/… after an image become `<figcaption>`.
   Tables: ruled (PyMuPDF) or borderless (aligned short cells, ≥3 rows, uniform size, not sentence-like; prose lines — ≥35
   chars, ≥6 words, one cell — are never cells, so a table in one column does not swallow the other column).
9. **Chapters**. PDF outline when present: split at the first level with ≥2 entries (one level deeper if that still averages ≥4 pages
   per chapter); each entry is located by matching a heading block of that page by title, else by destination y, else page start. Deeper
   entries become nav sub-sections. Without outline: split at the smallest heading level occurring ≥2 times, never on OCR-derived headings unless they are
   strong (≥1.5× body, centred, ≤60 chars). Content before the first
   chapter becomes a front-matter chapter titled with the book title. Very long chapters (>400 k chars) are split. Inside a chapter the
   title is `h1` and the other heading ranks are re-mapped to h2–h4.
10. **Links**. External `http(s)/mailto/ftp` kept (invalid URL characters percent-encoded); internal GoTo links are resolved to the nearest block on the target page
    (`file.xhtml#id`); ids are only emitted for referenced blocks.
11. **EPUB** (`epub.py`). Metadata from options → PDF info → first h1 → file name. Language: option → stopword detection (en, fr,
    es, de, it, pt, nl). Cover = JPEG snapshot of page 1, declared with `properties="cover-image"` but **not** in the spine (no image-only
    chapter). CSS uses only `em`/`%`/unitless values; `body` has no `font-size`. The first-run result passes epubcheck 5.4.

## Errors and warnings

`ConversionError` (user-safe messages) for: unreadable/not a PDF, empty file, no pages, password protected, nothing extractable,
and any unexpected exception (wrapped, with `__cause__`). Everything page-local (bad page, failed OCR, missing tesseract, missing language
data, undecodable image) becomes an entry in `ConvertResult.warnings`. PDF access is serialised with a process-wide lock because MuPDF / PDFium are
not thread-safe; analysis and packaging run outside it.

## Known limits

* No real table-of-contents page reconstruction (printed TOC pages stay as paragraphs with `…` leaders).
* Borderless tables and nested lists are best effort; multi-line table cells in borderless tables end the table.
* Footnote reference detection needs superscripts; plain "word23" references are not linked (notes then go to the chapter end as `orphan`).
* Text in right-to-left scripts, vertical text and rotated pages are not handled specially.
* Scanned documents: only layout structure derivable from text size/position (no bold/italic from OCR); headings need a visibly larger size.
* Floating images with text wrap are placed between paragraphs, not wrapped.

## Backends: measured differences (pdfminer default vs PyMuPDF)

Real-world corpus (18 PDFs from arXiv / Gutenberg / Internet Archive, both backends, before/after metrics): see
`tests/corpus/REPORT.md`. Summary after this round: same text coverage (word recall 0.966 vs 0.966, 0 epubcheck errors), PyMuPDF
~25 % faster and a little better on two-column reading order, pdfminer better on Internet Archive OCR text layers and lighter
on memory. The older measurements below were made on synthetic fixtures and one book.

Synthetic PDFs (book with outline, no outline, two columns + footnotes + image, vector figure, rotated page, scans, all 11 fixtures of
`tests/`): identical output (same element counts, word-sequence similarity 1.000). The only real-world file available (420-page French
academic paperback, OCR'd scan with text layer, no outline): word-sequence similarity 0.998, same chapter/image counts, heading counts
141 vs 142, lists 50 vs 64, blockquotes 104 vs 103, footnote-style notes 219 vs 166, borderless tables 2 vs 0; speed 35 s vs 28 s
(pdfminer is ~25 % slower on text-heavy pages; pypdfium2 rendering is on par). Known pdfminer-specific weaknesses: no built-in table
finder (only complete ruled grids and the shared borderless heuristic), character-level layout is slower on very dense pages, fonts without
descriptors rely on name patterns for bold/italic, unmapped glyphs on Type3 fonts are lost.
