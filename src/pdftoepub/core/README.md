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
   **Formulas** (`formulas.py`, born-digital pages, right after extraction). Spans set in a math font (CMMI/CMSY/CMEX,
   AMS, Euler, STIX/Cambria/Latin Modern Math, MathJax, Symbol, …) are flagged `Span.math`. A row cut by inline math is
   rejoined; a numerator and a denominator aligned with each other around a text line's middle become `a/b` in that line
   (parenthesised when compound; also when the PDF library already put them in the line as super/subscripts); a lone small
   fragment above/below becomes a superscript/subscript; operators are placed by rule, since math-font metrics give them
   boxes a row too low. The remaining fragments are grouped into vertical clusters between text lines, one per displayed
   equation (rows holding a relation sign); a cluster with math evidence (math font, operators, Greek, scripts, stacking) is
   a display formula: one row → a `dmath` text line; stacked / radical / big operator → a 200 dpi grey-scale crop
   (`ImageItem` kind `formula`, PNG ≤1600 px) whose alt text is the linearised formula. The crop may reach halfway to the
   neighbouring lines (never into their boxes, at most 1 em past the formula's glyph boxes); within that it starts at the
   glyph boxes and grows while a border row/column still has ink (CMEX delimiters and radicals reach past their metric
   boxes), plus a quarter em of white. A cluster beside which a text line continues the row is inline math, not a
   display formula. The equation number `(12)` stays
   text, and a connecting word beside it ("or") is kept before it. A column of values beside row labels is a table, not a
   formula. `structure.inline_display_math` puts each display formula inside the paragraph that introduces it
   (`<span class="dmath">`, centred block; `<img class="formula" style="width:…em">` scales with the reader's font) and
   continues that paragraph with the next one unless it is indented or a new sentence. No MathML.
2. **OCR** (`ocr.py`, `pipeline._extract_all`). Per page: `ocr="force"` → always; `"auto"` → page with <20 text chars and a
   scan-like image (or a garbage text layer: U+FFFD / private-use ratio, low alphabetic ratio); `"off"` → never.
   Missing tesseract or language data → warning, scanned pages kept as images. Languages are validated against
   `tesseract --list-langs`. OCR font sizes are rescaled so the OCR body size equals the native body size. On OCR pages and
   OCR-layer pages, line sizes within 15 % of the page's body size are snapped to it (glyph-box sizes jitter by 10–15 %, which
   would otherwise split every paragraph).
   Scanned pages with little text (< 150 characters) keep their page picture only if it shows more than specks outside
   the text lines: blank pages, a picture of text the layer already holds and uniform layers (an all-black mask) go. A
   mostly dark page (white on black part dividers) is judged inside its dark block, inverted, and read again by
   tesseract when OCR is allowed (its text replaces the layer's when at least as long).
   Words: when a page's layer has its own space glyphs (OCR layers such as ABBYY FineReader's, word processors), they are
   the word boundaries; a space is added only where a gap is well above the line's letter spacing (both backends;
   pdfminer's gap-based spaces would split letter-spaced small type into "B e r n a r d"). Conservative OCR
   corrections (`ocrfix.py`, OCR'd books only): fixed patterns ("lbid", "Tbe", "xixᶜ siècle", spaced or misread digits in
   years / page numbers) and words whose `î`/`ï`/`i` or `rn`/`m` variant, or camel-case split ("ofCalifornia"), occurs
   ≥3 times in the book while the original occurs at most once.
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
   lines, images, figures and tables, so spanning titles and figures stay in place. A gap with running text on both sides
   (≥3 lines of ≥25 characters each side) is cut first, as the column gutter, before any gap between table cells inside a
   column. Horizontal cuts between two bands without a full-width element (title, author block, wide figure/table, caption)
   are undone when the merged band has such a gutter, so two-column text is split into columns as a whole between
   full-width elements (not row by row, which glued a left-column line to a right-column table row).
   `detect_columns=False` disables vertical cuts.
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
   strong (≥1.5× body, centred, ≤60 chars).
   **Scanned books** (`openings.py`; no outline and ≥8 pages, mostly OCR): chapters come from the page layout — an opening
   page starts lower than usual (≥3 % of the page height below the median text top), with short centred capitalised lines
   above a paragraph; labels (`CHAPTER IV`, `Chapitre premier`, `LIVRE II`, `II.`) and size add evidence; a half-title page
   with the same title (fuzzy) before it marks a chapter and is dropped; the book title or a book-wide running head repeated
   above the chapter number is skipped; a roman numeral misread by OCR is repaired from its neighbours (I., II., `BE:` →
   III.). A printed table of contents (lines ending in page numbers, or headed TABLE / CONTENTS) is matched fuzzily; the
   printed→PDF page offset voted by ≥2 matches confirms openings and finds the ones the layout missed. Openings count only
   if there are ≥3 (or ≥2 confirmed by the TOC). Openings after a half-title (or ≥1.3× body when others are ≤1.15×) are
   chapters and the others level-2 sections when both kinds exist; roman numerals alone on a centred line mid-page are
   numbered parts. Other OCR headings then never split chapters. OCR lines are never headings on pages with < 150
   characters (title pages, bookplates, plates), before the first planned chapter, or when shaped like noise (< 60 %
   letters, a word glued across a case change: "MeeISLAND").
   **Printed table of contents** (`printedtoc.py`; no outline): a "Sommaire" / "Table des matières" / "Contents" page in
   the first or last 15 pages, rows ending in page numbers (rows are re-assembled from the page-number column), parsed
   into parts ("Deuxième partie" + title), numbered chapters ("5." + author line + title lines) and other entries
   ("Introduction", "Épilogue"); section lists printed under a chapter in smaller type ("A | B | C") become its sections.
   The printed → PDF offset is voted from the folios read in the running heads (before they are removed), else from the
   titles found at the top of pages. Used only when it shows structure (≥3 numbered chapters or ≥2 parts; a flat list
   such as Zola's TABLE leaves the scanned-book openings in charge): the contents pages are dropped, each entry's opening
   page gets one `h1` (multi-line title merged, "N. " in front, the body's or the contents' wording, whichever has the
   words more frequent in the book), author lines become `<p class="byline">`, front-matter headings become paragraphs,
   and the entries split the book like an outline: parts and unnumbered entries level 1, chapters inside a part level 2
   (nested in the navigation), sections below. Content before the first
   chapter becomes a front-matter chapter titled with the book title. Very long chapters (>400 k chars) are split. Inside a chapter the
   title is `h1` and the other heading ranks are re-mapped to h2–h4.
   **Endnotes** (`endnotes.py`): a "Notes" heading (larger than the type below it) opens a region running to the next
   heading ("Bibliographie", the next chapter); its lines, with those the page-footnote detector took from the page
   bottoms, are put in reading order (page, column, height; OCR rows glued across the column gap are cut at the gutter)
   and cut into notes where a line starts with the next number (a jump of up to 8 is accepted after a finished note:
   lines the OCR layer lacks). The region becomes one `<section epub:type="endnotes">` with an `<ol>` (`value` = the
   printed number); superscript numbers between the previous notes section and this one link to it (first occurrence),
   and each linked note links back.
10. **Links**. External `http(s)/mailto/ftp` kept (invalid URL characters percent-encoded); internal GoTo links are resolved to the nearest block on the target page
    (`file.xhtml#id`); ids are only emitted for referenced blocks.
11. **EPUB** (`epub.py`). Metadata from options → PDF info → the first pages (`frontmatter.py`: largest type on the
    cover / title page confirmed by a second page or a running head, or display type on pages 1–3; editors after
    "Volume coordonné par" / "Sous la direction de" / "Edited by" as `dc:creator` role `edt`; publisher and year from
    "© X, 2017"; ISBN with a valid check digit → `dc:identifier urn:isbn:…`, also from the file name) → first h1 → file
    name without download-site prefixes and ISBN. A placeholder author ("anonymous") is ignored. PDF text strings are decoded as written (UTF-16 / UTF-8 with a
    byte-order mark, UTF-8 without one, else PDFDocEncoding) and mojibake from a wrong decoding is repaired. Page list: when the
    folios agree on one printed → PDF offset (or the contents fixed it), an empty `epub:type="pagebreak"` marker opens
    each printed page (inside a paragraph that runs across the break) and the navigation gets a `page-list`. Language: option → stopword detection (en, fr,
    es, de, it, pt, nl). Cover = JPEG snapshot of page 1, declared with `properties="cover-image"` but **not** in the spine (no image-only
    chapter). CSS uses only `em`/`%`/unitless values; `body` has no `font-size`. The first-run result passes epubcheck 5.4.

## Errors and warnings

`ConversionError` (user-safe messages) for: unreadable/not a PDF, empty file, no pages, password protected, nothing extractable,
and any unexpected exception (wrapped, with `__cause__`). Everything page-local (bad page, failed OCR, missing tesseract, missing language
data, undecodable image) becomes an entry in `ConvertResult.warnings`. PDF access is serialised with a process-wide lock because MuPDF / PDFium are
not thread-safe; analysis and packaging run outside it.

## Known limits

* A printed table of contents is used only when it has numbered chapters or parts; otherwise (born-digital books with an
  outline, flat lists) it stays as paragraphs. Its titles keep OCR misreads when the body's wording is not better.
* Endnotes: notes the OCR layer lacks are missing; a superscript misread as a letter, or a reference set without a
  superscript ("word23"), is not linked.
* Mathematics: no MathML. Two-dimensional display formulas are pictures (alt text = linearised formula; glyphs whose
  ToUnicode maps are wrong, e.g. a CMEX radical read as "r", show up in the alt text); stacked inline fractions become
  `a/b`; matrices, multi-line aligned equations and inline formulas that are not fractions or scripts stay flat text.
* Scanned books: chapters need a page-opening layout (sink + centred title) repeated ≥3 times, or ≥2 of them confirmed by a
  printed TOC (which also finds a missed opening at the top of its page); a chapter starting mid-page is not split off (a
  roman numeral alone on its line becomes a part heading). Titles keep their OCR misreads ("DI^] LA CRITIQUE").
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
