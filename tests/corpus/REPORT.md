# Real-world corpus evaluation — conversion quality report

18 public-domain / openly licensed PDFs (98.5 MB, 3 362 pages) from arXiv, Project Gutenberg and the Internet Archive,
converted with both backends (pdfminer.six + pypdfium2 = default, PyMuPDF = optional), measured before and after the
fixes of this round. Reproduce:

```
python tests/corpus/fetch.py                      # downloads into tests/.corpus/ (git-ignored), verifies sha256
python tests/corpus/evaluate.py --label after     # ~35 min for both backends with epubcheck; results in tests/corpus/out/after/
python tests/corpus/evaluate.py --compare before after
python tests/corpus/evaluate.py --label main --src /tmp/main/src   # measure another checkout (git archive main src | tar -x -C /tmp/main)
```

## Corpus

| id | source | pages | MB | licence | what it exercises |
|---|---|---|---|---|---|
| fr-novel-roi-montagnes | Internet Archive (Bibebook edition) | 183 | 1.1 | CC BY-SA 4.0 | novel, french, dialogue, italics, outline |
| fr-novel-glebe | Internet Archive (Bibebook edition) | 42 | 0.7 | CC BY-SA 4.0 | novel, french, dialogue |
| fr-novel-chignole | Project Gutenberg #35150 | 102 | 0.3 | Public domain in the USA | novel, french, dialogue, generated-pdf |
| en-novel-my-antonia | Project Gutenberg #19810 | 308 | 3.4 | Public domain in the USA | novel, english, dialogue, italics, accents, outline |
| en-novel-puck | Project Gutenberg #26027 | 258 | 2.3 | Public domain in the USA | novel, english, poems, illustrations |
| arxiv-llama | arXiv:2302.13971v1 | 27 | 0.7 | CC BY 4.0 | paper, two-column, tables, figures, footnotes, ligatures, outline |
| arxiv-ligo | arXiv:1602.03837v1 | 16 | 0.9 | CC BY 4.0 | paper, two-column, math, figures, footnotes, long-author-list |
| arxiv-mistral | arXiv:2310.06825v1 | 9 | 3.7 | CC BY 4.0 | paper, figures, tables, code |
| arxiv-foundation-models | arXiv:2108.07258v3 | 214 | 14.4 | CC BY 4.0 | report, numbered-headings, lists, footnotes, figures, outline, long |
| arxiv-d2l | arXiv:2106.11342v5 | 1185 | 39.5 | CC BY-SA 4.0 | textbook, numbered-headings, lists, code, math, figures, tables, outline, very-long |
| pg-calculus-made-easy | Project Gutenberg #33283 | 292 | 1.3 | Public domain in the USA | textbook, math, numbered-chapters, ligatures, outline |
| pg-descartes-geometrie | Project Gutenberg #26400 | 82 | 0.6 | Public domain in the USA | french, math, old-typography, ligatures, figures |
| pg-galois | Project Gutenberg #40213 | 78 | 0.7 | Public domain in the USA | french, math, footnotes, outline, ligatures |
| ia-zola-roman-experimental | Internet Archive leromanexprime00zola | 436 | 18.5 | Public domain | scan, ocr-text-layer, french, long, running-headers |
| ia-island-plant | Internet Archive islandplantnantu00leem | 104 | 4.7 | Public domain | scan, ocr-text-layer, english, novel |
| ia-innkeeper-source | Internet Archive innkeeperstale00burr | 16 | 3.9 | Public domain | scan, ocr-text-layer, english, short |
| scan-only-en | derived from ia-innkeeper-source | 6 | 1.0 | Public domain | scan, image-only, ocr |
| scan-only-fr | derived from ia-zola-roman-experimental | 4 | 0.6 | Public domain | scan, image-only, ocr, french |

`scan-only-*` are image-only excerpts that `fetch.py` derives from two Internet Archive scans (pages rasterised and
rewrapped, so OCR is the only way to get text); they are scored against the IA text layer of the source pages.

## How it is measured

The reference is pypdfium2's text layer (neither backend reads text through pdfium), split into lines with per-glyph
boxes; the top/bottom 8 % of each page is the margin zone. All metrics are computed on normalised text (NFKC, lower case,
hyphenation and OCR-font accents undone on both sides). Full definitions are in the `evaluate.py` docstring. The main ones:

* **word / char recall & precision**: multiset overlap of alphabetic tokens / letters + digits, EPUB vs reference.
  Recall below 1 is expected, because running heads, page numbers and figure-internal text are removed on purpose.
* **order**: share of the reference's 6-word shingles (per page, margins excluded) found in the EPUB. It catches
  interleaved columns and lost or reordered lines. **order, 2-col** is the same measure on two-column pages.
* **mid-sentence breaks**: `<p>` ending without terminal punctuation followed by a `<p>` starting lower case, per 1000 paragraphs.
* **leftover hyphens**: `inter- national`, or `inter-national` when `international` is used elsewhere, per 10k words.
* **text in `<pre>`**: share of the text rendered as code blocks. **PUA**: private-use / U+FFFD characters left in the EPUB
  (they show as blank boxes without the PDF's font).
* **running-head / page-number leak**: share of recurring margin lines and folios still present in the text. Heads printed
  with their folio are matched exactly; other heads count only the excess over their body occurrences.
* **epubcheck 5.4** error count, **s/page**, and **peak RSS** of the conversion process (`wait4`).

Caveats: on the math books (Calculus, Galois, Descartes) numbers inside formulas make the page-number metric noisy and
display formulas count as "breaks". The French OCR excerpt is compared against another OCR engine (IA's), which is not
ground truth.

## Round 3: chapters of scanned books, mathematics, two-column order

"Before" is `main` at 9cb7528, re-measured now with the same evaluator as "after" (`--src` runs another checkout's
code; `--rescore` re-reads existing EPUBs). Numbers in rounds 1–2 below were produced by the older evaluator and are not
comparable with this section.

```
git archive 9cb7528 src | tar -x -C /tmp/main
python tests/corpus/evaluate.py --label r3-before --src /tmp/main/src
python tests/corpus/evaluate.py --label r3-after
```

### Measurement fixes first (both sides scored the same way)

* pdfium marks a line-end hyphen *inside* the word with U+FFFE (`continu` U+FFFE `ous`). The reference split such words, so
  every hyphenated line cost the EPUB two shingles it had right.
* The two-column page flag counted any narrow line: formula fragments and figure labels made 174 Calculus, 38 Descartes
  and 21 Galois pages "two-column". It now counts prose lines (≥25 characters). The real two-column pages are LLaMA's
  15 and LIGO's 9. **The 0.75 two-column mean of round 2 was mostly these two artefacts**: on unchanged `main`, the
  corrected measure gives LLaMA 0.956 / 0.865 (pdfminer / PyMuPDF) and LIGO 0.966 / 0.960.
* Words are runs of letters ("m1", "m 1" and "m<sub>1</sub>" are the same word, whichever way the extractor glues
  them); `<sub>`/`<sup>` are separate tokens; a formula picture counts as its alt text; "dx" is no longer a roman folio.
* New metrics: a hand-checked chapter list for the 3 Internet Archive books (manifest `chapters_gt`, checked on the page
  images: Zola 7 essays + 13 page-opening sections, Island 3 chapters, Innkeeper 1 story) with `ch_found` (level-1
  titles in the EPUB navigation), `sec_found` (level-2), `ch_spurious` (chapter files whose first heading is no GT
  title, beyond one front-matter file); `formula_imgs`; `sub_sup`.

Corpus means (18 documents, same evaluator both sides):

| mean | pdfminer before | pdfminer after | PyMuPDF before | PyMuPDF after |
|---|---|---|---|---|
| word recall | 0.983 | 0.983 | 0.984 | 0.984 |
| order (6-gram) | 0.941 | 0.948 | 0.946 | 0.950 |
| mid-sentence breaks /1000 ¶ | 48.1 | 35.7 | 60.5 | 41.8 |
| epubcheck errors (total) | 0 | 0 | 0 | 0 |

Novels and the other papers are unchanged to 3 decimals; the per-document table is in `out/r3-after/report.md`
(git-ignored, regenerated by the commands above).

### 1. Scanned books lose their chapters → `core/openings.py`

| doc | backend | GT chapters | chapters found (nav) | GT sections found | spurious chapter files | EPUB chapters | headings |
|---|---|---|---|---|---|---|---|
| ia-zola-roman-experimental | pdfminer | 7 | **1 → 7** | **0 → 13** / 13 | 0 → 0 | **3 → 9** | **13 → 45** |
| ia-zola-roman-experimental | pymupdf | 7 | 7 → 7 | **0 → 13** / 13 | 0 → 0 | **5 → 9** | **68 → 99** |
| ia-island-plant | pdfminer | 3 | **1 → 3** | – → – / 0 | 0 → 0 | **1 → 4** | **2 → 5** |
| ia-island-plant | pymupdf | 3 | **0 → 3** | – → – / 0 | 0 → 0 | **1 → 4** | **3 → 6** |
| ia-innkeeper-source | pdfminer | 1 | 1 → 1 | – → – / 0 | 0 → 0 | 1 → 1 | 4 → 4 |
| ia-innkeeper-source | pymupdf | 1 | 1 → 1 | – → – / 0 | 0 → 0 | 1 → 1 | 5 → 5 |
| scan-only-en | pdfminer | – | – → – | – → – / – | – → – | 1 → 1 | 1 → 1 |
| scan-only-en | pymupdf | – | – → – | – → – / – | – → – | 1 → 1 | 1 → 1 |
| scan-only-fr | pdfminer | – | – → – | – → – / – | – → – | 1 → 1 | 1 → 1 |
| scan-only-fr | pymupdf | – | – → – | – → – / – | – → – | 1 → 1 | 2 → 2 |

PyMuPDF's 7/7 "before" on Zola came from 68 headings that OCR size noise made (most of them body lines); the nav
had the essay titles among the noise but no chapter files for them (5 files, split by length).

How: an opening page starts lower than usual (≥3 % of the page height below the median text top) with short, centred,
capitalised lines above a paragraph. Label patterns (`CHAPTER IV`, `Chapitre premier`, `LIVRE II`, `II.`) and size add
evidence. A half-title page with the same title (fuzzy) marks a chapter; it is dropped. The book title or a book-wide
running head repeated above the number is skipped ("AN ISLAND PLANT." over "I. / THE ROOTS."). A misread numeral is
repaired from its neighbours (IA's OCR read "III." as "BE:"). The printed TOC (Zola's TABLE) is matched fuzzily: the
printed→PDF page offset, voted by ≥2 matches, confirms openings and finds one the layout missed. Openings count only
when there are ≥3 of them (or ≥2 confirmed by the TOC). Openings after a half-title (or much larger) are chapters and
the others are level-2 sections; a roman numeral alone on a centred line mid-page is a numbered part.

* scan-only-en / scan-only-fr stay at 1 chapter (6 and 4 pages: below the 8-page minimum, and one opening is not a pattern).
* Zola has 9 chapter files: front matter + 7 essays + the TABLE (a real division of the book, not in the ground truth).
* Titles keep their OCR misreads ("DI^] LA CRITIQUE").
* Tests: `test_scan_chapters.py`, with synthetic OCR-layer books (openings with a misread numeral; one centred title is
  not a pattern; short excerpts; half-titles → chapters vs sections; a printed TOC finding a missed opening; mid-page
  parts; fuzzy titles).

### 2. Mathematics → `core/formulas.py`

| doc | backend | mid-sentence breaks /1000 ¶ | order | word recall | formula pictures | sub/sup | epubcheck | s/page |
|---|---|---|---|---|---|---|---|---|
| pg-calculus-made-easy | pdfminer | **87.0 → 50.5** | **0.765 → 0.844** | **0.958 → 0.964** | **0 → 542** | **3422 → 2224** | 0 → 0 | **0.021 → 0.040** |
| pg-calculus-made-easy | pymupdf | **99.5 → 59.5** | **0.844 → 0.860** | **0.969 → 0.970** | **0 → 710** | **8955 → 1982** | 0 → 0 | **0.021 → 0.033** |
| pg-descartes-geometrie | pdfminer | **264.4 → 243.6** | **0.899 → 0.926** | **0.997 → 0.994** | **0 → 100** | **1172 → 587** | 0 → 0 | **0.031 → 0.045** |
| pg-descartes-geometrie | pymupdf | **232.3 → 113.3** | **0.935 → 0.924** | **0.996 → 0.990** | **0 → 103** | **2808 → 583** | 0 → 0 | **0.034 → 0.046** |
| pg-galois | pdfminer | **165.3 → 18.2** | **0.923 → 0.931** | **0.988 → 0.984** | **0 → 77** | **1102 → 791** | 0 → 0 | **0.018 → 0.025** |
| pg-galois | pymupdf | **156.3 → 9.4** | **0.939 → 0.938** | **0.987 → 0.985** | **0 → 76** | **1419 → 882** | 0 → 0 | **0.017 → 0.024** |
| arxiv-ligo | pdfminer | **17.2 → 17.4** | **0.978 → 0.977** | 0.986 → 0.986 | 0 → 0 | 1258 → 1258 | 0 → 0 | **0.126 → 0.135** |
| arxiv-ligo | pymupdf | **8.8 → 4.5** | 0.974 → 0.974 | 0.984 → 0.984 | 0 → 0 | **1285 → 1267** | 0 → 0 | **0.103 → 0.112** |

How (born-digital pages, right after extraction):

* Math-font spans are flagged (CMMI/CMSY/CMEX, AMS, Euler, STIX/Cambria/Latin Modern Math, MathJax, Symbol, …).
* Inline math: a row cut by inline math is rejoined. A numerator and a denominator, aligned around a text line's middle,
  become `a/b` in that line (parenthesised when compound), also when the PDF library has already placed them in the line as a
  super/subscript. A lone small fragment above/below becomes `<sup>`/`<sub>`. Operators are placed by rule, because
  CMSY metrics put "−"/"×" boxes a row too low.
* Display formulas: the remaining fragments form clusters between text lines, one per displayed equation. A cluster
  with math evidence is a display formula. A one-row formula stays text (a centred `<span class="dmath">`). A stacked
  formula, a radical or a big operator becomes a 200 dpi grey-scale PNG crop. Its alt text is the linearised formula
  ("dy/dx = 5/7 x^4."), the equation number `(12)` stays text, and a word printed beside it ("or") stays text before
  it. A column of values beside row labels (LIGO's Table I) is a table, not a formula.
* The display formula sits inside the paragraph that introduces it, and the following text continues that paragraph:
  the sentence is no longer cut in three.
* The picture's CSS width is set in em (scales with the reader's font size), with `max-width: 100%`. Largest picture on
  the corpus: 1077 × 535 px (cap 1600). epubcheck: 0 errors on every document.
* Price: EPUB size (Calculus 1.0 → 3.4 MB for 542 pictures; D2L +1.9 MB), conversion time (Calculus 0.021 → 0.040
  s/page), and memory on small math books (Descartes 140 → 201 MB, pdfminer: crops come from a cached full-page render).
* MathML: not attempted; the reader support is too uneven.
* Found on the way: pdfminer's region renders ignored a crop box inherited from the page tree (Project Gutenberg PDFs
  crop 20 pt per side). Crops were shifted by 20 pt, which cut the left of every formula and offset vector-figure
  pictures since round 1. Fixed in `_render_region`, test `test_region_render_follows_an_inherited_crop_box`. The
  PyMuPDF backend trusted MuPDF's superscript flag for whole runs of text ("x times the length…" in `<sup>`); it now
  trusts it for markers of ≤3 characters only.
* Tests: `test_math.py` (synthetic page: picture + alt + equation number + continuation, inline fraction, one-row
  formula, table column; pairing; operator placement; continuation; exponent ≠ footnote mark; crop box; Galois corpus
  test; epubcheck).

### 3. Two-column reading order → `layout.xycut`

| doc | backend | order, 2-col pages | order (all pages) | mid-sentence breaks |
|---|---|---|---|---|
| arxiv-llama | pdfminer | **0.956 → 0.973** | **0.967 → 0.978** | 5.3 → 5.3 |
| arxiv-llama | pymupdf | **0.865 → 0.949** | **0.905 → 0.962** | **9.2 → 3.0** |
| arxiv-ligo | pdfminer | 0.966 → 0.966 | **0.978 → 0.977** | **17.2 → 17.4** |
| arxiv-ligo | pymupdf | 0.960 → 0.960 | 0.974 → 0.974 | **8.8 → 4.5** |
| arxiv-mistral | pdfminer | – → – | 0.960 → 0.960 | 35.7 → 35.7 |
| arxiv-mistral | pymupdf | – → – | 0.960 → 0.960 | 12.3 → 12.3 |
| arxiv-foundation-models | pdfminer | – → – | 0.987 → 0.987 | **7.9 → 8.0** |
| arxiv-foundation-models | pymupdf | – → – | 0.986 → 0.986 | **42.5 → 42.7** |
| arxiv-d2l | pdfminer | – → – | **0.935 → 0.940** | **34.7 → 14.8** |
| arxiv-d2l | pymupdf | – → – | **0.947 → 0.952** | **36.1 → 10.9** |

The LLaMA page-4 failure was real: below the full-width Table 3, horizontal XY-cuts sliced the two-column region at
every blank row shared by both columns. One thin band then held a left-column bullet beside the cells of Table 4 in the
right column; the cell gaps outnumbered the gutter, and the line was glued across the columns ("…a textual description
GPT-3 175B 14.6 23.0 29.9 of the task…"). Now:

* Horizontal cuts between two bands without a full-width element (title, author block, wide figure/table, caption) are
  undone when the merged band has a gutter with running text on both sides. Two-column text is then split into columns
  as a whole between full-width elements.
* A gap with ≥3 prose lines on each side is cut first, as the gutter, before any gap between table cells inside a
  column.
* A merged band without such a gutter (a label / value table) keeps its old row-by-row cuts.
* Single-column documents are unchanged (novels identical to 3 decimals). Test: `test_columns.py` reproduces the LLaMA
  page (it fails on `main`).

### 4. Review of round 3: formula crops, Island navigation

```
python tests/corpus/evaluate.py --label r4-before --src <snapshot of the round-3 src> --ids <the 7 math docs>
python tests/corpus/evaluate.py --label r4-after --ids <the 7 math docs> ia-island-plant
```

New automatic check (`evaluate.py`, columns `crops / crop_bleed / crop_clip`): the conversion worker records where
each formula picture was cropped. The evaluator then checks each picture against pdfium's glyph boxes and its own
pixels:
* **bleed:** a glyph of another line reaches into the crop.
* **clipped:** the crop cuts one of the formula's own glyphs, or there is ink on a 1-px border row or column of the PNG.

"Before" is the round-3 working tree (`--src` snapshot), "after" is this code. Both are scored by the same evaluator.

| doc | backend | formula pictures | bleed | clipped (ink on the border) | mid-sentence breaks /1000 ¶ | order |
|---|---|---|---|---|---|---|
| arxiv-llama | pdfminer | 6 → 0 | 1 → 0 | 1 (1) → 0 (0) | 5.3 → 5.2 | 0.978 → 0.980 |
| arxiv-llama | pymupdf | 6 → 0 | 1 → 0 | 1 (1) → 0 (0) | 3.0 → 3.0 | 0.962 → 0.965 |
| arxiv-foundation-models | pdfminer | 1 → 1 | 1 → 0 | 1 (1) → 1 (1) | 8.0 → 8.0 | 0.987 → 0.987 |
| arxiv-foundation-models | pymupdf | 1 → 1 | 0 → 0 | 0 (0) → 0 (0) | 42.7 → 42.7 | 0.986 → 0.986 |
| arxiv-d2l | pdfminer | 470 → 453 | 145 → 16 | 217 (217) → 151 (150) | 14.8 → 15.3 | 0.940 → 0.940 |
| arxiv-d2l | pymupdf | 499 → 488 | 97 → 27 | 140 (140) → 144 (144) | 10.9 → 11.3 | 0.952 → 0.953 |
| pg-calculus-made-easy | pdfminer | 542 → 503 | 105 → 25 | 136 (136) → 80 (80) | 50.5 → 47.3 | 0.844 → 0.849 |
| pg-calculus-made-easy | pymupdf | 708 → 691 | 129 → 38 | 183 (183) → 123 (123) | 59.5 → 55.7 | 0.860 → 0.863 |
| pg-descartes-geometrie | pdfminer | 100 → 99 | 9 → 2 | 19 (19) → 10 (10) | 243.6 → 247.8 | 0.926 → 0.927 |
| pg-descartes-geometrie | pymupdf | 103 → 103 | 8 → 1 | 16 (16) → 7 (7) | 113.3 → 114.9 | 0.924 → 0.926 |
| pg-galois | pdfminer | 77 → 72 | 6 → 0 | 12 (12) → 0 (0) | 18.2 → 18.5 | 0.931 → 0.932 |
| pg-galois | pymupdf | 76 → 75 | 8 → 0 | 12 (12) → 1 (1) | 9.4 → 11.9 | 0.938 → 0.938 |
| **all** | pdfminer | 1196 → 1128 | **267 → 43** | **386 → 242** | | |
| **all** | pymupdf | 1393 → 1358 | **243 → 66** | **352 → 275** | | |

LIGO has no formula pictures. epubcheck reports 0 errors on every document.

The two reported cases are fixed (Calculus p.23 and p.34):
* **Bleed, p.23.** The cause was not the padding. pdfminer cuts the text row "…which is *y* − *dy*, will be…" around its
  "−", whose CMSY box hangs a row low. That stray "−" joined the display formula below, and its crop then reached up
  into the text line.
  * Now a text row cut around an operator standing in the gap is rejoined, with the "−" in place.
  * The equation "(y − dy)² = (181)² − …" is now one row of text with superscripts, not a picture.
* **Clip, p.34.** Fragment clustering depended on the order of the fragments. The top piece of the closing bracket
  ended up in a cluster of its own and was dropped as a lone symbol. The "×" of the denominator "1 × 2" was given to the
  next equation, whose box then clamped the crop.
  * Clusters are now built pairwise (union-find), so the order no longer matters.
  * An operator goes to the equation in whose row gap it stands, allowing for the CMSY shift. The same rule applies in
    `_rows` and in the alt text, which now reads "2(2 + 1)/(1 × 2)".

General crop rule (`formulas._formula` / `_trim`):
* The allowed region stops halfway to each neighbouring text line and to the other equations of the cluster. It never
  enters their boxes, and it extends at most 1 em past the formula's glyph boxes. Neighbour boxes leave out math-font
  operators, whose boxes hang a row low.
* Within that region, the crop starts at the glyph boxes and grows while a border row or column still has ink, which
  covers CMEX delimiters and radicals. It then adds a quarter em of white and grows again. The second pass takes in the
  Galois big parentheses, which have no text at all.
* A cluster whose row continues with a text line within 1 em is inline math, not a display formula (D2L's
  "• ∫ f(x) dx: integral" list).
* A cluster with no math font and no relation sign is table cells, not a formula. All 6 LLaMA "formulas" were table
  cells.
* I tried "halfway through the overlap" for loose font-metric boxes that overlap. It doubled the bleed, so I reverted it
  to the box edge.

Island navigation: the duplicate "‘THE RESULT OF DROUGHT AND WINTER." was the page's running head, on the first text
page after a run of plates. OCR had added a stray quote, so the running-head filter missed it, and it became a section
heading. Two fixes:
* An OCR heading that repeats the current chapter title (fuzzy match, 0.85) is dropped.
* An opening that repeats the previous opening's title is skipped.

The Island navigation is now front matter, I, II, III on pdfminer. On PyMuPDF it is front matter, the author, the book
title, then I, II, III; the two extra entries are unchanged from round 3.

Tests:
* `test_math.py`:
  * a synthetic page where the bracket's ink reaches past its glyph box, with a text line just above;
  * Calculus p.23 (the row is one line, crops have blank borders);
  * Calculus p.34 (bracket inside the crop, alt "(1 × 2)").
* `test_scan_chapters.py`: a repeated title as an opening, and as a mid-chapter OCR heading.

All of them fail on the round-3 code.

What is left (spot-checked by rendering the flagged crops):
* **Most remaining flags are detection errors, not boundary errors:**
  * a matrix cut into one picture per row (D2L);
  * a fraction split between two clusters (Calculus p.51);
  * an axis label of a graph taken for a formula (Calculus p.39, "dy/dx" with tick marks);
  * a Bayes formula whose left side was read as text (D2L p.111).
* **PyMuPDF's loose metric boxes** make neighbouring rows overlap. The crop then stops at the neighbour's box edge and
  can cut the formula's own descenders (Calculus p.23, PyMuPDF).
* **Descartes p.48:** the margin notes sit next to the equations.

### Could not improve (honestly)

* **Descartes** keeps ~240 (pdfminer) / ~113 (PyMuPDF) breaks per 1000 paragraphs. The rest are its marginal notes
  interleaved into the body ("…ainsi rapporte aux ¶ opérations de…"), not math. **Calculus** keeps ~50–60: worked
  examples whose fragments do not cluster cleanly, and exponent fractions (x^(1/2)) stacked inside a superscript.
* **LIGO's formulas are not detected**: its RevTeX/Adv fonts carry no math-font names and map "+" to "þ". The few
  display formulas stay flat text (unchanged; 0 pictures).
* **Alt text** is a best-effort linearisation. Nested exponents and CMEX glyphs whose ToUnicode is wrong (a radical sign
  read as "r") come out garbled. Matrices and aligned multi-line equations become one picture per row of equations, or
  flat text.
* **Two-column**: LLaMA PyMuPDF's title page (author block, 0.74) and LIGO's p.7 (Table I beside text, 0.90) are still
  below the rest.
* **Scans**: a chapter that starts mid-page is not split off. OCR-misread titles are kept as read. PyMuPDF on IA OCR
  layers still splits paragraphs (Zola 214 breaks/1000 vs 21 with pdfminer; unchanged).
* **Memory**: Zola peaked at 694 MB (pdfminer) in the "before" run and 1073 MB in the "after" run; run back to back, `main` and
  this code both peak at 1066–1069 MB, so that difference is run-to-run variation, not a regression. Peak memory on the IA
  scans varies by ±40 % between runs on this Mac.

## Headline numbers (round 1, older evaluator)

| metric (mean over 18 docs) | pdfminer before | pdfminer after | PyMuPDF before | PyMuPDF after |
|---|---|---|---|---|
| word recall | 0.966 | 0.966 | 0.964 | 0.966 |
| word precision | 0.984 | 0.984 | 0.983 | 0.984 |
| char recall | 0.988 | 0.989 | 0.988 | 0.989 |
| text in `<pre>` | 0.193 | 0.031 | 0.192 | 0.031 |
| PUA /10k chars | 1.84 | 0.04 | 1.99 | 0.04 |
| order (6-gram) | 0.884 | 0.886 | 0.885 | 0.890 |
| order, 2-col pages | 0.735 | 0.747 | 0.746 | 0.765 |
| mid-sentence breaks /1000 ¶ | 54 | 48 | 67 | 61 |
| leftover hyphens /10k words | 1.48 | 1.58 | 0.97 | 1.31 |
| running-head leak | 0.093 | 0.005 | 0.115 | 0.056 |
| page-number leak | 0.040 | 0.045 | 0.031 | 0.043 |
| outline titles in nav | 0.875 | 0.872 | 0.874 | 0.874 |
| headings / page | 1.072 | 0.347 | 1.218 | 0.489 |
| chapters / 100 pages | 67 | 15 | 76 | 24 |
| epubcheck errors (sum) | 1 | 0 | 1 | 0 |
| s / page | 0.144 | 0.129 | 0.106 | 0.097 |
| peak RSS MB (max) | 705 | 1054 | 917 | 1213 |

Same means without the three Internet Archive OCR-layer books (their 'before' output was entirely <pre>, which hides
paragraph-level problems):

| metric (mean over 15 docs) | pdfminer before | pdfminer after | PyMuPDF before | PyMuPDF after |
|---|---|---|---|---|
| word recall | 0.965 | 0.967 | 0.962 | 0.966 |
| word precision | 0.983 | 0.983 | 0.982 | 0.983 |
| char recall | 0.986 | 0.989 | 0.987 | 0.989 |
| text in `<pre>` | 0.032 | 0.038 | 0.033 | 0.038 |
| PUA /10k chars | 2.21 | 0.05 | 2.39 | 0.05 |
| order (6-gram) | 0.880 | 0.886 | 0.881 | 0.889 |
| order, 2-col pages | 0.735 | 0.747 | 0.746 | 0.765 |
| mid-sentence breaks /1000 ¶ | 65 | 47 | 81 | 49 |
| leftover hyphens /10k words | 1.71 | 1.77 | 1.09 | 1.45 |
| running-head leak | 0.000 | 0.000 | 0.000 | 0.000 |
| page-number leak | 0.038 | 0.035 | 0.028 | 0.032 |
| outline titles in nav | 0.875 | 0.872 | 0.874 | 0.874 |
| headings / page | 1.239 | 0.396 | 1.381 | 0.553 |
| chapters / 100 pages | 75 | 18 | 88 | 29 |

Means move little, because most problems were concentrated in particular classes of documents. Per-document numbers
show where the changes landed.

## Per document (before → after; changed values in bold)

**pdfminer** (before → after)

| doc | pages | recall | order | breaks/1000¶ | pre | PUA | head leak | chapters | headings | images | epubcheck | s/page | RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fr-novel-roi-montagnes | 183 | 0.964 → **0.965** | 0.910 → **0.911** | 3.1 → **2.4** | 0.000 | 2.8 → **0.1** | – | 11 | 44 | 2 | 0 → 0 | 0.023 | 152 |
| fr-novel-glebe | 42 | 0.973 | 0.923 → **0.928** | 43 → **11** | 0.000 | 25 → **0.6** | – | 3 | 37 | 2 | 0 → 0 | 0.022 | 96 |
| fr-novel-chignole | 102 | 0.987 | 0.962 | 0.7 | 0.000 | 0.0 | – | 24 | 38 | 0 | 0 → 0 | 0.024 | 125 |
| en-novel-my-antonia | 308 | 0.992 | 0.983 → **0.982** | 14 → **3.4** | 0.000 | 0.0 | 0.000 | 54 | 79 | 9 | 0 → 0 | 0.016 | 188 |
| en-novel-puck | 258 | 0.989 → **0.988** | 0.986 | 0.0 | 0.000 | 0.0 | 0.000 | 31 | 62 | 6 | 0 → 0 | 0.014 | 160 |
| arxiv-llama | 27 | 0.955 | 0.801 → **0.828** | 38 → **5.3** | 0.009 → **0.011** | 0.0 | – | 1 | 1 | 6 → **5** | 0 → 0 | 0.059 | 159 |
| arxiv-ligo | 16 | 0.976 | 0.939 → **0.940** | 4.7 → **17** | 0.000 | 0.0 | 0.000 | 1 | 2 | 7 | 0 → 0 | 0.124 | 160 |
| arxiv-mistral | 9 | 0.993 | 0.939 → **0.945** | 53 → **36** | 0.011 | 0.0 | – | 7 | 13 → **11** | 6 | 0 → 0 | 0.110 | 232 |
| arxiv-foundation-models | 214 | 0.982 | 0.974 | 6.2 → **7.9** | 0.000 | 0.0 | – | 40 → **39** | 42 | 28 | 1 → 0 | 0.058 | 357 |
| arxiv-d2l | 1185 | 0.909 → **0.970** | 0.837 → **0.904** | 31 → **35** | 0.120 → **0.193** | 0.0 | 0.002 → **0.000** | 186 → **187** | 1374 → **1383** | 1789 → **839** | 0 → 0 | 0.056 | 587 |
| pg-calculus-made-easy | 292 | 0.930 → **0.923** | 0.703 → **0.702** | 91 → **87** | 0.072 → **0.073** | 3.6 → **0.0** | 0.000 | 65 | 114 | 73 | 0 → 0 | 0.019 | 194 |
| pg-descartes-geometrie | 82 | 0.966 | 0.841 | 253 → **264** | 0.109 → **0.111** | 0.3 → **0.0** | – | 3 | 14 | 30 | 0 → 0 | 0.028 | 139 |
| pg-galois | 78 | 0.965 → **0.964** | 0.855 | 164 → **165** | 0.164 | 1.1 → **0.0** | – | 6 | 18 | 0 | 0 → 0 | 0.017 | 91 |
| ia-zola-roman-experimental | 436 | 0.957 → **0.947** | 0.847 → **0.843** | 0.0 → **21** | 1.000 → **0.000** | 0.0 | 0.646 → **0.037** | 21 → **3** | 21 → **13** | 62 | 0 → 0 | 0.535 | 1054 |
| ia-island-plant | 104 | 0.965 → **0.956** | 0.898 → **0.886** | 0.0 → **73** | 0.997 → **0.000** | 0.0 | 0.000 | 12 → **1** | 12 → **2** | 56 | 0 → 0 | 0.616 | 536 |
| ia-innkeeper-source | 16 | 0.992 → **0.976** | 0.970 → **0.937** | 0.0 → **75** | 0.990 → **0.000** | 0.0 | – | 9 → **1** | 9 → **4** | 12 | 0 → 0 | 1.208 | 450 |
| scan-only-en | 6 | 0.981 → **0.977** | 0.909 → **0.904** | 62 | 0.000 | 0.0 | – | 38 → **1** | 38 → **1** | 0 | 0 → 0 | 0.888 | 111 |
| scan-only-fr | 4 | 0.904 → **0.892** | 0.632 → **0.629** | 206 → **0.0** | 0.000 | 0.0 | – | 11 → **1** | 26 → **1** | 0 | 0 → 0 | 0.605 | 81 |

**pymupdf** (before → after)

| doc | pages | recall | order | breaks/1000¶ | pre | PUA | head leak | chapters | headings | images | epubcheck | s/page | RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fr-novel-roi-montagnes | 183 | 0.961 | 0.900 → **0.901** | 3.1 → **2.4** | 0.000 | 2.8 → **0.1** | – | 11 | 44 | 2 | 0 → 0 | 0.011 | 230 |
| fr-novel-glebe | 42 | 0.972 → **0.971** | 0.920 → **0.924** | 43 → **11** | 0.000 | 25 → **0.6** | – | 3 | 37 | 2 | 0 → 0 | 0.020 | 212 |
| fr-novel-chignole | 102 | 0.985 | 0.955 | 0.7 | 0.000 | 0.0 | – | 24 | 38 | 0 | 0 → 0 | 0.010 | 218 |
| en-novel-my-antonia | 308 | 0.991 | 0.980 → **0.979** | 14 → **3.5** | 0.000 | 0.0 | 0.000 | 52 | 80 | 9 | 0 → 0 | 0.009 | 262 |
| en-novel-puck | 258 | 0.987 | 0.982 | 0.0 | 0.000 | 0.0 | 0.000 | 31 | 62 | 6 | 0 → 0 | 0.007 | 252 |
| arxiv-llama | 27 | 0.961 → **0.956** | 0.761 → **0.782** | 12 → **9.2** | 0.011 | 0.0 | – | 44 → **46** | 44 → **46** | 4 | 0 → 0 | 0.070 | 248 |
| arxiv-ligo | 16 | 0.975 | 0.943 → **0.939** | 281 → **8.8** | 0.000 | 0.0 | 0.000 | 1 | 2 | 10 | 0 → 0 | 0.103 | 246 |
| arxiv-mistral | 9 | 0.993 | 0.945 | 12 | 0.011 | 0.0 | – | 7 | 14 | 6 | 0 → 0 | 0.239 | 474 |
| arxiv-foundation-models | 214 | 0.982 | 0.973 | 43 → **42** | 0.000 | 0.0 | – | 40 → **37** | 44 | 79 | 1 → 0 | 0.034 | 496 |
| arxiv-d2l | 1185 | 0.911 → **0.974** | 0.856 → **0.920** | 33 → **36** | 0.120 → **0.193** | 2.7 → **0.0** | 0.002 → **0.000** | 187 → **188** | 1372 → **1377** | 1757 → **802** | 0 → 0 | 0.051 | 688 |
| pg-calculus-made-easy | 292 | 0.913 → **0.931** | 0.736 → **0.763** | 91 → **100** | 0.073 | 3.6 → **0.0** | 0.000 | 65 | 115 | 58 | 0 → 0 | 0.019 | 281 |
| pg-descartes-geometrie | 82 | 0.955 → **0.961** | 0.854 → **0.861** | 218 → **232** | 0.110 → **0.112** | 0.3 → **0.0** | – | 3 | 15 | 32 | 0 → 0 | 0.031 | 254 |
| pg-galois | 78 | 0.962 → **0.961** | 0.863 → **0.866** | 151 → **156** | 0.165 | 1.1 → **0.0** | – | 6 | 24 | 0 | 0 → 0 | 0.015 | 225 |
| ia-zola-roman-experimental | 436 | 0.957 → **0.950** | 0.848 → **0.845** | 0.0 → **211** | 0.994 → **0.000** | 0.0 | 0.805 → **0.390** | 6 → **5** | 165 → **68** | 62 | 0 → 0 | 0.374 | 1213 |
| ia-island-plant | 104 | 0.965 → **0.957** | 0.898 → **0.891** | 0.0 → **88** | 0.991 → **0.000** | 0.0 | 0.000 | 28 → **1** | 28 → **3** | 56 | 0 → 0 | 0.492 | 896 |
| ia-innkeeper-source | 16 | 0.992 → **0.982** | 0.970 → **0.957** | 0.0 → **61** | 0.990 → **0.000** | 0.0 | – | 3 → **1** | 9 → **5** | 12 | 0 → 0 | 0.884 | 956 |
| scan-only-en | 6 | 0.981 → **0.978** | 0.927 → **0.923** | 95 → **114** | 0.000 | 0.0 | – | 37 → **1** | 37 → **1** | 0 | 0 → 0 | 0.916 | 220 |
| scan-only-fr | 4 | 0.901 → **0.889** | 0.626 → **0.623** | 212 → **0.0** | 0.000 | 0.0 | – | 13 → **1** | 28 → **2** | 0 | 0 → 0 | 0.652 | 209 |

## What was wrong and what changed

Ordered by impact. Every fix has a regression test in `src/pdftoepub/core/tests/test_corpus_regressions.py`.

1. **Internet Archive / OCRmyPDF scans came out entirely as `<pre>` code** (Zola, Island, Innkeeper: 99–100 % of the text).
   This was a regression from the monospace feature. Tesseract's invisible-layer font `GlyphLessFont` carries the FixedPitch
   flag. OCR fonts are now never bold, italic or mono, and their pages are flagged `PageData.ocr_layer`.
   Tests: `test_tesseract_glyphless_font_is_plain_text`.
2. **Paragraphs on OCR pages split at almost every line**, once they were real paragraphs. The causes are glyph-box sizes
   that jitter 10–15 % and line positions that wander by half a line. Fixes: sizes within 15 % of the page's body size are
   snapped to it; a plain vertical gap only ends a paragraph after a sentence (or when it is ≥1.5 em); on PyMuPDF,
   word fragments are merged across justified gaps. Zola 451 → 20 breaks/1000 (pdfminer).
   Tests: `test_ocr_line_sizes_are_snapped_but_headings_kept`, `test_ocr_line_jitter_does_not_split_sentences`.
3. **Running heads of scanned books leaked** because OCR misreads them ("LE KOMAN EXPÉRIMENTAL.", folio "3f"), which
   breaks the chain of identical keys. Keys now ignore accents and punctuation; a page's outermost margin line is mapped to
   a recurring head when it reads ≥ 80 % the same; vertical tolerance is 5 % on OCR pages. Zola running-head leak
   0.65 → 0.10. Test: `test_misread_ocr_running_heads_are_removed`.
4. **OCR noise from ornaments and plates** ("TSeAd ab oe aa", "ener * KK xk *") is dropped on OCR pages. A line goes only if
   its words are unknown to the book *and* it has very short tokens or many symbols. Innkeeper 91 → 48 breaks/1000.
   Tests: `test_ocr_noise_lines_are_dropped_but_short_real_lines_kept`, `test_ocr_noise_filter_keeps_french_lines_with_elisions`.
5. **Code listings in shaded boxes were rasterised as "vector figures"**, losing the code text: `import`, `torch` and `self`
   were the most-missed words in D2L. This was the original HackTheBox complaint, on a 1185-page textbook. A cluster with
   ≤ 6 shapes, one covering it entirely, with text inside, is now a text box. D2L word recall 0.909 → 0.970, order
   0.837 → 0.904; images in the EPUB 1789 → 839 (those were pictures of code). Test: `test_shaded_code_box_is_not_rasterised_as_figure`.
6. **A borderless table in one column swallowed the other column's prose as cells.** The table box then spanned the
   gutter, so XY-cut could not separate the columns and lines interleaved ("the per- To further investigate…"). Prose lines
   (≥ 35 chars, ≥ 6 words, one cell) are never table cells. LLaMA breaks 38 → 5, order 0.80 → 0.83, leftover hyphens
   8.0 → 0. Test: `test_prose_column_is_not_absorbed_by_a_borderless_table`.
7. **Typical line gap was measured on the wrong pairs on two-column pages** (in (y, x) order the neighbour is in the other
   column). On LIGO with PyMuPDF that made every line a paragraph. The gap is now measured to the next line below in the
   same column. LIGO/PyMuPDF 281 → 9 breaks/1000. Test: `test_line_gap_is_measured_within_columns`.
8. **Drop caps glued three lines together without spaces** ("lesombres", "plateessuie"). pdfminer puts the cap on the first
   line, and the merged line was as tall as the cap, so the row joiner absorbed the next two lines. Fixes: the line keeps its
   own height; the cap gets body size; rows only join lines that are disjoint in x. Test: `test_dropcap_does_not_swallow_the_following_lines`.
9. **Running heads in novels with short chapters** (My Ántonia: "xii · My Ántonia"; La Glèbe: "La glèbe … Chapitre IV").
   Every chapter opener breaks the verso/recto chain, and chapter names change. A short margin line on the row of a
   folio or of a chained head is now a head too. Breaks: My Ántonia 14 → 3.4, La Glèbe 43 → 11.
   Tests: `test_running_head_on_the_folio_row_is_removed_even_without_a_chain`, `test_chapter_name_next_to_a_chained_running_head_is_removed`.
10. **Private-use characters** (blank boxes in readers). This covers Linux Libertine small caps (the opening words of each Bibebook
    chapter), Adobe small caps, and Symbol tall-delimiter pieces in math (`[`, `{` drawn as 3–6 glyphs). They are mapped back.
    PUA 1.84 → 0.04 per 10k chars. Tests: `test_private_use_small_caps_are_mapped_to_letters`, `test_tall_delimiter_pieces_become_one_delimiter`.
11. **Old TeX (OT1) accents as separate glyphs** ("esp`ece", "fa¸con", "op´erations" in Descartes): composed into
    "espèce", "façon", "opérations". Test: `test_spacing_accents_from_ot1_fonts_are_combined`.
12. **Rotated glyphs** (plot axis labels) produced one-letter paragraphs on pdfminer ("v", "i", "r", "a"). They are dropped,
    as PyMuPDF already did.
13. **Paragraphs split by an illustration** placed at the page break are re-joined when the continuation starts lower
    case. Test: `test_paragraph_split_by_a_floating_figure_is_rejoined`.
14. **epubcheck error** (Foundation Models: link annotation URL with a space): URLs are percent-encoded. 1 → 0 errors.
    Test: `test_link_urls_with_spaces_are_percent_encoded`.

### Round 2: structure of OCR'd pages (reported from the frozen macOS binary)

On OCR pages, ordinary body lines became `<h1>` / `<h2>` and almost every page started a new chapter (6-page English
excerpt: 37 chapters). The running head of a 4-page French excerpt stayed in the text. Causes and fixes:

* **Line size from Tesseract word boxes** was the 75th-percentile box height, and box height depends on the letters: "une"
  spans the x-height, "lequel" or "été" nearly the full em. Line sizes jittered by ~30 %. Each word box is now divided by
  the share of the em its glyph zones cover (x-height / ascender, cap or accent / descender / both), and the line size is
  the median over its words (`ocr.line_size_px`). Body-line jitter on the French pages: ~30 % → ≤ 11 %.
* **Headings from OCR need strong evidence** (`structure._ocr_heading_key`): ≥ 1.3 × body and ≥ 2 pt larger, ≤ 2 lines,
  ≤ 100 chars, not starting lower case, not ending with a hyphen / comma / colon or (when long) mid-word, and either
  whitespace above, centred, or first in its flow. Blocks carry `ocr`, `space_above` and `centred` for this.
* **Chapters never split on OCR-derived headings** unless they are strong (≥ 1.5 × body, centred, ≤ 60 chars) or the PDF has
  an outline. Weaker ones stay section headings (`Heading.weak`).
* **Running heads on short scans**: the key ignores a folio at either end ("2 LE ROMAN…" = "…MENTAL. 3"), and in documents
  under 20 pages three occurrences are enough to map OCR misreads onto a head.
* New metrics: **headings per page** and **chapters per 100 pages**. Tests: `test_ocr_structure.py`, including a rasterised
  4-page essay that, with the old code, gives 13 chapters, 13 headings and 24 paragraphs; now 1 chapter, 1 heading and
  12 paragraphs (the typeset count).

| doc | backend | chapters | headings | headings/page | chapters/100 p | head leak | breaks/1000¶ | word recall | order |
|---|---|---|---|---|---|---|---|---|---|
| ia-zola-roman-experimental | pdfminer | 21 → **3** | 21 → **13** | 0.048 → **0.030** | 4.8 → **0.7** | 0.098 → **0.037** | 19.6 → **20.8** | 0.947 | 0.843 |
| ia-zola-roman-experimental | pymupdf | 5 | 148 → **68** | 0.339 → **0.156** | 1.1 | 0.415 → **0.390** | 227.9 → **211.2** | 0.950 | 0.845 |
| ia-island-plant | pdfminer | 11 → **1** | 11 → **2** | 0.106 → **0.019** | 10.6 → **1.0** | 0.000 | 54.6 → **72.8** | 0.956 | 0.886 |
| ia-island-plant | pymupdf | 26 → **1** | 26 → **3** | 0.250 → **0.029** | 25.0 → **1.0** | 0.000 | 51.2 → **88.3** | 0.957 | 0.891 |
| ia-innkeeper-source | pdfminer | 5 → **1** | 8 → **4** | 0.500 → **0.250** | 31.2 → **6.2** | – | 47.6 → **74.6** | 0.976 | 0.937 |
| ia-innkeeper-source | pymupdf | 3 → **1** | 9 → **5** | 0.562 → **0.312** | 18.8 → **6.2** | – | 49.2 → **60.6** | 0.982 | 0.957 |
| scan-only-en | pdfminer | 37 → **1** | 37 → **1** | 6.167 → **0.167** | 616.7 → **16.7** | – | 34.5 → **62.5** | 0.977 | 0.904 |
| scan-only-en | pymupdf | 35 → **1** | 35 → **1** | 5.833 → **0.167** | 583.3 → **16.7** | – | 53.6 → **114.3** | 0.978 | 0.923 |
| scan-only-fr | pdfminer | 11 → **1** | 23 → **1** | 5.750 → **0.250** | 275.0 → **25.0** | – | 142.9 → **0.0** | 0.904 → **0.892** | 0.632 → **0.629** |
| scan-only-fr | pymupdf | 13 → **1** | 24 → **2** | 6.000 → **0.500** | 325.0 → **25.0** | – | 166.7 → **0.0** | 0.901 → **0.889** | 0.626 → **0.623** |

"breaks/1000¶" rises on Island, Innkeeper and the English excerpt because lines that used to be (false) headings or chapter
starts are now paragraphs and are counted. The ones left are OCR noise on title / plate pages and real page-boundary
splits; on the English excerpt it is 2 breaks in 32 paragraphs. Zola keeps 13 headings (essay and section titles) in 3 chapters: under-split rather than
over-split, by design. PyMuPDF on the Zola OCR layer is still poor (see below).

### Robustness and resources

* **No page can stall pdfminer**: interpretation of one page is capped at `PDFTOEPUB_PAGE_TIMEOUT` seconds (default 60;
  checked every 1024 glyphs / paths and every 4096 operands) and at 150 000 glyphs. Paths beyond 50 000 are ignored.
  Over budget, the page is kept as a picture with a warning. No corpus page hit the budget (no "too complex" warning in
  36 conversions). Test: `test_pdfminer_page_budget_keeps_page_as_image` (both the glyph cap and the timeout).
* **Huge embedded bitmaps** (> 12 Mpx, e.g. an 11 000 × 3 600 px plot in Mistral) are rendered from the page at output
  size instead of being decoded in full. Mistral peak RSS 743 → 216 MB. Test: `test_huge_embedded_bitmap_is_not_decoded_at_full_size`.
* **Memory on long books** (pdfminer): 436-page OCR'd scan 430–560 MB; 1185-page D2L 460–530 MB; text novels 95–190 MB.
  Peak RSS tracks image decoding more than page count: the 104-page Island scan peaks as high as the 1185-page D2L.
  The whole book's IR stays in memory until packaging; conversion is not streamed.
* **Speed** (pdfminer, this Mac): born-digital text 0.015–0.06 s/page (D2L 1185 pages in 67 s); IA OCR-layer scans 0.55–1.2
  s/page (Zola 436 pages in 4 min, because their text layer is one positioned word at a time); Tesseract OCR 0.6–0.9 s/page.

## pdfminer (default) vs PyMuPDF

* **Quality is at parity.** After the fixes, mean word recall is 0.966 vs 0.966, char recall 0.989 vs 0.990, and order
  0.887 vs 0.891, with 0 epubcheck errors on both.
* **PyMuPDF is better** on two-column reading order (0.765 vs 0.747 on 2-col pages; D2L 0.921 vs 0.904; Calculus 0.763 vs 0.702)
  and has fewer mid-sentence breaks on Mistral (12 vs 36).
* **pdfminer is better** on LLaMA (order 0.83 vs 0.78; leftover hyphens 0 vs 7.2/10k) and much better on Internet Archive OCR
  layers. On Zola, PyMuPDF still splits OCR word fragments: 228 vs 20 breaks/1000, head leak 0.42 vs 0.10.
* **Speed**: PyMuPDF is ~25 % faster on born-digital PDFs (0.099 vs 0.130 s/page mean) and ~30 % faster on OCR layers.
* **Memory**: PyMuPDF's peak RSS is much higher (660–1215 MB on the IA scans vs 440–560 MB). Some of that is run-to-run
  noise in the same measurement.

## Remaining known weaknesses (not fixed)

* **Math** (round 3): two-dimensional display formulas are pictures with alt text, one-row ones text; no MathML.
  Descartes' remaining breaks are its marginal notes; LIGO's formulas are not recognised (no math-font names). See
  "Could not improve" in round 3.
* **Broken font encodings in the PDF itself**: LIGO's RevTeX math fonts map "+" to "þ" and "(" to "ð", and a radical
  extender to "ffi". pdfium extracts the same, so only glyph-shape analysis could fix it.
* **Marginal notes** (Descartes' side notes) are interleaved into the body text. **Two-column pages**: the round-2
  "0.75" was mostly a measurement artefact (round 3); LLaMA's title page with PyMuPDF (0.74) is the weakest page left.
* **Libertine accented small caps** (U+E078 "è", U+E079 "é", …) are only partly mapped; 0.6 PUA chars/10k remain in La Glèbe.
* **PyMuPDF + IA OCR layer**: see the backend comparison above.
* **OCR (Tesseract) on a French excerpt**: recall 0.89 against IA's own OCR. That reference is another OCR engine, not
  ground truth; on 4 pages the remaining differences are character-level misreads.
* **OCR headings are conservative**: a heading set only slightly larger than body text, or not centred and without space
  above, is read as a paragraph on scans. Chapters of scanned books come from page openings and the printed TOC
  (round 3); a chapter starting mid-page is not split off.
* **Footnotes**: plain "word23" references without superscript are not linked (unchanged).
* **No reconstruction of printed TOC pages**: scanned TOCs stay as paragraphs ("De la critique 287"); they are used to
  find chapters but not linked.
