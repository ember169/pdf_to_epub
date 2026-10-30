# Real-world corpus evaluation — conversion quality report

18 public-domain / openly licensed PDFs (98.5 MB, 3 362 pages) from arXiv, Project Gutenberg and the Internet Archive,
converted with both backends (pdfminer.six + pypdfium2 = default, PyMuPDF = optional), measured before and after the
fixes of this round. Reproduce:

```
python tests/corpus/fetch.py                      # downloads into tests/.corpus/ (git-ignored), verifies sha256
python tests/corpus/evaluate.py --label after     # ~25 min for both backends; results in tests/corpus/out/after/
python tests/corpus/evaluate.py --compare before after
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

## Headline numbers

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

* **Math**: display formulas become short separate paragraphs, sub/superscripts and fractions are flattened, there is no
  MathML. This produces the high "breaks" on Descartes (264/1000), Galois (165) and Calculus (87), and the low order on Calculus (0.70).
* **Broken font encodings in the PDF itself**: LIGO's RevTeX math fonts map "+" to "þ" and "(" to "ð", and a radical
  extender to "ffi". pdfium extracts the same, so only glyph-shape analysis could fix it.
* **Marginal notes** (Descartes' side notes) are interleaved into the body text. **Two-column pages** still have the
  lowest order (0.75 mean), mostly around figures, tables and author blocks.
* **Libertine accented small caps** (U+E078 "è", U+E079 "é", …) are only partly mapped; 0.6 PUA chars/10k remain in La Glèbe.
* **PyMuPDF + IA OCR layer**: see the backend comparison above.
* **OCR (Tesseract) on a French excerpt**: recall 0.89 against IA's own OCR. That reference is another OCR engine, not
  ground truth; on 4 pages the remaining differences are character-level misreads.
* **OCR headings are conservative**: a heading set only slightly larger than body text, or not centred and without space
  above, is read as a paragraph on scans.
* **Footnotes**: plain "word23" references without superscript are not linked (unchanged).
* **No reconstruction of printed TOC pages**: scanned TOCs stay as paragraphs ("De la critique 287").
