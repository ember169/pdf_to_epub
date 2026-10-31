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

## Round 8: cleaner tables of contents

Before is 9b47a4f (`r8-before`) and after is this tree (`r8-after3`). Each was run on all 19 documents with both backends.
Text metrics unchanged everywhere (word recall, order, running-head and page-number leaks, outline match), epubcheck 0
errors. The private book is unchanged (same navigation, same text). Test suite: 435 passed, 22 skipped.

**What changed** (`core/structure.py`, `core/epub.py`):
* **Fleurons are no headings.** A lone lower-case letter classified as a heading is an ornament from a decorative font
  (Bibebook ends every chapter with "n" in *Swinging*): dropped. It used to give a "n" entry per chapter, and *La Glèbe*
  (no outline) was even split into chapters named "n".
* **The chapter label joins its title.** "CHAPITRE II" set smaller right above "Photini." becomes one heading,
  "CHAPITRE II — Photini.", after the title's own lines are joined. It used to trail at the end of the previous chapter
  (the outline points at the title) and appear in the navigation as a sub-entry of the wrong chapter. When an outline entry
  is only the label ("CHAPTER I."), the navigation uses the whole heading; under a container entry ("Main Matter") the
  chapter stays listed.
* **Labelled chapters without an outline.** When ≥3 headings of one level read "CHAPITRE n" / "Chapter n" below a few
  larger title-page headings, the book is split there; everything before chapter I is one front-matter entry.
* **Front matter is one entry.** The pages before the first chapter (title page, publisher's notes, credits, licence),
  when they span ≥2 pages, no longer add sub-entries. A paper's first page keeps its "Abstract".
* **Contents rows.** "XI 32" left alone on the last page of a printed table is no heading.

| document | entries before → after | what went |
|---|---|---|
| Le Roi des montagnes | 43 → 13 | Bibebook pages, 10 × "n", 9 × "CHAPITRE n" under the wrong chapter |
| La Glèbe | 25 → 14 | chapters were named "n"; now CHAPITRE I–XI after one front-matter entry |
| Calculus Made Easy | 110 → 90 | "Chapter II" + "ON DIFFERENT DEGREES…" pairs → "CHAPTER II. — ON DIFFERENT DEGREES…" |
| Puck, My Ántonia | 60 → 53, 73 → 66 | title-page lines; Gutenberg licence "Section n." joined to its title |
| d2l, Descartes | −1 each | "Contents", "LA" in the front matter |

Left as is: Project Gutenberg PDFs whose outline starts with a "TABLE DES MATIÈRES" entry covering the title pages
(*Chignole*) still list the title-page lines under it; *La Glèbe* keeps its printed table and the publisher's last page
as entries after chapter XI.

## Round 7: a real cover

Before is 6a5d316 (`r7-before`) and after is this tree (`r7-after`). Each was run on all 19 documents with both backends.
epubcheck: 0 errors everywhere. The test suite: 449 passed, 2 skipped.

**What changed in the EPUB:**
* **A cover document first.** `cover.xhtml` is the first spine item (`linear="yes"`, `<section epub:type="cover">`): an
  SVG wrapper (`viewBox` = the picture, `preserveAspectRatio="xMidYMid meet"`, so it fills the screen without cropping)
  with the book title as `<title>` and `aria-label`. Reading systems that ignore the cover metadata (sideloaded Kobo, some
  Android readers, Kindle conversions) still open on the cover.
* **Cover metadata kept:** `properties="cover-image"` and the legacy `<meta name="cover">` stay.
* **Landmarks:** the landmarks nav now lists cover, table of contents and body start. An EPUB 2 `<guide>` lists the same
  (cover, toc, text) for older tools.
* **The nav document** is in the spine as `linear="no"`, because epubcheck requires a landmark's target to be in the
  spine.

**Which page** (`core/cover.py`, the first 3 pages rendered at 40 dpi):
* page 1, unless it is blank (under 0.4 % inked pixels: white with specks); then the first page of the first 3 that is not;
* a weak page 1 (under 3 % ink and no display type: a bookplate, a stamp) gives way to page 2 or 3 only when that page
  clearly is a cover (≥ 25 % ink, a full-bleed picture, or type ≥ 2× the body size);
* otherwise page 1.

On the corpus every document keeps page 1, including the scans, whose page 1 is the photographed binding or title page.
The rule is covered by unit tests.

**Which picture:**
* **Embedded:** used when the page's one full-page raster image has no visible text drawn over it. It is kept as embedded
  when it is a JPEG of at most 1 MB and 800–1600 px high, otherwise re-encoded.
* **Rendering:** used otherwise, 1600 px high (Bibebook covers set the title as text over a framed background: the
  rendering keeps the title).
* **Encoding:** JPEG quality 85, lowered in steps until it fits in 1 MB. Greyscale stays greyscale (a page whose three
  channels match is saved as L). The render pixel cap still applies.

**The cover page's own text.** When every word on the chosen cover page is in the title, the creators, the publisher or
the year (now in the metadata), that page's blocks are not repeated at the start of the first document. Any other text
stays, for example an abstract on page 1 of a paper, a Gutenberg licence header or a title page with names.

Every text change in the corpus is listed in the table below. The private book loses 6 words: its cover title, which
also opened chapter 1. On all 18 public documents the text is word-for-word identical. Two of them had no cover before
(Zola and Innkeeper, whose page 1 is a photographed binding that round 5 dropped from the text as a picture of no text);
they have one now.

**Covers on the corpus** (pdfminer; PyMuPDF within a few KB):

| document | cover before (pdfminer) | cover after (pdfminer) | words removed from the body |
|---|---|---|---|
| fr-novel-roi-montagnes | 641x910 RGB 60KB | 1127x1600 RGB 149KB | 0 |
| fr-novel-glebe | 641x910 RGB 57KB | 1127x1600 RGB 140KB | 0 |
| fr-novel-chignole | 641x910 RGB 59KB | 1127x1600 L 142KB | 0 |
| en-novel-my-antonia | 641x910 RGB 37KB | 1127x1600 L 83KB | 0 |
| en-novel-puck | 641x910 RGB 38KB | 1127x1600 L 85KB | 0 |
| arxiv-llama | 910x1287 RGB 253KB | 1131x1600 L 349KB | 0 |
| arxiv-ligo | 935x1210 RGB 266KB | 1237x1600 L 433KB | 0 |
| arxiv-mistral | 935x1210 RGB 165KB | 1237x1600 RGB 272KB | 0 |
| arxiv-foundation-models | 743x1100 RGB 198KB | 1080x1600 L 360KB | 0 |
| arxiv-d2l | 910x1287 RGB 17KB | 1131x1600 L 21KB | 0 |
| pg-calculus-made-easy | 599x880 RGB 51KB | 1089x1600 L 122KB | 0 |
| pg-descartes-geometrie | 935x1210 RGB 60KB | 1237x1600 L 33KB | 0 |
| pg-galois | 605x880 RGB 42KB | 1100x1600 L 89KB | 0 |
| ia-zola-roman-experimental | none | 1007x1600 RGB 265KB | 0 |
| ia-island-plant | 505x823 RGB 42KB | 982x1600 RGB 147KB | 0 |
| ia-innkeeper-source | none | 979x1600 RGB 341KB | 0 |
| scan-only-en | 500x823 RGB 72KB | 909x1496 RGB 192KB | 0 |
| scan-only-fr | 437x718 RGB 45KB | 794x1305 RGB 111KB | 0 |
| private book | 524x823 RGB 10KB | 1019x1600 L 25KB | 6 |

**Visual check:** a contact sheet (scratchpad) of the book, Zola, Island, Innkeeper, LLaMA, Puck and the three Bibebook
novels, before and after:
* **Same pictures, sharper:** the book, Island, LLaMA and Puck show the same page as before at about twice the
  resolution; the book's black cover is now a 25 KB greyscale JPEG.
* **New covers:** Zola and Innkeeper show their scanned bindings, Innkeeper with its title label.
* **Bibebook novels:** a first version used the embedded background alone and lost the title. That was fixed by
  rendering pages with visible text, and the titles are back.

**Switching it off.** It only takes a `ConvertOptions.cover: bool = True` field (API contract) and a CLI / web switch
(`--no-cover`). `pipeline` already reads `getattr(options, "cover", True)`, so it works as soon as the field exists. I
did not change `api.py`. `image_mode="none"` already leaves the cover out.

**Tests** (`core/tests/test_cover.py`):
* the page choice: blank, bookplate before a cover, display type, unsure → page 1, all blank;
* an embedded picture kept as is, and grey staying grey;
* the cover text dropped only when it is title and names;
* the EPUB markup: spine, `cover.xhtml`, landmarks, guide, a 1600 px picture, no repeated cover text;
* no cover with `image_mode="none"`.

The evaluator leaves the cover document and the non-linear nav document out of the book text and the chapter counts.

## Round 6: glued lower-case words in OCR'd books

Before is d563fe1 (`r6-before`) and after is this tree (`r6-after`). Each was run on all 19 documents with both backends
and epubcheck on. The test suite: 439 passed, 2 skipped. epubcheck: 0 errors everywhere.

### Licences: what was checked, and the choice

| source | what | licence, from the primary source | verdict |
|---|---|---|---|
| **wordfreq 3.2** (rspeer/wordfreq, tag v3.2, commit 42233e6) | word frequencies, 40+ languages, `large_fr` / `large_en` ≈ 1.5 MB each | code Apache-2.0 (LICENSE.txt, "Copyright 2022 Robyn Speer"); data files "may be redistributed under a Creative Commons Attribution-ShareAlike 4.0 license" (README, "License"); attribution required to Google Books Ngrams, OpenSubtitles, SUBTLEX (README) | **chosen** |
| Open Lexicon / Lexique 3.83 (chrplr/openlexicon) | French word forms with frequencies | CC BY-SA 4.0 (repository LICENSE.txt and README) | usable, French only, larger |
| French Hunspell dictionaries (Dicollecte / Grammalecte) | spelling dictionary, no frequencies | Mozilla Public License 2.0 (LibreOffice extensions page) | usable for membership only; affix expansion needed |
| SCOWL / en_US Hunspell (en-wl/wordlist) | English word lists, no frequencies | permissive, notice required; some parts (UKACD, WordNet) carry their own notice terms (`scowl/Copyright`) | usable, English only, no frequencies |
| FrequencyWords (hermitdave) | OpenSubtitles frequency lists | MIT for code, CC BY-SA 4.0 for content (LICENSE, README) | usable, subtitles only |

**The choice:** wordfreq. It is one source for both languages, with frequencies from books, subtitles, Wikipedia and the
web. Its terms suit an MIT project: code under Apache-2.0, data under CC BY-SA 4.0. No GPL, AGPL, NonCommercial or
NoDerivatives term applies. Share-alike covers only the data files, which ship as separate files under their own licence.

**How the files are shipped and read:**
* The author asks that the data not be converted to formats that drop the attribution (README: "Can I convert wordfreq to
  … a CSV file? No."). So the two files ship **unmodified**, next to wordfreq's `LICENSE.txt` and a `NOTICE.txt` holding
  the licence and every attribution the README requires.
* They are read by a 60-line MessagePack reader in `core/lexicon.py`, so no new Python dependency is added.
* `python -m pdftoepub.core.lexicon fetch` downloads them from the pinned commit into `src/pdftoepub/core/data/wordfreq/`
  and checks their sha256:
  * `large_fr.msgpack.gz` `6f16cd80…c00c8b`;
  * `large_en.msgpack.gz` `dffae806…28b05c`;
  * `LICENSE.txt` `8990c551…aa88`.
* That folder is git-ignored. I don't commit them, because they are 3 MB of binary data that never changes and that a
  pinned, hash-checked fetch reproduces exactly.

**Without the files:** the repair does nothing; nothing else depends on them.

**Packaging, not done by me (`packaging/`):**
* **Build:** `build.sh`, `build.ps1` and `Dockerfile.linux` should run `python -m pdftoepub.core.lexicon fetch` before
  PyInstaller. `collect_data_files("pdftoepub")` in the spec already takes `core/data/wordfreq/`, and the lookup also
  works from `_MEIPASS`.
* **Licences:** add to `gen_licenses.py` `FIXED`:
  ```
  == wordfreq 3.2 word-frequency data (large_fr, large_en; pdftoepub/core/data/wordfreq, unmodified) ==
  Data: CC BY-SA 4.0 - https://creativecommons.org/licenses/by-sa/4.0/ ; code: Apache-2.0 - https://github.com/rspeer/wordfreq/blob/v3.2/LICENSE.txt
  By Robyn Speer, https://github.com/rspeer/wordfreq (commit 42233e6). Contains data from Google Books Ngrams (http://books.google.com/ngrams), OPUS OpenSubtitles 2018 (attribution to OpenSubtitles, http://www.opensubtitles.org/), SUBTLEX by Marc Brysbaert et al. (freely available data), Wikipedia, the Leeds Internet Corpus and ParaCrawl. Full notice: pdftoepub/core/data/wordfreq/NOTICE.txt
  ```

**Cost in the binaries and at run time:**
* +2.99 MB of data, shipped as published (already compressed).
* At run time, only for OCR'd French or English books: 0.2 s to load and about +60 MB peak memory (the French table, plus
  the other language's common words, which is 29k entries).

### Algorithm → `core/glue.py`

It runs only on OCR'd text, never born-digital (see the gate below). The language is the book's detected `dc:language`;
it applies to French and English, and does nothing otherwise.

A token is split only when all of these hold:
* it is all lower case, 5–40 letters, with no digit, apostrophe or hyphen, and not part of a URL or e-mail;
* it occurs once in the book;
* it is not a common word (Zipf < 3.5; the lists also hold frequent typos such as "dela"), nor a common word of the other
  language (Zipf ≥ 3: "differently abled");
* it is not one letter away from a common word. That is an OCR misread: "auleurs" is "auteurs", not "au leurs", and
  likewise "planle", "suile", "porle", "faisail";
* its best split into 2–3 words beats the token's own log-frequency by 1.5 (log10), with these limits on the parts:
  * every part is common (Zipf ≥ 3; three-letter parts ≥ 4, so not an abbreviation like "sci");
  * one- and two-letter parts are function words (Zipf ≥ 5.5: "la", "de", "of"; not "es", "ci");
  * a one-letter word sits beside a function word ("il a", "à la"; not "drap a");
  * after a prefix-like word ("in", "all", "en", "sur", "anti") only a very common word may follow (Zipf ≥ 6: "in the";
    not "in dwellers", "anti es").

Each rule above comes from a wrong split seen on the corpus. The changes are counted, and a sample goes to each
document's evaluation report (`glue_splits`, `glue_examples`; the evaluator's worker records them).

**OCR gate, a correction to round 5.** The OCR'd-book test was "OCR here or a known OCR-layer font", and it missed ABBYY
layers, which use ordinary font names. So round 5's OCR corrections (`ocrfix.py`) never ran on the private book. The 91
changes I reported came from running `ocrfix` on cached blocks, not from the conversion. Pages are now also counted as
OCR'd when they are a full-page scan with text (`PageData.scanned`). Both repairs now run on the book's real output.

### Results

| document | splits (pdfminer / PyMuPDF) | hand-checked (pdfminer) |
|---|---|---|
| Zola (fr) | 64 / 67 | all 64: 61 right, 1 probably wrong ("nousa" → "nous a"), 2 unclear (the corrected phrase also occurs elsewhere) |
| Island (en) | 2 / 2 | 2 right |
| Innkeeper (en) | 1 / 1 | 1 right |
| scan-only-en / -fr | 1 / 1 each | right |
| private book (fr) | 5 / 5 | 5 right |
| born-digital documents | 0 | – |

Precision of the splitter, all 74 pdfminer changes checked by hand: **at least 71 / 74 (96 %), 73 / 74 if the 2 unclear
ones are right.**

Rules added on the way, and what they cost:
* An earlier version made 88 changes on Zola with about 17 wrong (OCR misreads and hyphen fragments split into words).
  The misread rule and the short-part rules removed those.
* They also cost about 10 right splits, such as "quele" (also one letter from "quelle") and "letour" (one letter from
  "retour"). Precision was preferred.
* The private book has few lower-case glued words, 5 found. The round-5 "danslavie" and "socialprovisioning" were the
  examples; the second mixes French and English, and is left.

**Metrics against the reference text, and why they move.** The corpus reference is the PDF's own text layer. For these
scans it holds the very glue being repaired: 61 of Zola's 64 split tokens are single words in it. So a correct split
counts as a "split word" and lowers word precision against that reference.

Raw metrics, before → after (pdfminer; PyMuPDF the same within 0.0005):

| document | word precision | split words /10k | joined words /10k |
|---|---|---|---|
| Zola | 0.9918 → 0.9911 | 0.45 → 1.87 | 17.67 → 17.40 |
| Island | 0.9994 → 0.9992 | 1.26 → 1.89 | 0 → 0 |
| Innkeeper | 0.9987 → 0.9982 | 0 → 0 | 2.63 → 2.63 |
| scan-only-en | 0.9907 → 0.9903 | 4.41 → 4.41 | 4.41 → 4.41 |
| scan-only-fr | 0.9468 → 0.9479 | 30.67 → 30.64 | 71.57 → 61.29 |

Scored against a reference with the same glue split (only whole-word occurrences of the 64 / 2 tokens, nothing else
touched):

| document | precision | split words | recall | order |
|---|---|---|---|---|
| Zola, before → after | 0.9913 → 0.9918 | 0.45 → 0.45 | 0.9710 → 0.9720 | 0.9314 → 0.9348 |
| Island, before → after | 0.9992 → 0.9994 | 1.26 → 1.26 | 0.9801 → 0.9804 | 0.9760 → 0.9768 |

Innkeeper's −0.0005 is its one change ("theshepherds" → "the shepherds", glued in the reference). On the 13 born-digital
public documents every metric is identical. On the private book, `order_2col` goes 0.890 → 0.885: the OCR corrections now
run there, and the reference keeps the misreads they fix.

**Tests** (`core/tests/test_glue.py`, with a synthetic lexicon in wordfreq's format):
* the format is read;
* glued words are split, while real, repeated, capitalised, digit, address, one-letter-misplaced, typo-list and
  other-language words are left alone;
* without the lexicon there is no change;
* an OCR layer over a scan is repaired, and the same text born-digital is not.

**Not done:** languages other than French and English; glued words with a capital or an apostrophe; splits into more than
3 words; glued words that the book repeats; and misread glue ("toutle" one letter from "toute").

## Round 5: a real scanned book (collective volume, ABBYY OCR layer)

The test case is a 420-page French collective volume, scanned with an invisible ABBYY FineReader 10 text layer. It is
copyrighted and the user's own copy, so it is **local only** (listed only in the git-ignored `tests/.corpus/private/manifest.json`,
sha256 only, no URL; `fetch.py` skips it and says where to place it; `evaluate.py` includes it when present). Its
hand-checked ground truth sits next to the PDF, git-ignored (`gt_file`). It was read from the page images:
* 21 units (4 parts, the Introduction, 15 numbered chapters, the Épilogue) with their authors, sections and printed pages;
* printed page = PDF page + 2, checked on 22 pages;
* endnote counts for three chapters;
* the blank and part-divider pages;
* the title, editors, publisher, year and ISBN.

The report gives numbers only, no text from the book. Unit tests use synthetic PDFs.

"Before" is `main` at ba5e2be (`--src`), "after" this working tree, both scored by the same evaluator (all 18 public
documents and the book, both backends, epubcheck on):

```
git archive ba5e2be src | tar -x -C /tmp/main
python tests/corpus/evaluate.py --label r5-before --src /tmp/main/src
python tests/corpus/evaluate.py --label r5-after
```

New metrics (`evaluate.py`):
* `lspaced`: letter-spaced runs, per 10k words.
* `glued`: glued words (two reference words as one, or camelCase), per 10k words.
* `noterefs`, `sup_unlinked` and `note_items`: linked note references, superscript numbers left unlinked, and notes.
* `junk_imgs`: blank, uniform, specks-only or black pictures.
* `lower_starts`: paragraphs and quotes starting in lower case after another one, per 1000.
* `pagelist`: page-list entries per PDF page.
* With a private ground truth: `spine_units` (units opening a spine document), `spine_docs`, `nav_recall`,
  `nav_precision` and `title_ok`.

### The book, before → after

| metric | pdfminer | pymupdf |
|---|---|---|
| word_recall | **0.975 → 0.976** | **0.980 → 0.976** |
| order | **0.951 → 0.979** | **0.972 → 0.979** |
| lspaced | **84.3 → 0.8** | **37.5 → 0.9** |
| glued | **2.8 → 3.0** | **3.1 → 3.0** |
| noterefs | **2 → 316** | **2 → 316** |
| sup_unlinked | **502 → 187** | **502 → 187** |
| note_items | **156 → 494** | **210 → 493** |
| junk_imgs | **15 → 0** | **15 → 0** |
| img_epub | **17 → 0** | **17 → 0** |
| spine_units | **3 → 21** | **3 → 21** |
| spine_docs | **5 → 23** | **5 → 23** |
| nav_recall | **0.828 → 0.966** | **0.828 → 0.966** |
| nav_precision | **0.835 → 0.983** | **0.835 → 0.983** |
| title_ok | **0 → 1** | **0 → 1** |
| lower_starts | **22.8 → 12.8** | **21.1 → 12.8** |
| mid_breaks | **9.8 → 5.3** | **8.9 → 5.3** |
| pagelist | **0.000 → 0.943** | **0.000 → 0.943** |
| hdr_leak | **0.132 → 0.000** | 0.000 → 0.000 |
| epubcheck | 0 → 0 | 0 → 0 |

Endnotes checked against the ground truth (counted on the page images):

| chapter | notes in the ground truth | notes found (pdfminer / PyMuPDF) | references linked (pdfminer / PyMuPDF) |
|---|---|---|---|
| 6 | 44 | 43 / 38 | 30 / 27 |
| 9 | 26 | 26 / 26 | 15 / 15 |
| 12 | 94 | 82 / 82 | 56 / 56 |

Before: the book had no per-chapter notes section, and 2 links in all. Chapter 6's missing notes (31–33, 37–40) are absent
from the ABBYY layer itself; nothing is between the running head and the first note line of that page. Unlinked
references are mostly superscripts the OCR misread or lost (`sup_unlinked` counts the ones left).

### 1. Letter-spacing and glued words → `backends/*` (space glyphs), `ocrfix.py` (camelCase)

pdfminer adds a space wherever two glyphs are more than 0.1 em apart, and MuPDF has its own gap rule. In the ABBYY layer,
small type is letter-spaced (gaps of 1.1–1.6 pt at 6.5 pt), so every note and bibliography word came apart. The layer has
real space glyphs, though.

What changed:
* **Pages whose layer has its own spaces** (≥20 and ≥6 % of characters) use them as word boundaries. pdfminer's virtual
  spaces are ignored. PyMuPDF reads such pages from `rawdict` with `TEXT_INHIBIT_SPACES`.
* **Missing space glyphs:** a space is added only at a gap of at least 2.5× the line's letter spacing and 0.18 em.
* **Pages without space glyphs** (LaTeX) keep the old geometric rule.
* **Glued words:** the words ABBYY glued ("ofCalifornia") have no gap at all; ABBYY spaced their letters evenly. They are
  split only when both halves occur at least 3 times in the book (camelCase only).

Documents where a value moved (all others identical):

| doc | backend | word_recall | word_precision | char_recall | order | lspaced | glued |
|---|---|---|---|---|---|---|---|
| arxiv-d2l | pdfminer | 0.978 → 0.978 | 0.984 → 0.984 | 0.981 → 0.981 | 0.940 → 0.940 | **3.11 → 3.14** | 1.23 → 1.23 |
| pg-calculus-made-easy | pdfminer | 0.965 → 0.965 | 0.986 → 0.986 | 0.972 → 0.972 | 0.849 → 0.849 | **14.2 → 14.4** | 0.00 → 0.00 |
| pg-calculus-made-easy | pymupdf | 0.970 → 0.970 | 0.985 → 0.985 | 0.974 → 0.974 | 0.863 → 0.863 | **13.5 → 13.3** | 0.21 → 0.21 |
| pg-descartes-geometrie | pdfminer | 0.994 → 0.994 | 0.995 → 0.995 | 0.999 → 0.999 | 0.927 → 0.927 | **30.5 → 30.2** | 0.00 → 0.00 |
| pg-descartes-geometrie | pymupdf | 0.990 → 0.990 | 0.995 → 0.995 | 0.999 → 0.999 | 0.926 → 0.926 | **27.1 → 26.8** | 0.29 → 0.29 |
| ia-zola-roman-experimental | pdfminer | 0.972 → 0.972 | 0.992 → 0.992 | 0.986 → 0.986 | 0.935 → 0.935 | 0.62 → 0.62 | **9.64 → 9.46** |
| ia-zola-roman-experimental | pymupdf | 0.974 → 0.974 | 0.992 → 0.992 | 0.988 → 0.988 | 0.936 → 0.936 | 0.62 → 0.62 | **9.62 → 9.45** |
| ia-innkeeper-source | pdfminer | 0.983 → 0.983 | 0.999 → 0.999 | **0.990 → 0.989** | 0.963 → 0.963 | 0.00 → 0.00 | 0.00 → 0.00 |
| ia-innkeeper-source | pymupdf | 0.990 → 0.990 | **0.999 → 1.000** | **0.995 → 0.994** | 0.984 → 0.984 | 0.00 → 0.00 | 0.00 → 0.00 |
| private book | pdfminer | **0.975 → 0.976** | **0.949 → 0.998** | **0.982 → 0.976** | **0.951 → 0.979** | **84.3 → 0.82** | **2.83 → 3.05** |
| private book | pymupdf | **0.980 → 0.976** | **0.982 → 0.998** | **0.981 → 0.976** | **0.972 → 0.979** | **37.5 → 0.89** | **3.06 → 3.05** |

### 2. Endnotes → `endnotes.py`

How endnotes are now built:
* **Region:** each "Notes" heading (larger than the type below it) opens a region running to the next heading
  ("Bibliographie"), a non-text block, or type 1.25× larger.
* **Order:** its lines go back into reading order: page, then column, then height. Lines the page-footnote detector took
  from the page bottoms are included. OCR rows glued across the column gap are cut at the gutter, and note rows the table
  detector took are read back as lines.
* **Cutting into notes:** a note starts where a line begins with the next number. A jump of up to 8 is accepted after a
  finished note, because the OCR layer lacks some notes.
* **Validity:** a region needs at least 3 notes of plausible length. Galois's mid-text "NOTES" block is not one.
* **Markup:** one `<section epub:type="endnotes">` with an `<ol>` (`value` = printed number).
* **Links:** superscript numbers in the same spine document link to their note (first occurrence), and the note links back.

A bug found on the way: when the page-footnote detector rejected a candidate note, it gave the line back to the text
with its number already stripped (". Author, 2011."). The line now comes back as printed.

| doc | backend | noterefs | sup_unlinked | note_items |
|---|---|---|---|---|
| arxiv-d2l | pdfminer | 160 → 160 | **647 → 648** | 165 → 165 |
| private book | pdfminer | **2 → 316** | **502 → 187** | **156 → 494** |
| private book | pymupdf | **2 → 316** | **502 → 187** | **210 → 493** |

### 3–4. Printed table of contents and chapter openings → `printedtoc.py`

Parsing the contents:
* **Finding them:** a "Sommaire" / "Table des matières" / "Contents" page within the first or last 15 pages, plus the
  continuation pages.
* **Rows:** re-assembled across the page-number column, and including rows PyMuPDF's table detector took.
* **Entries:** parts ("Deuxième partie" + title), numbered chapters ("5." + author line + title lines) and other
  entries. Sections are the lists set in smaller type under a chapter.
* **Page offset:** voted from the folios of the running heads, read before those are removed. When the folios don't
  settle it, it is voted from the titles found at the top of pages.

When it is used, and what it does:
* **Condition:** only when it shows structure (≥3 numbered chapters or ≥2 parts). Zola's flat TABLE leaves the round-3
  openings plan in charge. With the TABLE in charge, Zola got 24 documents instead of 9 in an interim run.
* **Contents pages:** dropped; the navigation replaces them.
* **Openings:** each entry's opening page gets one `h1`: the multi-line title merged, "N. " in front for a chapter, and
  "Deuxième partie — " for a part. The wording comes from the body or from the contents, whichever has its words more
  frequent in the book. That keeps a front-matter title from the body, and a part title from the contents, where tesseract glued two words
  on the divider.
* **Bylines:** author lines, including names printed above the title, become `<p class="byline">`. Front-matter headings
  become paragraphs.
* **Split and navigation:** parts and unnumbered entries are level 1, and a chapter inside a part is level 2, nested
  under it in the navigation. Sections (two-line titles merged) sit one level below, at the rank of "Notes" and
  "Bibliographie".

### 5. Page images → `pipeline._scan_is_redundant`

How a scanned page with little text (< 150 characters) is judged:
* **Rendering:** at 50 dpi.
* **Junk:** outside its text lines, the page shows no more than 0.5 % ink, so it is blank, specks only, or a picture of
  text the layer has. Its page picture goes.
* **Dark pages:** a mostly dark page is judged inside its dark block, inverted (the white margin and skew are ignored),
  and re-read by tesseract when OCR is allowed. Tesseract's lines replace the layer's when they are at least 60 % as long.
* **Uniform layers:** an all-black mask is dropped even next to a real plate.

The book's part titles now come from the inverted page, or from the contents when that reads better.

| doc | backend | img_pdf | img_epub | junk_imgs |
|---|---|---|---|---|
| arxiv-d2l | pdfminer | 294 → 294 | **1292 → 1291** | 84 → 84 |
| arxiv-d2l | pymupdf | 294 → 294 | **1290 → 1289** | 85 → 85 |
| pg-calculus-made-easy | pdfminer | 0 → 0 | **576 → 578** | 15 → 15 |
| pg-calculus-made-easy | pymupdf | 0 → 0 | **750 → 748** | 0 → 0 |
| ia-zola-roman-experimental | pdfminer | 0 → 0 | **62 → 14** | **62 → 14** |
| ia-zola-roman-experimental | pymupdf | 0 → 0 | **62 → 13** | **62 → 13** |
| ia-island-plant | pdfminer | 0 → 0 | **56 → 16** | **50 → 10** |
| ia-island-plant | pymupdf | 0 → 0 | **56 → 14** | **50 → 8** |
| ia-innkeeper-source | pdfminer | 0 → 0 | **12 → 2** | **9 → 1** |
| ia-innkeeper-source | pymupdf | 0 → 0 | **12 → 2** | **9 → 1** |
| private book | pdfminer | 0 → 0 | **17 → 0** | **15 → 0** |
| private book | pymupdf | 0 → 0 | **17 → 0** | **15 → 0** |

On the Internet Archive scans, the pictures that went are blank pages (no pixel darker than mid-grey) and the all-black
mask layer paired with every scanned page. The plates stay.

### 6. Metadata → `frontmatter.py`

* **Title:** the largest type on the first 6 pages, confirmed by a second page or a running head; otherwise display type
  (≥2× body) on pages 1–3.
* **Editors:** "Volume coordonné par" / "Sous la direction de" / "Edited by" → `dc:creator` with role `edt`.
* **Publisher and year:** from "© X, 2017" → `dc:publisher`, `dc:date`.
* **ISBN:** only with a valid check digit → `dc:identifier urn:isbn:…`. It may also come from the file name.
* **File-name fallback:** without download-site prefixes and the ISBN.
* **Placeholder authors:** "anonymous" (reportlab's default) is ignored.
* **The book:** `dc:title` goes from "input" to the real title; the 4 editors, the publisher, 2017 and the ISBN are all
  right.

### 7. Cross-page joins → `structure.merge_across_breaks`

* A quotation continues across a page.
* A quotation's end set as a plain paragraph on the next page joins the quotation.
* A lower-case start (or "– lower case") continues the previous paragraph even when it is marked indented, or when the
  previous one ends in "." (an OCR'd abbreviation).
* Running heads whose folio the OCR misread ("39<>", "2O5") are recognised as running heads again
  (`layout._norm_key`).
* What remains in `lower_starts` is mostly quotations introduced by "…:" that start in lower case, which is correct
  typography.

| doc | backend | mid_breaks | lower_starts | order |
|---|---|---|---|---|
| fr-novel-chignole | pdfminer | 0.7 → 0.7 | **3.4 → 2.7** | 1.000 → 1.000 |
| fr-novel-chignole | pymupdf | 0.7 → 0.7 | **3.4 → 2.7** | 0.991 → 0.991 |
| en-novel-my-antonia | pdfminer | **3.4 → 0.9** | **6.9 → 4.3** | 0.997 → 0.997 |
| en-novel-my-antonia | pymupdf | **3.5 → 0.9** | **6.9 → 4.3** | 0.993 → 0.993 |
| arxiv-llama | pdfminer | 5.2 → 5.2 | **62.3 → 59.9** | 0.980 → 0.980 |
| arxiv-llama | pymupdf | 3.0 → 3.0 | **60.1 → 54.4** | 0.965 → 0.965 |
| arxiv-foundation-models | pdfminer | 8.0 → 8.0 | **37.0 → 36.4** | 0.987 → 0.987 |
| arxiv-foundation-models | pymupdf | 42.7 → 42.7 | **67.9 → 67.4** | 0.986 → 0.986 |
| arxiv-d2l | pdfminer | **15.3 → 15.1** | **87.1 → 79.3** | 0.940 → 0.940 |
| arxiv-d2l | pymupdf | **11.3 → 10.8** | **84.6 → 78.2** | 0.953 → 0.953 |
| pg-calculus-made-easy | pdfminer | **47.3 → 46.9** | **102.6 → 98.4** | 0.849 → 0.849 |
| pg-calculus-made-easy | pymupdf | **55.7 → 55.4** | **121.2 → 117.3** | 0.863 → 0.863 |
| pg-descartes-geometrie | pdfminer | **247.8 → 246.2** | **347.0 → 347.7** | 0.927 → 0.927 |
| pg-descartes-geometrie | pymupdf | **114.9 → 115.2** | **256.7 → 254.9** | 0.926 → 0.926 |
| ia-zola-roman-experimental | pdfminer | 20.7 → 20.7 | **90.7 → 88.7** | 0.935 → 0.935 |
| ia-zola-roman-experimental | pymupdf | **214.2 → 214.8** | **615.7 → 615.0** | 0.936 → 0.936 |
| ia-island-plant | pdfminer | **74.3 → 45.6** | **104.7 → 73.7** | 0.977 → 0.977 |
| ia-island-plant | pymupdf | **90.0 → 82.0** | **131.8 → 118.0** | 0.983 → 0.983 |
| ia-innkeeper-source | pdfminer | **74.6 → 75.8** | **164.2 → 166.7** | 0.963 → 0.963 |
| ia-innkeeper-source | pymupdf | **60.6 → 61.5** | **90.9 → 92.3** | 0.984 → 0.984 |
| private book | pdfminer | **9.8 → 5.3** | **22.8 → 12.8** | **0.951 → 0.979** |
| private book | pymupdf | **8.9 → 5.3** | **21.1 → 12.8** | **0.972 → 0.979** |

### 8. Page list

* **Labels:** when the folios agree on one printed → PDF offset (on ≥30 % of the pages, ≥50 % of them agreeing), or when
  the printed contents fixed it.
* **Markers:** an empty `epub:type="pagebreak"` marker (`role="doc-pagebreak"`) opens each printed page. It sits inside
  the paragraph that runs across the break, set when the paragraphs are joined.
* **Navigation:** a hidden `page-list` nav lists the markers actually written.
* **Coverage:** the public documents with consistent folios get a page list too.

| doc | backend | pagelist |
|---|---|---|
| fr-novel-roi-montagnes | pdfminer | **0.000 → 0.973** |
| fr-novel-roi-montagnes | pymupdf | **0.000 → 0.973** |
| fr-novel-glebe | pdfminer | **0.000 → 0.881** |
| fr-novel-glebe | pymupdf | **0.000 → 0.881** |
| en-novel-my-antonia | pdfminer | **0.000 → 0.873** |
| en-novel-my-antonia | pymupdf | **0.000 → 0.873** |
| en-novel-puck | pdfminer | **0.000 → 0.849** |
| en-novel-puck | pymupdf | **0.000 → 0.849** |
| arxiv-mistral | pdfminer | **0.000 → 1.000** |
| arxiv-mistral | pymupdf | **0.000 → 1.000** |
| arxiv-foundation-models | pdfminer | **0.000 → 1.000** |
| arxiv-foundation-models | pymupdf | **0.000 → 1.000** |
| arxiv-d2l | pdfminer | **0.000 → 0.816** |
| arxiv-d2l | pymupdf | **0.000 → 0.813** |
| pg-calculus-made-easy | pdfminer | **0.000 → 0.911** |
| pg-calculus-made-easy | pymupdf | **0.000 → 0.921** |
| ia-zola-roman-experimental | pdfminer | **0.000 → 0.931** |
| ia-zola-roman-experimental | pymupdf | **0.000 → 0.936** |
| ia-innkeeper-source | pdfminer | **0.000 → 0.750** |
| ia-innkeeper-source | pymupdf | **0.000 → 0.750** |
| scan-only-en | pdfminer | **0.000 → 1.000** |
| scan-only-en | pymupdf | **0.000 → 1.000** |
| private book | pdfminer | **0.000 → 0.943** |
| private book | pymupdf | **0.000 → 0.943** |

The other public documents have no readable folios (or no agreeing offset) and get no page list.

### 9. OCR corrections → `ocrfix.py` (OCR'd books only)

Fixed patterns:
* "lbid" → "Ibid" and "Tbe" → "The";
* "xix" + superscript "c" → "e";
* spaced or misread digits in years and page numbers.

Lexicon changes:
* The lexicon is the book itself. A word changes only when its `î`→`ï`/`i` or `rn`↔`m` variant, or its camelCase split,
  occurs ≥3 times in the book and the original at most once.
* "cl"/"d" and "li"/"h" were left out: rare real words ("clans") would become frequent ones ("dans").

On the book: 91 changes (pdfminer): 39 roman "c" → "e", 19 "lbid", 10 "Tbe", 14 camelCase splits, 6 spaced years, 2 lexicon words ("î" → "i" / "rn" → "m"), 1 "O" read for a zero. All 16 lexicon and camelCase changes and a random sample of the others were checked by hand:
no wrong correction.

### Public corpus: means, before → after

18 public documents; the private book is left out of the means.

| backend | word_recall | word_precision | order | mid_breaks | hyph_left | hdr_leak | pnum_leak | lspaced | glued | lower_starts | junk_imgs | pagelist | epubcheck |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pdfminer | 0.983 → 0.983 | 0.992 → 0.992 | 0.948 → 0.948 | **35.8 → 34.0** | 1.6 → 1.6 | 0.005 → 0.005 | 0.053 → 0.053 | **3.48 → 3.47** | 13.7 → 13.7 | **70.3 → 67.6** | **12.8 → 7.500** | **0.000 → 0.555** | 0.000 → 0.000 |
| pymupdf | 0.984 → 0.984 | 0.993 → 0.993 | 0.950 → 0.950 | **41.8 → 41.3** | 1.0 → 1.0 | 0.012 → 0.012 | 0.057 → 0.057 | **3.06 → 3.03** | **16.1 → 16.0** | **100.5 → 98.6** | **13.5 → 8.000** | **0.000 → 0.555** | 0.000 → 0.000 |

Structure columns that moved (chapters / headings / chapter ground truth / running heads):

| doc | backend | chapters | headings | outline_match | ch_found | sec_found | ch_spurious | hdr_leak |
|---|---|---|---|---|---|---|---|---|
| arxiv-d2l | pdfminer | **187 → 188** | **1379 → 1380** | 0.998 → 0.998 | – → – | – → – | – → – | **0.000 → 0.001** |
| ia-zola-roman-experimental | pdfminer | 9 → 9 | **45 → 46** | – → – | 7 → 7 | 13 → 13 | 0 → 0 | 0.037 → 0.037 |
| ia-zola-roman-experimental | pymupdf | 9 → 9 | **51 → 52** | – → – | 7 → 7 | 13 → 13 | 0 → 0 | 0.085 → 0.085 |
| ia-island-plant | pdfminer | 4 → 4 | **4 → 5** | – → – | 3 → 3 | – → – | 0 → 0 | 0.000 → 0.000 |
| ia-island-plant | pymupdf | 4 → 4 | **6 → 8** | – → – | 3 → 3 | – → – | 0 → 0 | 0.000 → 0.000 |
| private book | pdfminer | **5 → 23** | **140 → 119** | – → – | – → – | – → – | – → – | **0.132 → 0.000** |
| private book | pymupdf | **5 → 23** | **139 → 119** | – → – | – → – | – → – | – → – | 0.000 → 0.000 |

### What moved the wrong way (investigated)

* **Private book, character recall 0.982 → 0.976 (word recall 0.980 → 0.976 with PyMuPDF):** by design. The printed
  Sommaire pages are dropped (the navigation replaces them), and they hold 0.48 % of the book's text.
* **Internet Archive scans, `img_epub` down (Island 56 → 16 / 14, Zola 62 → 14 / 13, Innkeeper 12 → 2):** checked
  picture by picture. What went is blank pages (no pixel darker than mid-grey) and the all-black mask layer that came with
  each scanned page; `junk_imgs` falls by the same amount. The pictures that stay are the plates and decorations.
* **Innkeeper, `mid_breaks` 74.6 → 75.8 and `lower_starts` 164.2 → 166.7:** same count of breaks and lower-case starts,
  one paragraph fewer in the denominator (67 → 66).
* **Island (PyMuPDF) headings 6 → 8, Zola +1, Island (pdfminer) +1:** running-head variants or OCR noise on a page whose
  picture went ("ISLAND PLANT", "_i"). Chapters and sections against the ground truth are unchanged (Island 3/3, Zola 7/7
  and 13/13, 0 spurious).
* **D2L (pdfminer): one more chapter and heading:** a real section title ("Introduction to Gaussian Processes") became a
  heading. Header leak goes from 0.000 to 0.001 (one line) and one picture fewer; outline match is unchanged.
* **Private book, `glued` 2.8 → 3.0 (pdfminer):** spaces pdfminer used to add at real but glyph-less gaps are now added
  only at wide gaps. The camelCase splitter takes back most of them.
* **Interim run (fixed before the final run):**
  * Zola got 24 chapter files from its flat TABLE. Fixed by the structure condition.
  * Galois lost 1.2 % of its words to a mid-text "NOTES" block taken for endnotes. Fixed by the stricter region end.
  * Roi des montagnes got 9 headings from its contents rows. I reverted a contents-is-not-a-table rule in the table
    detector; the contents parser reads the table instead.
  * epubcheck duplicate-id and fragment errors: each page marker is written once, and the page list holds only written
    markers.
  * A noteref linked across documents: linking is now per spine document.
* **Test suite:** 416 passed, 2 skipped. One failure, `web/tests/test_cli.py::test_launch_failure_pauses_on_windows`:
  it passes alone, fails only in the full run (order-dependent), and fails the same way on `main` (ba5e2be). It does
  not involve the converter core.

### Not fixed

* **OCR text left as read:**
  * Text the ABBYY layer lacks (some endnotes, a few lines) is not recovered; the layer is used as is.
  * Part titles read by tesseract from the inverted dividers keep small errors when the contents is no better.
  * Titles keep the Sommaire's misreads where the body's wording is worse, e.g. a valid word where two were printed.
* **References:** superscripts misread as letters or lost by the OCR stay unlinked (187 of 503 superscripts). Plain
  "word23" references are never linked.
* **Bylines:** names on two lines of the same block are joined without a separator in one byline (chapter 1).
* **Credits:** translator credits are printed at the end of each chapter, just before Notes. They stay as ordinary
  paragraphs, not `credit` paragraphs.
* **Glued words:** only camelCase glue is split. All-lower-case glue ("danslavie") needs a real dictionary, since the
  book's own words would wrongly split real compounds ("contrepartie").
* **Two-column notes:** split by number and column; a note whose number the OCR misread ("l." for "1.") is merged into
  the previous one.
* **Per-fix runs:** all fixes were measured in one before/after pair, plus one interim run after fixes 1, 5 and 6
  (labels `r5-before`, `r5-mid`, `r5-after` in `tests/corpus/out`). There is no separate full-corpus run per fix.

## Round 5b: review of round 5

"Before" is `main` (`r5-before`), the middle value is round 5 (`r5-after`), and "after" is this tree (`r5b-after`). All
19 documents were run with both backends and epubcheck on. The test suite: 427 passed, 2 skipped, no failure.

| doc | backend | nav entries | garbled | unsupported | headings | GT chapters | GT sections | spurious | lower-case starts /1000 |
|---|---|---|---|---|---|---|---|---|---|
| ia-zola-roman-experimental | pdfminer | 45 → 46 → 42 | 0 → 1 → 0 | 19 → 20 → 18 | 45 → 46 → 42 | 7 → 7 → 7 | 13 → 13 → 13 | 0 | 90.7 → 88.7 → 88.2 |
| ia-zola-roman-experimental | pymupdf | 47 → 48 → 42 | 0 → 1 → 0 | 19 → 20 → 17 | 51 → 52 → 46 | 7 → 7 → 7 | 13 → 13 → 13 | 0 | 615.7 → 615.0 → 612.0 |
| ia-island-plant | pdfminer | 4 → 5 → 4 | 0 → 1 → 0 | 0 → 1 → 0 | 4 → 5 → 4 | 3 → 3 → 3 | – | 0 | 104.7 → 73.7 → 73.4 |
| ia-island-plant | pymupdf | 6 → 8 → 4 | 0 → 1 → 0 | 2 → 4 → 0 | 6 → 8 → 4 | 3 → 3 → 3 | – | 0 | 131.8 → 118.0 → 123.0 |
| ia-innkeeper-source | pdfminer | 3 → 3 → 2 | 0 | 1 → 1 → 0 | 4 → 4 → 2 | 1 → 1 → 1 | – | 0 | 164.2 → 166.7 → 173.9 |
| ia-innkeeper-source | pymupdf | 3 → 3 → 2 | 0 | 1 → 1 → 0 | 5 → 5 → 2 | 1 → 1 → 1 | – | 0 | 90.9 → 92.3 → 101.4 |
| private book | both | 121 → 119 → 115 | 0 | – | 140 → 119 → 115 | 21 of 21 units open a document | nav recall 0.966, precision 0.983 | – | 22.8 → 12.8 → 12.8 |

Public documents in total, `nav_garbled` / `nav_unsupported`:
* pdfminer: 187 / 163 (main) → 189 / 166 (round 5) → 187 / 162.
* PyMuPDF: 185 / 166 → 187 / 170 → 185 / 162.

**1. Junk navigation entries ("MeeISLAND PLANT", "_i").** The text of those pages was unchanged. Round 5 dropped the blank
page pictures that sat between the title-page lines, and some of those OCR lines then passed the size-based heading test.
Three rules now apply to OCR'd text (`structure.convert_blocks`):
* a line on a page with under 150 characters of OCR text (title page, bookplate, plate) is never a heading;
* in a scanned book with a chapter plan, an OCR line before the first chapter is not a heading;
* an OCR heading shaped like noise is not a heading: under 60 % letters, or a word glued across a case change ("MeeISLAND").

Effect on the navigation, against `main`:
* **Island:** pdfminer now has the same entries as `main`. PyMuPDF also loses `main`'s title-page entries "MARY CATHERINE
  LEE" and "AN ISLAND PLANT.".
* **Zola:** the title-page entries go ("ROMAN EXPÉRIMENTAL", "EMILE ZOLA LE ROMAN", "EXPÉRIMENTAL", "PARIS
  IBLIOTHÈQUE-CHARPENTIER"), plus, with PyMuPDF, a duplicate half-title entry "NATURALISME AU THÉÂTRE". The 7 chapters and
  13 sections are all still found.
* **Innkeeper:** the title-page author line goes.
* **Innkeeper, lower-case starts up:** an OCR-noise line on its title page used to be a heading and is now a paragraph.
  The denominator is small (about 69 paragraphs).

New evaluator metrics:
* `nav_garbled`: navigation entries shaped like OCR noise.
* `nav_unsupported`: entries that match no outline or hand-checked title. The first entry and Notes / Bibliographie /
  Conclusion are excepted.

**2. Bylines (book).** In chapters 6, 9, 12 and 15 the authors are printed in the same OCR block as the title. That block
was skipped as "the author line", so the title was never matched: a heading was made from the contents, and the
"author + title" block stayed as a section, which was chapter 15's duplicate entry. Now a block starting with the
contents' authors is split: the closest-matching name prefix becomes `<p class="byline">` and the rest is matched as the
title. All 15 numbered chapters have a byline on both backends, and no "author + title" entries remain.

**3. Épilogue (book).** An unnumbered contents entry directly followed (within 2 printed pages) by a numbered chapter is a
divider holding it, like a part. So "Épilogue" holds chapter 15 and "Introduction" holds chapter 1, as in the printed
book, where both are divider pages before their text.

Choosing between the two readings of a title:
* **Same letters, different accents:** the one with more accents wins, since OCR drops accents more often than it adds
  them ("Épilogue", not "Epilogue").
* **Different words:** the body's wording must beat the contents' by a margin. On PyMuPDF's render, tesseract read
  "Epiloguc", which occurs once in the book; that occurrence alone no longer decides.

**4. PDF metadata strings.** My Antonia's Info title is UTF-8 bytes without a byte-order mark, and pdfminer decoded it as
PDFDocEncoding ("My Ã†ntonia").
* **Decoding:** `backends.common.decode_pdf_string` handles UTF-16 BE/LE and UTF-8 with a byte-order mark. Bytes that are
  valid multibyte UTF-8 are read as UTF-8, otherwise as PDFDocEncoding. Used for the Info title / author and for pdfminer
  outline titles.
* **Repair:** `repair_mojibake` fixes already-decoded strings (PDFDocEncoding, then Windows-1252, then Latin-1) and is
  applied to both backends' metadata.
* **Result:** `dc:title` is "My Ántonia" with both backends.

**On the way: PyMuPDF spacing accents.** TeX sets an accent before a capital in its own font, as a one-character span
("G" "´" "EOM"). The accent now joins its letter when it combines and both spans are text of the same size: Descartes
"LA GÉOMÉTRIE", "NOUVELLE ÉDITION", "LIVRE TROISIÈME". A first version also combined backticks before code and hats on
single math variables. That moved D2L's formula pictures (+3) and Mistral's reading order (−0.004); the final rule
excludes both, and those documents match `main` again.

**Still differing from `main`, and why:**
* **D2L, PyMuPDF navigation:** two outline sub-entries left the navigation. "Convenience Functions" was a second entry
  pointing a few blocks before the heading that already has its own entry. "Training and Prediction" is placed by the
  PDF outline on page 423, while the heading is on page 425. On `main` it linked to an unrelated paragraph; now it falls
  on the same block as the previous outline entry and is merged with it. The headings themselves are unchanged.
* **D2L, pdfminer:** one more navigation entry, "Introduction to Gaussian Processes", a real section title that became a
  heading in round 5.
* **Foundation Models:** its first navigation entry is now the full title, from the title page.

Tests:
* `test_book_structure.py`: noise headings, author prefix → byline, divider entries holding the next chapter.
* `test_text_layer.py`: PDF metadata strings, synthetic PDF with a raw UTF-8 title; an accent in its own font.

## Round 5c: words cut by page markers

**The regression.** Zola converted with the default options (`ocr: auto`) had about 60 words cut in two against `main`
("phy siologie", "con naissance", "elle- même."). The cause was not the space-glyph rule, but where the round-5
page-break marker went. When a word hyphenated across a page break was joined, the empty
`<span epub:type="pagebreak">` was inserted between its two halves. Readers show the word whole, but any tool that
treats tags as word boundaries (search, read-aloud, a word diff) sees two words.

Why the corpus run missed it:
* The run uses `ocr: off`, as in the manifest, and with that option those joins did not cut runs inside the word.
* The evaluator reads each element's text joined across tags.

**The fix.** `structure._insert_between_words`: a marker that would fall inside a word moves to the next space, which
covers hyphenated words, compounds kept with their hyphen ("elle-même") and a word followed by punctuation. Zola with
default options now differs from `main` only by 7 OCR corrections: "chirniste" → "chimiste", "rn'a" → "m'a",
"rn'ont" → "m'ont", "3o8" → "308", "200 1." → "2001.", "dontParis" → "dont Paris", "accuseMichelle." →
"accuse Michelle.".

**Also changed: spaces in formulas on pages with space glyphs.** The diff also turned up ") −γ max" → ")−γmax" in one
D2L formula (PyMuPDF). Formulas have no space glyphs and their spacing is narrower than the "missing space" threshold.
Between math-font glyphs, the usual narrow gap (0.12 em) is now a space again, in both backends.

**New metrics.** The evaluator now reads a page marker as a word boundary, so a marker inside a word counts as a cut.
`split_words` and `joined_words` are given per 10k words:
* **Split:** two EPUB words whose concatenation is a reference word but which never stand side by side in the
  reference. Words the reference itself glues in camelCase ("accuseMichelle") are excepted.
* **Joined:** an EPUB word that is not in the reference but is two reference words that stand side by side there.

Absolute counts, `main` → this tree, summed over the 18 public documents:

| backend | split + joined, `main` | split + joined, now |
|---|---|---|
| pdfminer | 839 | 838 |
| PyMuPDF | 1161 | 1161 |

Per document there is no increase anywhere; the one decrease is My Ántonia (1 → 0). On the private book, split words fall
2290 → 89 (pdfminer) and 788 → 88 (PyMuPDF). Joined words rise 1 → 29 and 13 → 29: these are words the ABBYY layer
itself glued. pdfminer's gap rule used to cut them apart by chance, along with the letter-spaced ones. Dictionary-based
splitting is the next round.

**My Ántonia navigation (74 → 73 entries).** The entry for the front matter is still there: it is the first entry,
"My Ántonia", linking to ch001.xhtml (title page, contents, illustrations). What went is a second entry, a link to the
title-page heading a few blocks into that same document. With the metadata title decoded correctly, its title equals its
parent's, and the existing rule leaves out a section repeating its chapter's title. On `main` both were listed only
because the parent read "My Ã†ntonia".

Runs: `r5c-after`, all 19 documents with both backends, epubcheck 0 errors everywhere. Other metrics are as in round 5b.
The test suite: 429 passed, 2 skipped. New tests: `test_a_page_marker_never_cuts_a_word` (`test_book_structure.py`) and
`test_a_spacing_accent_set_in_its_own_font_joins_its_letter` (`test_text_layer.py`).

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
