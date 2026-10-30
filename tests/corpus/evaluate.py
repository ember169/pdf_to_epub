"""Measure conversion quality on the real-world corpus (see manifest.json, fetch.py).

    python tests/corpus/evaluate.py --label before            # all docs, every installed backend
    python tests/corpus/evaluate.py --label after --ids arxiv-llama --backends pdfminer
    python tests/corpus/evaluate.py --compare before after     # markdown before/after table

Each conversion runs in its own subprocess (wall time, peak RSS via wait4, hard timeout). Results go to
tests/corpus/out/<label>/ (results.json, report.md, the EPUBs). The reference text is extracted with pypdfium2's
text layer, which neither backend uses for text, so it is an independent baseline; image-only excerpts are scored
against the text layer of the pages they were derived from.

Metrics (all on normalised text: NFKC, lower case, intra-word hyphens and soft hyphens removed; words are runs of letters):
  word_recall / word_precision  multiset overlap of alphabetic tokens, EPUB vs reference
  char_recall / char_precision  multiset overlap of letters and digits (catches lost accents, (cid:N) garbage)
  pre_share                     share of the text rendered as <pre> code blocks (should be ~0 outside programming books)
  pua                           private-use / U+FFFD characters left in the EPUB (unreadable without the PDF font), per 10k chars
  order                         share of reference 6-word shingles (per page, margins excluded) found in the EPUB
  order_2col                    the same on pages detected as two-column (stream order of LaTeX two-column = reading order)
  mid_breaks                    paragraphs ending without terminal punctuation followed by one starting lower case, per 1000 <p>
  hyph_left                     leftover line-end hyphens ("inter- national", "inter-national" when "international" is used), per 10k words
  hyph_joined                   compounds hyphenated mid-line in the PDF that were glued in the EPUB, per 10k words
  hdr_leak                      running header/footer lines (text recurring in page margins on >=3 pages) still in the EPUB, share
                                (heads printed with their page number are matched exactly; others by excess occurrences)
  pnum_leak                     page numbers left in the text (standalone blocks or glued to the neighbouring words), share
  outline / nav / chapters / headings, outline_match (share of outline titles found in the EPUB navigation)
  headings_per_page, chapters_per_100p  structure density; on scans, spurious headings from OCR size noise show up here
  gt_chapters, ch_found, sec_found, ch_spurious
                                hand-checked chapter list (manifest `chapters_gt`, IA scans): level-1 titles found in the EPUB
                                navigation, level-2 titles found, and EPUB chapter files whose first heading is no GT title
                                (beyond one front-matter file)
  formula_imgs                  display formulas rendered as images (<img class="formula">); sub_sup: <sub>/<sup> elements
                                (text metrics read <sub>/<sup> as separate tokens and a formula picture as its alt text)
  crops, crop_bleed, crop_clip  formula pictures checked against pdfium's glyph boxes (the conversion worker records each crop):
                                pictures crossed by a glyph of another line; pictures cutting one of the formula's own
                                glyphs or with ink on a 1-px border row/column (crop_edge_ink alone in results.json)
  lspaced                       letter-spaced runs ("f e m m es", "2 0 1 0": 4+ single characters in a row), per 10k words
  glued                         words glued together ("ofCalifornia", two reference words as one), per 10k words
  split_words, joined_words     a word cut in two (together a reference word, never side by side there) / two reference words that
                                stand side by side in the reference run together, per 10k words (a page-break marker
                                inside a word counts as a cut)
  noterefs / sup_unlinked       note references linked in the EPUB / superscript numbers left without a link
  note_items                    notes in the EPUB (endnote list items + footnote asides)
  junk_imgs                     pictures that are blank, uniform, specks only or almost entirely black
  lower_starts                  paragraphs / quotes starting in lower case (or "– lower") after another one, per 1000
  pagelist                      page-list entries (printed page numbers) per PDF page
  gt_units, spine_units, spine_docs, nav_recall, nav_precision, title_ok
                                private books with a hand-checked structure (manifest `gt_file`, git-ignored): parts /
                                chapters / introduction / epilogue that open a spine document, spine documents, share of
                                units + sections + front matter in the navigation, share of navigation entries that are
                                one of them (or Notes / Bibliographie / the book title), dc:title right
  nav_garbled, nav_unsupported  navigation entries shaped like OCR noise (< 60 % letters, "MeeISLAND"); entries matching no
                                outline / hand-checked title (first entry and Notes / Bibliographie / Conclusion excepted)
  img_pdf / img_epub            distinct embedded images (>=48 px, not full-page scans) vs images in the EPUB
  epubcheck                     ERROR+FATAL count (java, or the pdftoepub-test Docker image), -1 when not run
  s_per_page, rss_mb            wall time per page and peak resident memory of the conversion process
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CORPUS = HERE.parent / ".corpus"
OUT = HERE / "out"
XHTML = "{http://www.w3.org/1999/xhtml}"
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre", "figcaption", "dt", "dd"}
TERMINAL = tuple(".!?:;…»\"”’)]*")
MARGIN = 0.08  # top/bottom share of the page height treated as header/footer zone
# "x" alone is a variable and "dx" a differential, not folios: front-matter numbers stay below D
ROMAN = re.compile(r"^(?=[ivxlc]{2,}$)c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)


# ---------------------------------------------------------------- text normalisation

SPACING_ACCENTS = {"`": "\u0300", "\u00b4": "\u0301", "\u02c6": "\u0302", "\u02dc": "\u0303", "\u00a8": "\u0308", "\u00b8": "\u0327",
                   "\u02c7": "\u030c"}


def norm(text: str) -> str:
    # old TeX fonts draw accents as separate glyphs ("esp`ece"); compare the composed letters on both sides
    text = re.sub("([" + "".join(SPACING_ACCENTS) + "])([a-zA-Z\u0131])",
                  lambda m: SPACING_ACCENTS[m.group(1)] and m.group(2).replace("\u0131", "i") + SPACING_ACCENTS[m.group(1)], text)
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    # pdfium marks a line-end hyphenation inside the word with U+FFFE ("continu\ufffeous"): the word continues
    text = text.replace("\ufffe", "").replace("\x02", "-\n").replace("\xad", "").replace("‐", "-").replace("‑", "-")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # line-end hyphenation
    text = re.sub(r"(?<=\w)-(?=\w)", "", text)  # intra-word hyphens: "well-known" == "wellknown" on both sides
    return text.lower()


def words(text: str) -> list[str]:
    # letters only: "m1", "m 1" and "m<sub>1</sub>" are the same word whatever the extractor glues
    return re.findall(r"[^\W\d_]+", norm(text))


def chars(text: str) -> collections.Counter:
    return collections.Counter(c for c in norm(text) if c.isalnum())


def overlap(ref: collections.Counter, out: collections.Counter) -> tuple[float, float]:
    common = sum((ref & out).values())
    return (common / max(1, sum(ref.values())), common / max(1, sum(out.values())))


def shingles(ws: list[str], k: int = 6) -> list[tuple]:
    return [tuple(ws[i:i + k]) for i in range(len(ws) - k + 1)]


# ---------------------------------------------------------------- reference (pypdfium2 text layer)

def text_lines(tp) -> list[tuple[float, float, float, float, str]]:
    """The page text in stream order, cut into lines at pdfium's line breaks, each with the box of its glyphs.
    (Per-rectangle extraction duplicates text on OCR layers whose word boxes overlap.)"""
    text = tp.get_text_range()
    n = tp.count_chars()
    out = []
    cur, box = [], None
    for i, ch in enumerate(text):
        if ch in "\r\n":
            if cur and "".join(cur).strip():
                out.append((*box, "".join(cur).strip()))
            cur, box = [], None
            continue
        cur.append(ch)
        if i < n and not ch.isspace():
            l, b, r, t = tp.get_charbox(i)
            box = (l, b, r, t) if box is None else (min(box[0], l), min(box[1], b), max(box[2], r), max(box[3], t))
        if box is None and not ch.isspace():
            box = (0, 0, 0, 0)
    if cur and box and "".join(cur).strip():
        out.append((*box, "".join(cur).strip()))
    return out


def reference(pdf: Path, pages: list[int] | None = None) -> dict:
    """Per page: body text (stream order, margins excluded), margin lines, two-column flag, image count; outline."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument(str(pdf))
    out_pages = []
    img_hashes: set = set()
    for pno in pages or range(1, len(doc) + 1):
        page = doc[pno - 1]
        w, h = page.get_size()
        tp = page.get_textpage()
        rects = text_lines(tp)
        top, bottom = h * (1 - MARGIN), h * MARGIN
        margin = [(("top" if t >= top else "bottom"), txt) for l, b, r, t, txt in rects if b >= top or t <= bottom]
        body = [x for x in rects if not (x[1] >= top or x[3] <= bottom)]
        # prose lines only: formula fragments and figure labels are narrow too (they made math pages "two-column")
        prose = [x for x in body if len(x[4]) >= 25]
        narrow = [x for x in prose if x[2] - x[0] < 0.45 * w]
        left = sum(1 for x in narrow if x[2] < 0.55 * w)
        right = sum(1 for x in narrow if x[0] > 0.45 * w)
        twocol = left >= 8 and right >= 8 and (left + right) >= 0.6 * max(1, len(prose))
        n_img = 0
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
            try:
                pw, ph = obj.get_px_size()
                l, b, r, t = obj.get_bounds()
            except Exception:  # noqa: BLE001
                continue
            if pw < 48 or ph < 48 or ((r - l) * (t - b) > 0.7 * w * h):
                continue
            key = (pw, ph)
            try:
                key = (pw, ph, hash(bytes(obj.get_data(decode_simple=False))[:65536]))
            except Exception:  # noqa: BLE001
                pass
            if key not in img_hashes:
                img_hashes.add(key)
                n_img += 1
        out_pages.append({"pno": pno, "body": "\n".join(x[4] for x in body), "margin": margin, "twocol": twocol, "images": n_img})
        tp.close()
        page.close()
    outline = []
    if pages is None:
        try:
            for item in doc.get_toc():
                outline.append({"level": item.level, "title": item.get_title() if hasattr(item, "get_title") else item.title})
        except Exception:  # noqa: BLE001
            pass
    doc.close()
    return {"pages": out_pages, "outline": outline}


# ---------------------------------------------------------------- EPUB reading

def read_epub(path: Path) -> dict:
    from lxml import etree

    z = zipfile.ZipFile(path)
    opf_name = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml")).group(1).decode()
    opf = etree.fromstring(z.read(opf_name))
    base = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
    ns = {"o": "http://www.idpf.org/2007/opf"}
    manifest = {i.get("id"): i for i in opf.iterfind(".//o:manifest/o:item", ns)}
    spine = [manifest[r.get("idref")].get("href") for r in opf.iterfind(".//o:spine/o:itemref", ns)]
    blocks: list[tuple[str, str, int]] = []  # (tag, text, chapter index)
    headings = collections.Counter()
    n_img = n_formula = n_subsup = 0
    first_heads = []  # first heading of each content document
    extra = collections.Counter()  # noterefs, unlinked superscript numbers, endnote items, lowercase starts, junk images
    import io

    from PIL import Image, ImageStat
    for ci, href in enumerate(spine):
        raw = z.read(base + href)
        # "x<sup>2</sup>" is "x" and "2" (as in the PDF text layer), not the word "x2"; a formula picture's text is its
        # alt text (linearised), which readers and screen readers expose
        raw = re.sub(rb"<(/?)(sub|sup)>", lambda m: b" <" + m.group(1) + m.group(2) + b"> ", raw)
        # a page-break marker is a boundary for text tools (search, read-aloud): one inside a word splits it
        raw = re.sub(rb'<span epub:type="pagebreak"[^>]*></span>', b" ", raw)
        raw = re.sub(rb'(<img class="formula"[^>]*?alt=")([^"]*)("[^>]*/>)', rb"\1\2\3<span> \2 </span>", raw)
        root = etree.fromstring(raw)
        if not href.endswith("nav.xhtml"):
            first_heads.append(next(("".join(h.itertext()).strip() for h in root.iter(*(XHTML + f"h{i}" for i in range(1, 7)))), ""))
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            tag = el.tag.replace(XHTML, "")
            if tag == "img":
                n_img += 1
                n_formula += "formula" in (el.get("class") or "").split()
                if "formula" not in (el.get("class") or "").split():
                    try:  # a page picture that is blank / uniform / specks only
                        im = Image.open(io.BytesIO(z.read(base + (href.rsplit("/", 1)[0] + "/" if "/" in href else "")
                                                          + el.get("src")))).convert("L")
                        im.thumbnail((200, 200))
                        st = ImageStat.Stat(im)
                        dark = sum(im.histogram()[:128]) / max(1, im.width * im.height)
                        extra["junk_imgs"] += st.stddev[0] < 8 or dark < 0.004 or dark > 0.85
                    except Exception:  # noqa: BLE001
                        pass
            if tag == "a" and el.get("{http://www.idpf.org/2007/ops}type") == "noteref":
                extra["noterefs"] += 1
            if tag == "sup" and re.fullmatch(r"\s*\d{1,3}\s*", "".join(el.itertext())) and not any(
                    isinstance(a.tag, str) and a.tag.endswith("}a") for a in el.iterancestors()):
                extra["sup_unlinked"] += 1
            if tag == "li" and el.get("{http://www.idpf.org/2007/ops}type") in ("endnote", "footnote"):
                extra["note_items"] += 1
            if tag == "aside" and el.get("{http://www.idpf.org/2007/ops}type") in ("footnote", "endnote"):
                extra["note_items"] += 1
            if tag in ("sub", "sup"):
                n_subsup += 1
            if tag in BLOCK_TAGS:
                anc = el.getparent()
                nested = False
                while anc is not None:
                    if isinstance(anc.tag, str) and anc.tag.replace(XHTML, "") in BLOCK_TAGS:
                        nested = True
                        break
                    anc = anc.getparent()
                if nested:
                    continue
                if tag[0] == "h" and tag[1:].isdigit():
                    headings[tag] += 1
                ctx = "aside" if any(isinstance(a.tag, str) and a.tag.endswith(("aside", "blockquote")) for a in el.iterancestors()) else ""
                blocks.append((tag if not ctx else f"{ctx}/{tag}", "".join(el.itertext()), ci))
    nav_titles = []
    nav_item = next((i for i in manifest.values() if "nav" in (i.get("properties") or "").split()), None)
    if nav_item is not None:
        nav = etree.fromstring(z.read(base + nav_item.get("href")))
        for n in nav.iter(XHTML + "nav"):
            if n.get("{http://www.idpf.org/2007/ops}type") == "toc":
                nav_titles = ["".join(a.itertext()).strip() for a in n.iter(XHTML + "a")]
            if n.get("{http://www.idpf.org/2007/ops}type") == "page-list":
                extra["pagelist"] = sum(1 for _ in n.iter(XHTML + "a"))
    dc_title = "".join(t.text or "" for t in opf.iterfind(".//{http://purl.org/dc/elements/1.1/}title"))
    chapters = sum(1 for h in spine if not h.endswith("nav.xhtml"))
    # paragraphs / quotes starting in lower case after another one: the rest of a sentence cut at a page break
    prev = None
    for tag, text, _ in blocks:
        t = text.strip()
        if tag in ("p", "blockquote/p") and t:
            if prev in ("p", "blockquote/p") and re.match(r"^(?:[–—-]\s*)?[^\W\d_A-ZÀ-Þ]", t):
                extra["lower_starts"] += 1
            extra["paras_all"] += 1
        prev = tag if t else prev
    return {"blocks": blocks, "headings": dict(headings), "images": n_img, "nav": nav_titles, "chapters": chapters,
            "first_heads": first_heads, "formula_imgs": n_formula, "sub_sup": n_subsup, "extra": dict(extra),
            "dc_title": dc_title}


# ---------------------------------------------------------------- metrics

def margin_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", norm(text))).strip()


def is_pnum(text: str) -> bool:
    t = text.strip().strip("-–—[]()·•. ")
    return bool(t) and (t.isdigit() or bool(ROMAN.match(t))) and len(t) <= 6


def title_key(text: str) -> str:
    text = re.sub(r"^\s*(chapter|chapitre|part|partie|book|livre)?\s*[ivxlc\d]+\s*[.:—–-]\s*", "", norm(text))  # "II. The ..."
    text = re.sub(r"^\s*\w+(?:e|ème)?\s+partie\s*[.:—–-]\s*", "", text)  # "Deuxième partie — Les villes"
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text)


def garbled(text: str) -> bool:
    t = text.strip()
    letters = sum(c.isalpha() for c in t)
    nonspace = sum(not c.isspace() for c in t)
    if re.fullmatch(r"[\dIVXLCivxlc]+(?:[.\-][\dA-Za-z]{1,3})*\.?", t):  # numbering only ("II", "1.B.")
        return False
    return (not nonspace or letters < 0.6 * nonspace
            or re.search(r"\b[A-ZÀ-Þ]?[a-zà-ÿ]{2,}[A-ZÀ-Þ]{3,}", t) is not None)


def same_title(a: str, b: str) -> bool:
    import difflib

    a, b = title_key(a), title_key(b)
    if len(a) < 3 or len(b) < 3:
        return False
    short, long_ = sorted((a, b), key=len)
    if short in long_ and len(short) >= 0.6 * len(long_):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def chapter_metrics(gt: dict, ep: dict) -> dict:
    l1, l2 = [g["title"] for g in gt["level1"]], [g["title"] for g in gt.get("level2", [])]
    nav = ep["nav"]
    found = sum(1 for t in l1 if any(same_title(t, n) for n in nav))
    sec = sum(1 for t in l2 if any(same_title(t, n) for n in nav))
    stray = sum(1 for h in ep["first_heads"] if not any(same_title(t, h) for t in l1 + l2))
    return {"gt_chapters": len(l1), "ch_found": found, "sec_found": sec if l2 else None, "gt_sections": len(l2),
            "ch_spurious": max(0, stray - 1)}


def private_gt_metrics(gt: dict, ep: dict) -> dict:
    """Against a hand-checked structure (private book): spine documents per unit, navigation precision / recall,
    metadata title."""
    units = gt.get("units", [])
    sections = [s for u in units for s in u.get("sections", [])]
    heads = ep["first_heads"]
    spine_hit = sum(1 for u in units if any(same_title(u["title"], h) for h in heads))
    nav = ep["nav"]
    items = [u["title"] for u in units] + sections + [f["title"] for f in gt.get("front_matter", [])]
    generic = ("notes", "bibliographie", "bibliography", "conclusion", "references", "references")
    nav_ok = sum(1 for n in nav if any(same_title(t, n) for t in items) or title_key(n) in generic
                 or same_title(n, gt.get("metadata", {}).get("title", "")))
    return {"gt_units": len(units), "spine_units": spine_hit, "spine_docs": ep["chapters"],
            "nav_recall": sum(1 for t in items if any(same_title(t, n) for n in nav)) / max(1, len(items)),
            "nav_precision": nav_ok / max(1, len(nav)),
            "title_ok": int(same_title(ep.get("dc_title", ""), gt.get("metadata", {}).get("title", "")))}


def metrics(ref: dict, ep: dict, gt: dict | None = None) -> dict:
    pages = ref["pages"]
    ref_text = "\n".join(p["body"] + "\n" + "\n".join(t for _, t in p["margin"]) for p in pages)
    out_text = "\n".join(b[1] for b in ep["blocks"])
    rw, ow = collections.Counter(words(ref_text)), collections.Counter(words(out_text))
    m: dict = {}
    m["word_recall"], m["word_precision"] = overlap(rw, ow)
    m["char_recall"], m["char_precision"] = overlap(chars(ref_text), chars(out_text))
    m["pre_share"] = sum(len(b[1]) for b in ep["blocks"] if b[0].endswith("pre")) / max(1, len(out_text))
    m["pua"] = 10000 * sum(1 for c in out_text if 0xE000 <= ord(c) <= 0xF8FF or c == "\ufffd") / max(1, len(out_text))
    m["missing_top"] = [w for w, _ in (rw - ow).most_common(15)]
    m["extra_top"] = [w for w, _ in (ow - rw).most_common(15)]
    # reading order / joining: reference shingles found in the EPUB
    out_words = words(out_text)
    out_sh = set(shingles(out_words))
    found = total = found2 = total2 = 0
    for p in pages:
        sh = shingles(words(p["body"]))
        hit = sum(1 for s in sh if s in out_sh)
        found += hit
        total += len(sh)
        if p["twocol"]:
            found2 += hit
            total2 += len(sh)
    m["order"] = found / total if total else None
    m["order_2col"] = found2 / total2 if total2 else None
    m["twocol_pages"] = sum(1 for p in pages if p["twocol"])
    # paragraphs broken mid-sentence
    paras = [(b[1].strip(), b[2]) for b in ep["blocks"] if b[0] == "p"]
    breaks = 0
    examples = []
    for (a, ca), (b, cb) in zip(paras, paras[1:]):
        if a and b and ca == cb and not a.endswith(TERMINAL) and a[-1].isalpha() and b[0].islower():
            breaks += 1
            if len(examples) < 5:
                examples.append(f"…{a[-40:]} ¶ {b[:40]}…")
    m["mid_breaks"] = 1000 * breaks / max(1, len(paras))
    m["mid_break_examples"] = examples
    m["paragraphs"] = len(paras)
    # hyphenation
    raw_ref = unicodedata.normalize("NFKC", "\n".join(p["body"] for p in pages)).replace("\x02", "-\n").lower()
    midline = set(re.findall(r"\b(\w+-\w+)\b(?!\n)", re.sub(r"-\s*\n", "", raw_ref)))
    midline = {c for c in midline if not re.search(r"\w-\n", c)}
    raw_out = unicodedata.normalize("NFKC", out_text).lower()
    out_vocab = collections.Counter(re.findall(r"\w+", raw_out))
    left = len(re.findall(r"[^\W\d_]{2,}- [a-zà-ÿ]{2,}", raw_out))
    joined_tokens = re.findall(r"\b([^\W\d_]+)-([^\W\d_]+)\b", raw_out)
    left += sum(1 for a, b in joined_tokens if f"{a}-{b}" not in midline and out_vocab.get(a + b, 0) > 0)
    glued = 0
    for c in midline:
        a, _, b = c.partition("-")
        if a.isalpha() and b.isalpha() and out_vocab.get(a + b, 0) and (a + b) not in rw:
            glued += out_vocab[a + b]
    nw = max(1, len(out_words))
    m["hyph_left"] = 10000 * left / nw
    m["hyph_joined"] = 10000 * glued / nw
    # header / footer / page number leakage
    occ = collections.defaultdict(set)
    raw_lines = collections.defaultdict(list)
    for p in pages:
        for pos, t in p["margin"]:
            if not is_pnum(t) and sum(c.isalpha() for c in t) >= 4:
                occ[margin_key(t)].add(p["pno"])
                raw_lines[margin_key(t)].append(t)
    running = {k: v for k, v in occ.items() if len(v) >= 3}
    out_exact = re.sub(r"\s+", " ", norm(out_text))
    out_norm = re.sub(r"\s+", " ", re.sub(r"\d+", "#", norm(out_text)))
    body_norm = re.sub(r"\s+", " ", re.sub(r"\d+", "#", norm("\n".join(p["body"] for p in pages))))
    leak = expected = 0
    leak_examples = []
    for k, pg in running.items():
        expected += len(pg)
        if "#" in k:  # heads carrying the page number: each printed form is unique, so any hit is a leak
            excess = sum(1 for t in raw_lines[k] if re.sub(r"\s+", " ", norm(t)).strip() in out_exact)
        else:
            n_out, n_body = out_norm.count(k), body_norm.count(k)
            excess = max(0, n_out - n_body - 1)  # one legitimate use (title page / chapter title) is allowed
        leak += min(excess, len(pg))
        if excess and len(leak_examples) < 5:
            leak_examples.append(f"{k[:50]} ×{excess}")
    m["hdr_leak"] = leak / expected if expected else None
    m["hdr_leak_examples"] = leak_examples
    m["running_lines"] = expected
    folios = collections.Counter(t.strip().strip("-–—[]()·•. ").lower() for p in pages for _, t in p["margin"] if is_pnum(t))
    alone = collections.Counter(b[1].strip().strip("-–—[]()·•. ").lower() for b in ep["blocks"]
                                if b[0] in ("p", "h1", "h2", "h3", "h4") and is_pnum(b[1]))
    standalone = sum(1 for k, c in alone.items() if folios.get(k) and c == 1)  # repeated numbers are formulae, not folios
    seq = " ".join(out_words_with_digits(out_text))
    pn_total = pn_leak = 0
    for p in pages:
        nums = [(pos, t.strip().strip("-–—[]()·•. ").lower()) for pos, t in p["margin"] if is_pnum(t)]
        if not nums:
            continue
        pn_total += 1
        bw = out_words_with_digits(p["body"])
        if len(bw) < 4:
            continue
        for pos, n in nums:
            probe = " ".join(bw[-3:] + [n]) if pos == "bottom" else " ".join([n] + bw[:3])
            if probe in seq:
                pn_leak += 1
                break
    m["pnum_leak"] = (pn_leak + standalone) / pn_total if pn_total else None
    m["pnum_pages"] = pn_total
    # structure
    outline = ref["outline"]
    m["outline"] = len(outline)
    m["nav"] = len(ep["nav"])
    m["chapters"] = ep["chapters"]
    m["headings"] = sum(ep["headings"].values())
    m["headings_per_page"] = m["headings"] / max(1, len(pages))
    m["chapters_per_100p"] = 100 * ep["chapters"] / max(1, len(pages))
    if outline:
        navn = [re.sub(r"\W+", " ", norm(t)).strip() for t in ep["nav"]]
        hit = 0
        for o in outline:
            t = re.sub(r"\W+", " ", norm(o["title"] or "")).strip()
            if t and any(t[:40] in n or (n and n[:40] in t) for n in navn):
                hit += 1
        m["outline_match"] = hit / len(outline)
    else:
        m["outline_match"] = None
    # navigation entries that are OCR noise (under 60 % letters, a word glued across a case change: "MeeISLAND"), and,
    # when an outline or a hand-checked structure exists, entries supported by neither
    m["nav_garbled"] = sum(1 for t in ep["nav"] if garbled(t))
    known = [o["title"] or "" for o in outline]
    if gt and "level1" in gt:
        known += [g["title"] for g in gt["level1"] + gt.get("level2", [])]
    if known:
        generic = {"notes", "bibliographie", "bibliography", "references", "conclusion", "index", "contents"}
        kn = [re.sub(r"\W+", " ", norm(k)).strip() for k in known]

        def supported(t: str) -> bool:
            n = re.sub(r"\W+", " ", norm(t)).strip()
            return any(k and (k[:40] in n or n[:40] in k) for k in kn) or any(same_title(k, t) for k in known)
        m["nav_unsupported"] = sum(1 for t in ep["nav"][1:] if title_key(t) not in generic and not supported(t))
    else:
        m["nav_unsupported"] = None
    m["img_pdf"] = sum(p["images"] for p in pages)
    m["img_epub"] = ep["images"]
    m["formula_imgs"] = ep["formula_imgs"]
    m["sub_sup"] = ep["sub_sup"]
    ex = ep.get("extra", {})
    nw = max(1, len(out_words))
    # letter-spaced runs ("f e m m es", "2 0 1 0") and words glued together ("ofCalifornia"), per 10k words
    flat = " ".join(b[1] for b in ep["blocks"])
    m["lspaced"] = 10000 * len(re.findall(r"(?<!\w)(?:\w ){3,}\w+", flat)) / nw
    rv = collections.Counter(words(ref_text))
    glued = 0
    for w, c in collections.Counter(out_words).items():
        if len(w) >= 7 and rv[w] == 0 and any(rv[w[:i]] >= 2 and rv[w[i:]] >= 2 for i in range(2, len(w) - 1)):
            glued += c
    glued += len(re.findall(r"(?<![^\W\d_])[a-zà-ÿ]{2,}[A-ZÀ-Þ][a-zà-ÿ]{2,}", flat))  # "ofCalifornia", "theRightto"
    m["glued"] = 10000 * glued / nw
    # words cut in two ("con naissance": together a reference word, never two words there) and two reference words run together
    # ("lacritique", seen side by side in the reference), per 10k words
    ref_words = words(ref_text)
    bigrams = set(zip(ref_words, ref_words[1:]))
    glued_ref = {w.lower() for w in re.findall(r"[a-zà-ÿ]{2,}[A-ZÀ-Þ][a-zà-ÿ]+", ref_text)}  # the reference's own glue
    split = sum(1 for a, b in zip(out_words, out_words[1:])
                if rv[a + b] > 0 and (a, b) not in bigrams and a + b not in glued_ref)
    joined = 0
    for w in out_words:
        if len(w) >= 4 and rv[w] == 0 and any((w[:i], w[i:]) in bigrams for i in range(1, len(w))):
            joined += 1
    m["split_words"] = 10000 * split / nw
    m["joined_words"] = 10000 * joined / nw
    m["noterefs"] = ex.get("noterefs", 0)
    m["sup_unlinked"] = ex.get("sup_unlinked", 0)
    m["note_items"] = ex.get("note_items", 0)
    m["junk_imgs"] = ex.get("junk_imgs", 0)
    m["lower_starts"] = 1000 * ex.get("lower_starts", 0) / max(1, ex.get("paras_all", 0))
    m["pagelist"] = ex.get("pagelist", 0) / max(1, len(pages))
    if gt and "level1" in gt:
        m.update(chapter_metrics(gt, ep))
    elif gt and "units" in gt:
        m.update(private_gt_metrics(gt, ep))
    return m


def out_words_with_digits(text: str) -> list[str]:
    return re.findall(r"\w+", norm(text))


# ---------------------------------------------------------------- epubcheck

def epubcheck(epub: Path, mode: str) -> int:
    if mode == "off":
        return -1
    sys.path.insert(0, str(ROOT / "tests"))
    import epubcheck as ec  # tests/epubcheck.py (pinned jar, cached in tests/.cache)

    java_home = Path("/opt/homebrew/opt/openjdk@21/bin")
    if java_home.exists() and str(java_home) not in os.environ["PATH"]:
        os.environ["PATH"] = f"{java_home}:{os.environ['PATH']}"
    if mode in ("auto", "java") and ec.java_available():
        with tempfile.TemporaryDirectory() as tmp:
            return len(ec.check(epub, Path(tmp)))
    if mode in ("auto", "docker") and shutil.which("docker"):
        cmd = ["docker", "run", "--rm", "-v", f"{epub.parent}:/w:ro", "--entrypoint", "python", "pdftoepub-test", "-c",
               "import sys,pathlib,tempfile; sys.path.insert(0,'/src/tests'); import epubcheck as e; "
               f"print('N=%d' % len(e.check(pathlib.Path('/w/{epub.name}'), pathlib.Path(tempfile.mkdtemp()))))"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        hit = re.search(r"N=(\d+)", res.stdout)
        return int(hit.group(1)) if hit else -1
    return -1


# ---------------------------------------------------------------- conversion worker

def worker(pdf: str, epub: str, ocr: str, langs: str) -> None:
    if os.environ.get("PDFTOEPUB_EVAL_SRC"):  # --src: measure another checkout's code (e.g. main) without reinstalling
        sys.path.insert(0, os.environ["PDFTOEPUB_EVAL_SRC"])
    import pdftoepub

    crops = probe_crops()
    t0 = time.perf_counter()
    try:
        res = pdftoepub.convert(pdf, epub, pdftoepub.api.ConvertOptions(ocr=ocr, ocr_langs=langs))
        out = {"ok": True, "pages": res.page_count, "chapters": res.chapter_count, "ocr_pages": res.ocr_pages, "warnings": res.warnings}
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out["seconds"] = time.perf_counter() - t0
    if crops is not None:
        Path(epub + ".crops.json").write_text(json.dumps(crops))
    print("RESULT " + json.dumps(out))


def probe_crops() -> list | None:
    """Record where each formula picture was cropped (page, crop rectangle, box of the formula's own glyphs, in the
    backend's page coordinates) so that the main process can check the crops against pdfium's glyph boxes."""
    try:
        from pdftoepub.core import formulas
    except ImportError:  # a checkout without formula pictures
        return None
    crops: list = []
    orig = formulas._formula

    def probe(pieces, page, *a, **k):
        r = orig(pieces, page, *a, **k)
        if isinstance(r, formulas.ImageItem):
            own = [p for p in pieces if p.text.strip() not in {r.label, r.lead} - {""}]
            crops.append({"iid": r.image_id, "page": page.number, "size": [page.width, page.height], "rect": list(r.bbox),
                          "ink": [min(p.x0 for p in own), min(p.y0 for p in own), max(p.x1 for p in own), max(p.y1 for p in own)]})
        return r

    formulas._formula = probe
    return crops


def crop_check(pdf: Path, epub: Path) -> dict:
    """Formula pictures against pdfium's glyph boxes and their own pixels:
    crop_bleed  pictures crossed by a glyph of another line (a glyph whose centre is outside the formula's own box)
    crop_clip   pictures cutting one of the formula's own glyphs, or with ink on a 1-px border row/column."""
    side = Path(str(epub) + ".crops.json")
    if not side.exists():
        return {}
    import io

    import pypdfium2 as pdfium
    from PIL import Image

    crops = json.loads(side.read_text())
    z = zipfile.ZipFile(epub)
    names = {Path(n).stem: n for n in z.namelist() if n.startswith("OEBPS/images/")}
    doc = pdfium.PdfDocument(str(pdf))
    tol = 0.3  # points (0.8 px at 200 dpi)
    bleed = clip = border = 0
    seen: set = set()
    examples = []
    glyphs: dict[int, list] = {}
    for c in crops:
        if c["iid"] in seen or c["iid"] not in names:
            continue
        seen.add(c["iid"])
        pno = c["page"]
        page = doc[pno - 1]
        if pno not in glyphs:
            tp = page.get_textpage()
            glyphs[pno] = [tp.get_charbox(i) for i in range(tp.count_chars()) if not tp.get_text_range(i, 1).isspace()]
            tp.close()
        # page coordinates (top-left origin) of whichever box the backend measured from: media box (pdfminer) or crop box
        # (get_bbox: the effective crop box; get_mediabox/get_cropbox fall back to Letter when the box is inherited)
        w, h = c["size"]
        boxes = [page.get_bbox(), page.get_mediabox()]
        bx = min(boxes, key=lambda b: abs((b[2] - b[0]) - w) + abs((b[3] - b[1]) - h))

        def conv(r):
            return (r[0] + bx[0], bx[3] - r[3], r[2] + bx[0], bx[3] - r[1])  # -> PDF user space (l, b, r, t)

        cl, cb, cr, ct = conv(c["rect"])
        il, ib, ir_, it = conv(c["ink"])
        bad_bleed = bad_clip = False
        for gl, gb, gr, gt in glyphs[pno]:
            if min(gr, cr) - max(gl, cl) <= tol or min(gt, ct) - max(gb, cb) <= tol:
                continue  # does not reach into the crop
            mx, my = (gl + gr) / 2, (gb + gt) / 2
            # the formula's own glyph: inside its glyph boxes, or inside the crop on its rows (CMEX parentheses have
            # glyphs in pdfium's text layer but no text in the backends, so no box of their own)
            if ib - 0.5 <= my <= it + 0.5 and (il - 0.5 <= mx <= ir_ + 0.5 or cl <= mx <= cr):
                if gl < cl - tol or gr > cr + tol or gb < cb - tol or gt > ct + tol:
                    bad_clip = True
            else:
                bad_bleed = True
        page.close()
        im = Image.open(io.BytesIO(z.read(names[c["iid"]]))).convert("L")
        px = im.load()
        W, H = im.size
        edge = [px[x, 0] for x in range(W)] + [px[x, H - 1] for x in range(W)] + [px[0, y] for y in range(H)] + [px[W - 1, y] for y in range(H)]
        inked = min(edge) < 160
        border += inked
        bleed += bad_bleed
        clip += bad_clip or inked
        if (bad_bleed or bad_clip or inked) and len(examples) < 8:
            examples.append(f"{c['iid']} p{pno}" + " bleed" * bad_bleed + " clip" * bad_clip + " edge-ink" * inked)
    doc.close()
    return {"crops": len(seen), "crop_bleed": bleed, "crop_clip": clip, "crop_edge_ink": border, "crop_examples": examples}


def run_worker(doc: dict, pdf: Path, epub: Path, backend: str, timeout: int, src: str | None = None) -> dict:
    env = dict(os.environ, PDFTOEPUB_BACKEND=backend)
    if src:
        env["PDFTOEPUB_EVAL_SRC"] = str(Path(src).resolve())
    cmd = [sys.executable, "-I", str(Path(__file__)), "--worker", str(pdf), str(epub), doc.get("ocr", "auto"), doc.get("ocr_langs", "fra+eng")]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    deadline = time.time() + timeout
    rusage = None
    while True:
        pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            rusage = ru
            break
        if time.time() > deadline:
            proc.kill()
            os.wait4(proc.pid, 0)
            return {"ok": False, "error": f"timeout after {timeout}s"}
        time.sleep(0.2)
    stdout = proc.stdout.read()
    stderr = proc.stderr.read()
    line = next((l for l in stdout.splitlines() if l.startswith("RESULT ")), None)
    res = json.loads(line[7:]) if line else {"ok": False, "error": (stderr or "worker crashed")[-500:]}
    rss = rusage.ru_maxrss / (1 << 20 if sys.platform == "darwin" else 1 << 10)
    res["rss_mb"] = round(rss, 1)
    return res


# ---------------------------------------------------------------- report

HEAD = ["doc", "backend", "pages", "word_recall", "word_precision", "char_recall", "pre_share", "pua", "order", "order_2col", "mid_breaks",
        "hyph_left", "hyph_joined", "hdr_leak", "pnum_leak", "outline", "nav", "chapters", "headings", "outline_match",
        "headings_per_page", "chapters_per_100p", "gt_chapters", "ch_found", "sec_found", "ch_spurious", "img_pdf", "img_epub",
        "formula_imgs", "crops", "crop_bleed", "crop_clip", "sub_sup", "lspaced", "glued", "split_words", "joined_words", "noterefs", "sup_unlinked",
        "note_items", "junk_imgs", "lower_starts", "pagelist", "gt_units", "spine_units", "spine_docs", "nav_recall",
        "nav_precision", "title_ok", "nav_garbled", "nav_unsupported", "epubcheck", "s_per_page", "rss_mb"]


def fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"
    return str(v)


def table(rows: list[dict], cols: list[str]) -> str:
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    return "\n".join(lines)


def summarise(rows: list[dict]) -> dict:
    """Means over successful rows, per backend."""
    agg = {}
    for be in sorted({r["backend"] for r in rows}):
        rs = [r for r in rows if r["backend"] == be and r.get("ok")]
        s = {"doc": "MEAN", "backend": be, "pages": sum(r["pages"] for r in rs)}
        for c in HEAD[3:]:
            vals = [r[c] for r in rs if isinstance(r.get(c), (int, float)) and r.get(c) is not None and r.get(c) != -1]
            s[c] = sum(vals) / len(vals) if vals else None
        s["s_per_page"] = sum(r["seconds"] for r in rs) / max(1, s["pages"])
        s["rss_mb"] = max((r["rss_mb"] for r in rs), default=None)
        s["failed"] = sum(1 for r in rows if r["backend"] == be and not r.get("ok"))
        agg[be] = s
    return agg


def write_report(label: str, rows: list[dict]) -> Path:
    d = OUT / label
    agg = summarise(rows)
    md = [f"# Corpus evaluation `{label}`", "", table(rows + list(agg.values()), HEAD), ""]
    md.append("## Details")
    for r in rows:
        md.append(f"### {r['doc']} / {r['backend']}")
        if not r.get("ok"):
            md.append(f"FAILED: {r.get('error')}")
            continue
        md.append(f"- warnings ({len(r.get('warnings', []))}): {'; '.join(r.get('warnings', [])[:5])}")
        md.append(f"- missing (most frequent): {', '.join(r.get('missing_top', []))}")
        md.append(f"- extra (most frequent): {', '.join(r.get('extra_top', []))}")
        if r.get("mid_break_examples"):
            md.append("- mid-sentence breaks: " + " | ".join(r["mid_break_examples"]))
        if r.get("hdr_leak_examples"):
            md.append("- header leaks: " + " | ".join(r["hdr_leak_examples"]))
    (d / "report.md").write_text("\n".join(md) + "\n")
    return d / "report.md"


def compare(a: str, b: str) -> str:
    ra = json.loads((OUT / a / "results.json").read_text())
    rb = json.loads((OUT / b / "results.json").read_text())
    cols = ["word_recall", "word_precision", "char_recall", "pre_share", "pua", "order", "order_2col", "mid_breaks", "hyph_left", "hyph_joined",
            "hdr_leak", "pnum_leak", "outline_match", "img_epub", "epubcheck", "s_per_page", "rss_mb"]
    out = []
    sa, sb = summarise(ra), summarise(rb)
    out.append("| backend | metric | " + a + " | " + b + " |")
    out.append("|---|---|---|---|")
    for be in sorted(set(sa) | set(sb)):
        for c in cols:
            out.append(f"| {be} | {c} | {fmt(sa.get(be, {}).get(c))} | {fmt(sb.get(be, {}).get(c))} |")
    out.append("")
    out.append("| doc | backend | " + " | ".join(f"{c} {a}→{b}" for c in ("word_recall", "order", "mid_breaks", "hyph_left", "hdr_leak", "pnum_leak")) + " |")
    out.append("|---|---|" + "---|" * 6)
    idx = {(r["doc"], r["backend"]): r for r in ra}
    for r in rb:
        o = idx.get((r["doc"], r["backend"]), {})
        cells = [f"{fmt(o.get(c))}→{fmt(r.get(c))}" for c in ("word_recall", "order", "mid_breaks", "hyph_left", "hdr_leak", "pnum_leak")]
        out.append(f"| {r['doc']} | {r['backend']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="latest")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--backends", default=None, help="comma list (default: pdfminer + pymupdf when installed)")
    ap.add_argument("--epubcheck", default="auto", choices=["auto", "java", "docker", "off"])
    ap.add_argument("--timeout", type=int, default=1800, help="per conversion, seconds")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--rescore", action="store_true", help="recompute metrics from the label's existing EPUBs (no conversion)")
    ap.add_argument("--src", help="directory holding the `pdftoepub` package to measure (default: the installed one), "
                                  "e.g. a `git archive main src | tar -x` export")
    ap.add_argument("--worker", nargs=4, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        worker(*args.worker)
        return 0
    if args.compare:
        print(compare(*args.compare))
        return 0
    import importlib.util

    backends = args.backends.split(",") if args.backends else ["pdfminer"] + (["pymupdf"] if importlib.util.find_spec("pymupdf") else [])
    manifest = json.loads((HERE / "manifest.json").read_text())
    private = CORPUS / "private" / "manifest.json"  # git-ignored: copyrighted books the user owns (see fetch.py)
    if private.exists():
        manifest["documents"] += [{**d, "private": True} for d in json.loads(private.read_text())["documents"]]
    docs = [d for d in manifest["documents"] if not args.ids or d["id"] in args.ids]
    by_id = {d["id"]: d for d in manifest["documents"]}
    d_out = OUT / args.label
    d_out.mkdir(parents=True, exist_ok=True)
    ref_cache = OUT / "reference"
    ref_cache.mkdir(parents=True, exist_ok=True)
    results_path = d_out / "results.json"
    rows = json.loads(results_path.read_text()) if results_path.exists() else []
    for doc in docs:
        pdf = CORPUS / doc.get("file", f"{doc['id']}.pdf")
        if not pdf.exists():
            print(f"skip {doc['id']}: " + ("private file absent" if doc.get("private") else "not fetched (run fetch.py)"))
            continue
        rc = ref_cache / f"{doc['id']}.json"
        if rc.exists() and rc.stat().st_mtime > max(pdf.stat().st_mtime, Path(__file__).stat().st_mtime):
            ref = json.loads(rc.read_text())
        else:
            if "derive" in doc:
                ref = reference(CORPUS / f"{by_id[doc['derive']['from']]['id']}.pdf", doc["derive"]["pages"])
            else:
                ref = reference(pdf)
            rc.write_text(json.dumps(ref))
        for be in backends:
            epub = d_out / f"{doc['id']}.{be}.epub"
            print(f"{doc['id']:<28} {be:<9}", end=" ", flush=True)
            if args.rescore:
                old = next((r for r in rows if (r["doc"], r["backend"]) == (doc["id"], be)), None)
                if old is None or not old.get("ok") or not epub.exists():
                    print("no previous result")
                    continue
                res = {k: old[k] for k in ("ok", "pages", "chapters", "ocr_pages", "warnings", "seconds", "rss_mb")}
            else:
                res = run_worker(doc, pdf, epub, be, args.timeout, args.src)
            row = {"doc": doc["id"], "backend": be, **res}
            if res.get("ok"):
                gt = doc.get("chapters_gt")
                if doc.get("gt_file") and (CORPUS / doc["gt_file"]).exists():
                    gt = json.loads((CORPUS / doc["gt_file"]).read_text())
                row.update(metrics(ref, read_epub(epub), gt))
                row.update(crop_check(pdf, epub))
                row["epubcheck"] = old.get("epubcheck", -1) if args.rescore else epubcheck(epub, args.epubcheck)
                row["s_per_page"] = res["seconds"] / max(1, res["pages"])
                print(f"ok {res['seconds']:.1f}s rss={res['rss_mb']}MB recall={row['word_recall']:.3f} order={fmt(row['order'])} "
                      f"breaks={row['mid_breaks']:.1f} hdr={fmt(row['hdr_leak'])} pnum={fmt(row['pnum_leak'])} epubcheck={row['epubcheck']}")
            else:
                print(f"FAILED {res.get('error')}")
            rows = [r for r in rows if (r["doc"], r["backend"]) != (doc["id"], be)] + [row]
            order = {d["id"]: i for i, d in enumerate(manifest["documents"])}
            rows.sort(key=lambda r: (order.get(r["doc"], 999), r["backend"]))
            results_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"report: {write_report(args.label, rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
