"""Structure recognition: RawBlocks -> IR blocks (headings, lists, quotes, tables, figures), chapters, nav."""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from . import openings
from .ir import (Block, Chapter, Endnotes, Figure, Footnote, Heading, Line, ListBlock, Paragraph, Run, Table)
from .layout import BULLET_RE, GLYPH_BULLET_RE, TERMINAL_RE, Ctx, RawBlock, RawNote, is_centered

_HYPHENS = "-­‐‑"
_FR_INVERSION = {"il", "elle", "on", "ils", "elles", "ce", "je", "tu", "nous", "vous", "moi", "toi", "lui", "leur",
                 "ci", "là", "même", "mêmes", "t", "en", "y", "je"}
_SUP_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUP_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_LEADER_RE = re.compile(r"(?:\s*[.·•]){4,}\s*|(?:\s*\.\s*){4,}")
_CAPTION_RE = re.compile(r"^\s*(fig(?:ure|\.)?|figure|tableau|table|abb(?:ildung|\.)?|illustration|image|photo|chart|graph|plate|planche|schéma)\b", re.I)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def _style(r: Run) -> tuple:
    return (r.bold, r.italic, r.sup, r.sub, r.mono, r.link, r.noteref, r.display, r.image, r.eqno, r.pagebreak)


_PLAIN = _style(Run(""))


def normalize_runs(pieces: list[Run]) -> list[Run]:
    # explode unicode superscript digits
    exploded: list[Run] = []
    for r in pieces:
        if not r.sup and _SUP_RE.search(r.text):
            pos = 0
            for m in _SUP_RE.finditer(r.text):
                if m.start() > pos:
                    exploded.append(_clone(r, r.text[pos:m.start()]))
                x = _clone(r, m.group().translate(_SUP_DIGITS))
                x.sup = True
                exploded.append(x)
                pos = m.end()
            if pos < len(r.text):
                exploded.append(_clone(r, r.text[pos:]))
        else:
            exploded.append(r)
    # collapse whitespace
    for r in exploded:
        r.text = _LEADER_RE.sub(" … ", r.text) if "..." in r.text or ". ." in r.text else r.text
        r.text = re.sub(r"[ \t\r\n   ]+", " ", r.text)
    exploded = [r for r in exploded if r.text != "" or r.pagebreak]
    # whitespace-only pieces take the style of identical neighbours
    for i, r in enumerate(exploded):
        if r.text.strip() == "" and 0 < i < len(exploded) - 1 and r.image is None:
            a, b = exploded[i - 1], exploded[i + 1]
            if (_style(a) == _style(b) and not a.sup and not a.sub and a.noteref is None and a.link == b.link
                    and a.image is None and not a.eqno):
                r.bold, r.italic, r.mono, r.link, r.display = a.bold, a.italic, a.mono, a.link, a.display
    # merge equal styles
    merged: list[Run] = []
    for r in exploded:
        if merged and _style(merged[-1]) == _style(r) and r.image is None:
            merged[-1].text += r.text
        else:
            merged.append(_clone(r, r.text))
    # move edge whitespace out of styled runs
    out: list[Run] = []
    for r in merged:
        if _style(r) == _PLAIN or r.image is not None or r.pagebreak:
            out.append(r)
            continue
        lead = len(r.text) - len(r.text.lstrip())
        trail = len(r.text) - len(r.text.rstrip())
        edge = Run("", display=r.display)  # spaces stay inside their display formula
        if lead == len(r.text):
            out.append(_clone(edge, r.text))
            continue
        if lead:
            out.append(_clone(edge, r.text[:lead]))
        out.append(_clone(r, r.text.strip()))
        if trail:
            out.append(_clone(edge, r.text[len(r.text) - trail:]))
    # final merge of plain pieces, trim ends, collapse double spaces
    final: list[Run] = []
    for r in out:
        if final and _style(final[-1]) == _style(r) and r.image is None:
            final[-1].text += r.text
        else:
            final.append(r)
    for r in final:
        r.text = re.sub(r" {2,}", " ", r.text)
    if final:
        final[0].text = final[0].text.lstrip()
        final[-1].text = final[-1].text.rstrip()
    final = [r for r in final if r.text or r.pagebreak]
    # drop spaces around "start of block" duplicates (e.g. " " after a plain run ending in space)
    for a, b in zip(final, final[1:]):
        if a.text.endswith(" ") and b.text.startswith(" "):
            b.text = b.text.lstrip()
    return [r for r in final if r.text or r.pagebreak]


def _clone(r: Run, text: str) -> Run:
    return Run(text, r.bold, r.italic, r.sup, r.sub, r.mono, r.link, r.noteref, r.display, r.image, r.eqno, r.pagebreak)


def _last_word(runs: list[Run]) -> str:
    txt = "".join(r.text for r in runs)
    m = re.search(r"([^\W\d_]+)[" + re.escape(_HYPHENS) + r"]\s*$", txt)
    return m.group(1) if m else ""


def join_runs(a: list[Run], b: list[Run], ctx: Ctx) -> list[Run]:
    """Concatenate two run lists across a line/page break, removing line-end hyphenation when appropriate."""
    if not a:
        return list(b)
    if not b:
        return list(a)
    a = [_clone(r, r.text) for r in a]
    b = [_clone(r, r.text) for r in b]
    atext = "".join(r.text for r in a).rstrip()
    if len(atext) >= 2 and atext[-1] in _HYPHENS and atext[-2].isalpha():
        w1 = _last_word(a)
        btext = "".join(r.text for r in b).lstrip()
        m = re.match(r"[^\W\d_]+", btext)
        w2 = m.group(0) if m else ""
        keep = False
        if atext[-1] != "­" and w2:
            lw1, lw2 = w1.lower(), w2.lower()
            if ctx.hyph_vocab.get(f"{lw1}-{lw2}"):
                keep = True
            elif ctx.vocab.get(lw1 + lw2):
                keep = False
            elif lw2 in _FR_INVERSION and len(lw1) >= 2:
                keep = True
            elif not w2[0].islower():
                keep = True
        elif not w2:
            keep = True
        # strip trailing whitespace of a, then optionally the hyphen
        while a and not a[-1].text.rstrip():
            a.pop()
        a[-1].text = a[-1].text.rstrip()
        if not keep or a[-1].text[-1] == "­":
            a[-1].text = a[-1].text[:-1]
        elif a[-1].text[-1] in "‐‑":
            a[-1].text = a[-1].text[:-1] + "-"
        b[0].text = b[0].text.lstrip()
        return a + b
    return a + [Run(" ")] + b


def runs_from_lines(lines: list[Line], ctx: Ctx) -> list[Run]:
    runs: list[Run] = []
    for line in lines:
        pieces = []
        for s in line.spans:
            link = None
            if s.link:
                link = s.link
            pieces.append(Run(s.text, s.bold, s.italic, s.sup, s.sub, s.mono, link))
        runs = join_runs(runs, pieces, ctx) if runs else pieces
    return normalize_runs(runs)


def plain(runs: list[Run]) -> str:
    return "".join(r.text for r in runs).strip()


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------
@dataclass
class HeadingModel:
    size_levels: list[float]  # descending distinct sizes (cluster centres)
    bold_level: int | None
    body: float

    def classify(self, blk: RawBlock) -> int | None:
        """Return heading rank (1 = biggest) or None."""
        key = _heading_key(blk, self.body)
        if key is None:
            return None
        if key == "bold":
            return self.bold_level
        for i, s in enumerate(self.size_levels):
            if abs(s - key) <= 0.75:
                return i + 1
        return None


def _is_marker_line(text: str) -> bool:
    return bool(GLYPH_BULLET_RE.match(text) or BULLET_RE.match(text))


def _heading_key(blk: RawBlock, body: float):
    if blk.kind != "text" or not blk.lines or blk.math:
        return None
    text = blk.text
    n = len(text)
    if n < 1 or len(blk.lines) > 4 or n > 200:
        return None
    if re.fullmatch(r"[\d\W_]+", text):
        return None
    if _is_marker_line(text):
        return None
    size = blk.size
    if blk.ocr:
        return _ocr_heading_key(blk, body, text)
    if size >= body * 1.12 and size - body >= 1.0:
        return round(size * 2) / 2
    if blk.mono:
        return None
    if (size >= body * 0.95 and n <= 120 and all(l.bold_ratio > 0.85 for l in blk.lines)
            and not re.search(r"[.;,]$", text.strip())):
        return "bold"
    return None


def _ocr_heading_key(blk: RawBlock, body: float, text: str):
    """OCR sizes are estimates (±10 %) and there is no bold: a heading needs to be clearly larger, short, shaped like a
    title (not a sentence fragment) and set apart (whitespace above, or centred)."""
    size = blk.size
    t = text.strip()
    if len(blk.lines) > 2 or len(t) > 100 or size < 1.3 * body or size - body < 2.0:
        return None
    if t[:1].islower() or t.endswith(("-", ",", ";", ":")):
        return None
    if len(t) > 40 and t[-1].islower():  # a long line ending mid-word / mid-sentence
        return None
    if not (blk.centred or blk.space_above is None or blk.space_above >= 0.6 * body):
        return None
    return round(size * 2) / 2


def strong_ocr_heading(blk: RawBlock, body: float) -> bool:
    """Evidence strong enough to start a chapter from OCR alone: much larger than body, centred, short."""
    return blk.size >= 1.5 * body and blk.centred and len(blk.text.strip()) <= 60


def build_heading_model(blocks: list[RawBlock], ctx: Ctx) -> HeadingModel:
    body = ctx.body_size
    chars_by_size: Counter = Counter()
    total_chars = 0
    text_blocks = 0
    for b in blocks:
        if b.kind != "text":
            continue
        text_blocks += 1
        c = len(b.text)
        total_chars += c
        chars_by_size[round(b.size * 2) / 2] += c
    cands: Counter = Counter()
    bold_n = 0
    for b in blocks:
        k = _heading_key(b, body)
        if k == "bold":
            bold_n += 1
        elif k is not None:
            cands[k] += 1
    sizes = []
    for s in sorted(cands, reverse=True):
        if chars_by_size[s] > 0.15 * max(total_chars, 1) and cands[s] > 3:
            continue  # a size used for lots of running text is not a heading size
        if sizes and sizes[-1] - s <= 0.75:
            continue
        sizes.append(s)
    bold_level = None
    if bold_n and bold_n <= 0.25 * max(text_blocks, 1):
        bold_level = len(sizes) + 1
    return HeadingModel(sizes, bold_level, body)


# ---------------------------------------------------------------------------
# Raw blocks -> IR blocks
# ---------------------------------------------------------------------------
@dataclass
class _Item:
    """Working representation while merging/grouping."""

    block: Block
    size: float = 0.0
    left_margin: float = 0.0
    marker: str | None = None  # list marker text (raw), for paragraphs
    lines: int = 1


def _marker(text: str):
    t = text.lstrip()
    if GLYPH_BULLET_RE.match(t):
        return ("ul", None, GLYPH_BULLET_RE.match(t).end())
    m = BULLET_RE.match(t)
    if m and m.group(1) in "-*":
        return ("ul", None, m.end())
    m = re.match(r"^\(?(\d{1,3})[.)]\s+(?=\S)", t)
    if m:
        return ("ol", int(m.group(1)), m.end())
    m = re.match(r"^\(?([a-z])[.)]\s+(?=\S)", t)
    if m:
        return ("ola", ord(m.group(1)) - 96, m.end())
    return None


def _strip_prefix_runs(runs: list[Run], n: int) -> list[Run]:
    out = [_clone(r, r.text) for r in runs]
    lead = len(out[0].text) - len(out[0].text.lstrip()) if out else 0
    todo = n - lead if False else n
    res: list[Run] = []
    for r in out:
        if todo <= 0:
            res.append(r)
            continue
        t = r.text
        if len(t) <= todo:
            todo -= len(t)
            continue
        r.text = t[todo:].lstrip()
        todo = 0
        res.append(r)
    return normalize_runs(res)


def _pre_text(lines: list[Line]) -> str:
    """Verbatim text of code lines: indentation from geometry, blank lines from vertical gaps, no joining."""
    widths = [(l.x1 - l.x0) / max(len(l.text.rstrip()) + (len(l.text) - len(l.text.lstrip())), 1) for l in lines if len(l.text.strip()) >= 4]
    cw = statistics.median(widths) if widths else max(lines[0].size * 0.6, 1.0)
    cw = cw if 0.3 * lines[0].size <= cw <= 0.9 * lines[0].size else max(lines[0].size * 0.6, 1.0)
    base = min(l.x0 for l in lines)
    # visual column of the first printed character: geometric offset (+ leading space glyphs, which the bbox includes)
    cols = [(l.x0 - base) / cw + (len(l.text) - len(l.text.lstrip())) for l in lines]
    dedent = min(cols)
    diffs = [b.y0 - a.y0 for a, b in zip(lines, lines[1:]) if b.y0 - a.y0 > 0]
    pitch = max(min(diffs), 0.7 * (lines[0].height or 12.0)) if diffs else 0.0
    out: list[str] = []
    prev = None
    for l, col in zip(lines, cols):
        if prev is not None and pitch > 0:
            blanks = min(int(round((l.y0 - prev.y0) / pitch)) - 1, 3)
            out.extend([""] * max(blanks, 0))
        out.append(" " * int(round(col - dedent)) + l.text.strip().replace("\t", "    "))
        prev = l
    return "\n".join(out)


def merge_code_blocks(blocks: list[Block]) -> list[Block]:
    """Consecutive code blocks (split by a page / column break or a large gap) become one <pre>."""
    out: list[Block] = []
    for b in blocks:
        if (out and isinstance(b, Paragraph) and b.kind == "pre" and isinstance(out[-1], Paragraph) and out[-1].kind == "pre"):
            prev = out[-1]
            if b.break_before in ("page", "column") or (b.page == prev.page and 0 <= b.y0 - prev.y1 < 3 * max(b.size, 1)):
                blank = "\n" if (b.page == prev.page and b.y0 - prev.y1 > 0.8 * max(b.size, 1)) else ""
                prev.runs = [Run(prev.runs[0].text + "\n" + blank + b.runs[0].text, mono=True)]
                prev.y1 = b.y1
                prev.page = b.page if b.break_before else prev.page
                continue
        out.append(b)
    return out


def garbled_heading(text: str) -> bool:
    """A heading shape OCR noise has: under 60 % letters, or a word glued across a case change ("MeeISLAND")."""
    t = text.strip()
    letters = sum(c.isalpha() for c in t)
    nonspace = sum(not c.isspace() for c in t)
    if re.fullmatch(r"[\dIVXLCivxlc]+(?:[.\-][\dA-Za-z]{1,3})*\.?", t):  # numbering only ("II", "1.B.")
        return False
    return (not nonspace or letters < 0.6 * nonspace
            or re.search(r"\b[A-ZÀ-Þ]?[a-zà-ÿ]{2,}[A-ZÀ-Þ]{3,}", t) is not None)


def convert_blocks(raw: list[RawBlock], ctx: Ctx, notes: dict[int, list[RawNote]],
                   headings: HeadingModel, plan=None) -> tuple[list[Block], dict[str, Footnote]]:
    """Convert layout blocks to IR blocks (headings/paragraphs/quotes/pre/tables/figures) and footnotes. `plan`
    (`openings.Plan`, scanned books) forces the chapter / section headings found from the page layout; other OCR
    headings then stay out of chapter splitting."""
    out: list[Block] = []
    footnotes: dict[str, Footnote] = {}
    note_ids: dict[int, dict[str, str]] = {}
    chapter_title = ""  # the current chapter's title (plan)
    for pno, ns in notes.items():
        ids = {}
        for k, n in enumerate(ns, 1):
            nid = f"fn-p{pno}-{k}"
            if not n.orphan:
                ids.setdefault(n.marker, nid)
            footnotes[nid] = Footnote(nid, runs_from_lines(n.lines, ctx), n.marker, pno, n.orphan)
        note_ids[pno] = ids
    used_markers: dict[int, set[str]] = {}
    for b in raw:
        if b.kind == "image":
            it = b.item
            if it.kind == "formula":
                runs = ([Run(it.lead)] if it.lead else []) + [Run(it.alt, image=(it.image_id, it.width_em), display=1)]
                runs += [Run(it.label, eqno=True, display=1)] if it.label else []
                out.append(Paragraph(runs, "dmath", b.page, b.y0, b.break_before, False, ctx.body_size, y1=it.bbox[3]))
                continue
            out.append(Figure(it.image_id, "", None, b.page, b.y0, b.break_before))
            continue
        if b.kind == "endnotes":
            from .endnotes import footnotes_of
            out.append(Endnotes(footnotes_of(b.item, runs_from_lines, ctx), b.page, b.y0, b.break_before))
            continue
        if b.kind == "table":
            t = b.item
            rows = [[[Run(c)] if c else [] for c in row] for row in t.rows]
            out.append(Table(rows, t.header, b.page, b.y0, b.break_before))
            continue
        if plan is not None:
            if id(b) in plan.skip:
                continue
            forced = plan.forced.get(id(b))
            if forced is not None:
                level, group, text = forced
                runs = [Run(text)] if text else runs_from_lines([l for g in group for l in g.lines], ctx)
                for r in runs:
                    r.bold = False
                    r.text = re.sub(r"\s{2,}", " ", r.text)
                runs = normalize_runs(runs)
                if runs:
                    out.append(Heading(level, runs, b.page, b.y0, b.size, b.break_before))
                    if level == 1 or not chapter_title:
                        chapter_title = plain(runs)
                continue
        runs = runs_from_lines(b.lines, ctx)
        if not runs:
            continue
        ids = note_ids.get(b.page, {})
        if ids and not b.math:  # an exponent in a displayed formula is not a footnote mark
            used = used_markers.setdefault(b.page, set())
            for r in runs:
                if r.sup and r.text.strip() in ids and r.text.strip() not in used:
                    r.noteref = ids[r.text.strip()]
                    used.add(r.text.strip())
        rank = headings.classify(b)
        if rank is not None and b.ocr and (garbled_heading(plain(runs)) or (plan is not None and not chapter_title)
                                           or b.page in ctx.sparse_pages):
            rank = None  # OCR noise ("MeeISLAND PLANT", "_i"), front matter of a planned book, a title page / plate line
        if rank is not None:
            for r in runs:
                r.bold = False
            runs = normalize_runs(runs)
            weak = b.ocr and (plan is not None or not strong_ocr_heading(b, ctx.body_size))
            if b.ocr and plan is not None:
                if chapter_title and openings.similar(plain(runs), chapter_title, 0.85):
                    continue  # the chapter's title again: its running head ("‘THE RESULT OF DROUGHT …" after plates)
                rank = max(rank, 3)
            out.append(Heading(min(rank, 4), runs, b.page, b.y0, b.size, b.break_before, weak=weak))
            continue
        size = b.size
        if b.math:
            for r in runs:
                r.display = 1
            out.append(Paragraph(runs, "dmath", b.page, b.y0, b.break_before, False, size, y1=max(l.y1 for l in b.lines)))
            continue
        if b.mono:
            out.append(Paragraph([Run(_pre_text(b.lines), mono=True)], "pre", b.page, b.y0, b.break_before, False, size,
                                 y1=max(l.y1 for l in b.lines)))
            continue
        kind = "p"
        inset_l = b.min_x0 - b.left
        inset_r = b.right - b.max_x1
        centered = all(is_centered(l, b.left, b.right, size) for l in b.lines)
        ragged = max(l.x0 for l in b.lines) - min(l.x0 for l in b.lines) > 0.6 * size
        if (inset_l >= 1.4 * size and size <= ctx.body_size + 0.6 and not _marker(b.text)
                and len(b.lines) >= 2 and inset_r >= 0 and not (centered and ragged)):
            kind = "blockquote"
        p = Paragraph(runs, kind, b.page, b.y0, b.break_before, b.first_indent, size, y1=max(l.y1 for l in b.lines))
        out.append(p)
    return out, footnotes


def inline_display_math(blocks: list[Block]) -> list[Block]:
    """A display formula belongs to the sentence around it: it joins the paragraph before it (as a centred block
    inside the <p>), and the text after it continues that paragraph unless it starts a new one (indented, or a new
    sentence after a formula ending with a full stop)."""
    out: list[Block] = []
    open_p: Paragraph | None = None  # paragraph that just received a formula
    continued = False  # open_p already took the text after its formula
    n = 0
    for b in blocks:
        if isinstance(b, Paragraph) and b.kind == "dmath":
            n += 1
            runs = [_clone(r, r.text) for r in b.runs]
            for r in runs:
                if r.display:
                    r.display = n
            prev = out[-1] if out else None
            if open_p is None and isinstance(prev, Paragraph) and prev.kind == "p":
                open_p = prev
            if open_p is not None:
                open_p.runs = open_p.runs + [Run(" ")] + runs
                open_p.y1 = b.y1
            else:
                open_p = Paragraph(runs, "p", b.page, b.y0, b.break_before, False, b.size, y1=b.y1)
                out.append(open_p)
            continued = False
            continue
        if open_p is not None and isinstance(b, Paragraph) and b.kind == "p" and not b.indented:
            text = plain(b.runs)
            last = plain([r for r in open_p.runs if r.display and not r.eqno])[-1:]
            # the text right after the formula continues its sentence; later pieces (split by a page break or a
            # footnote) only while they visibly continue it (lower case), never a table row or a new sentence
            ok = bool(text) and (text[0].islower() if continued
                                 else text[0].islower() or not text[0].isalpha() or last not in ".!?")
            if ok and not _marker(text):
                open_p.runs = open_p.runs + [Run(" ")] + b.runs
                open_p.y1 = b.y1
                continued = True
                continue
        open_p = None
        out.append(b)
    return out


def merge_across_breaks(blocks: list[Block], ctx: Ctx) -> list[Block]:
    """Join paragraphs interrupted only by a column or page break."""
    out: list[Block] = []
    for b in blocks:
        # a figure / table placed at the break (top of the next page, or a plate) floats out of the sentence
        k = len(out) - 1
        while k >= 0 and len(out) - k <= 2 and isinstance(out[k], (Figure, Table)):
            k -= 1
        floats = out[k + 1:]
        broken = b.break_before in ("page", "column") or any(f.break_before in ("page", "column") for f in floats)
        # a lowercase start ("et la suite …", "– disait-il …") continues the sentence, whatever the indentation
        low = isinstance(b, Paragraph) and re.match(r"^(?:[–—-]\s*)?[^\W\d_A-ZÀ-Þ]", plain(b.runs)) is not None
        kinds = (isinstance(b, Paragraph) and k >= 0 and isinstance(out[k], Paragraph)
                 and (b.kind == out[k].kind in ("p", "blockquote") or (low and out[k].kind == "blockquote" and b.kind == "p")))
        if k >= 0 and kinds and broken and (not floats or low):
            prev = out[k]
            ptxt = plain(prev.runs)
            ctxt = plain(b.runs)
            if (ptxt and ctxt and abs(prev.size - b.size) <= 0.8 and (not b.indented or low or b.kind == "blockquote")
                    and (not TERMINAL_RE.search(ptxt) or ptxt[-1] in _HYPHENS or (low and ptxt[-1] == "."))
                    and not _marker(ctxt)):
                joined = join_runs(prev.runs, b.runs, ctx)
                if b.page != (prev.last_page or prev.page):  # where the next page begins, for the page list
                    _insert_between_words(joined, min(len(prev.runs), len(joined)), Run("", pagebreak=b.page))
                prev.runs = normalize_runs(joined)
                prev.last_page = b.page
                continue
        out.append(b)
    return out


def _insert_between_words(runs: list[Run], i: int, marker: Run) -> None:
    """Insert `marker` at run index `i`, moved forward to the next space when `i` falls inside a word (a word
    hyphenated across the page break: "phy-" / "siologie" is one word, the marker goes after it)."""
    before = "".join(r.text for r in runs[:i])
    after = "".join(r.text for r in runs[i:])
    if not (before[-1:].strip() and after[:1].strip()):  # already between words
        runs.insert(i, marker)
        return
    for k in range(i, len(runs)):
        r = runs[k]
        j = r.text.find(" ") if not r.image else -1
        if j >= 0:
            head, tail = _clone(r, r.text[:j + 1]), _clone(r, r.text[j + 1:])
            runs[k:k + 1] = [head, marker] + ([tail] if tail.text else [])
            return
    runs.append(marker)


def group_lists(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        mk = _marker(plain(b.runs)) if isinstance(b, Paragraph) and b.kind == "p" else None
        if mk is None:
            out.append(b)
            i += 1
            continue
        kind, num, plen = mk
        items = [(b, plen)]
        j = i + 1
        cur = num
        while j < n:
            c = blocks[j]
            if not (isinstance(c, Paragraph) and c.kind == "p"):
                break
            m2 = _marker(plain(c.runs))
            if m2 is None or m2[0] != kind:
                break
            if kind != "ul":
                if m2[1] != cur + 1:
                    break
                cur = m2[1]
            items.append((c, m2[2]))
            j += 1
        if kind == "ul" and len(items) >= 1 and (GLYPH_BULLET_RE.match(plain(b.runs)) or len(items) >= 2):
            ok = True
        elif kind != "ul" and len(items) >= 2:
            ok = True
        else:
            ok = False
        if not ok:
            out.append(b)
            i += 1
            continue
        lb = ListBlock(kind != "ul", [_strip_prefix_runs(p.runs, pl) for p, pl in items], b.page, b.y0, b.break_before)
        if kind == "ola":
            lb.start = -1  # lowercase-alpha marker
        elif kind == "ol" and num != 1:
            lb.start = num
        out.append(lb)
        i = j
    return out


def attach_captions(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if (out and isinstance(out[-1], Figure) and out[-1].caption is None and isinstance(b, Paragraph)
                and b.kind == "p" and _CAPTION_RE.match(plain(b.runs)) and len(plain(b.runs)) < 300):
            out[-1].caption = b.runs
            out[-1].alt = plain(b.runs)[:200]
            continue
        out.append(b)
    return out


def merge_adjacent_headings(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if out and isinstance(b, Heading) and isinstance(out[-1], Heading) and out[-1].level == b.level and b.page - out[-1].page <= 1:
            a = out[-1]
            ta, tb = plain(a.runs), plain(b.runs)
            if (len(ta) <= 14 or len(tb) <= 14 or re.match(r"(?i)^(chapter|chapitre|part|partie|section|kapitel|capítulo|\d+\.?)$", ta)) \
                    and (b.y0 - a.y0) < 6 * max(a.size, 1) and a.page == b.page:
                a.runs = normalize_runs(a.runs + [Run(" ")] + b.runs)
                continue
        out.append(b)
    return out


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


@dataclass
class TocEntry:
    level: int
    title: str
    page: int
    y: float


def clean_toc(toc, npages: int) -> list[TocEntry]:
    """toc: [(level, title, page, y)] from the backend."""
    out = []
    for e in toc or []:
        try:
            lvl, title, page = int(e[0]), clean_text_field(e[1], 500), int(e[2])
            y = float(e[3]) if len(e) > 3 else 0.0
        except Exception:  # noqa: BLE001
            continue
        if not title or page < 1 or page > npages:
            continue
        out.append(TocEntry(max(lvl, 1), re.sub(r"\s+", " ", title), page, y))
    return out


def _pick_split_level(entries: list[TocEntry], npages: int) -> int | None:
    best = None
    for L in sorted({e.level for e in entries}):
        n = sum(1 for e in entries if e.level <= L)
        if n < 2:
            continue
        if best is None:
            best = L
        elif L == best + 1 and npages / n >= 4:
            best = L
    return best


def _match_heading(blocks: list[Block], lo: int, hi: int, title: str) -> int | None:
    nt = _norm(title)
    if len(nt) < 2:
        return None
    for i in range(lo, hi):
        b = blocks[i]
        if isinstance(b, Heading):
            nh = _norm(plain(b.runs))
            if nh and (nh == nt or (len(nt) >= 4 and (nt in nh or (len(nh) >= 4 and nh in nt)))):
                return i
    return None


def assign_ids(blocks: list[Block]) -> None:
    n = 0
    for b in blocks:
        n += 1
        if getattr(b, "id", None) is None and not isinstance(b, Footnote):
            b.id = f"b{n}"


def build_chapters(blocks: list[Block], toc: list[TocEntry], npages: int, doc_title: str, warnings: list[str],
                   split_level: int | None = None) -> list[Chapter]:
    assign_ids(blocks)
    starts: list[tuple[int, str, bool, int]] = []  # (block index, title, title_is_heading, toc level)
    nav_extra: list[tuple[int, str, int]] = []  # (level, title, block idx)
    L = (split_level or _pick_split_level(toc, npages)) if toc else None
    if L is not None:
        page_first: dict[int, int] = {}
        page_last: dict[int, int] = {}
        for i, b in enumerate(blocks):
            page_first.setdefault(b.page, i)
            page_last[b.page] = i
        pages_sorted = sorted(page_first)
        prev_idx = 0
        for e in toc:
            lo = None
            for pg in pages_sorted:
                if pg >= e.page:
                    lo = pg
                    break
            if lo is None:
                continue
            first = page_first[lo]
            last = page_last[lo] + 1 if lo == e.page else first
            hi = max(first, last)
            idx = _match_heading(blocks, max(first, prev_idx), hi, e.title) if lo == e.page else None
            is_h = idx is not None
            if idx is None:
                idx = first
                if lo == e.page and e.y > 0:
                    for i in range(first, hi):
                        if blocks[i].y0 >= e.y - 6:
                            idx = i
                            break
                    else:
                        idx = first
                idx = max(idx, prev_idx)
                if idx < len(blocks) and isinstance(blocks[idx], Heading) and lo == e.page:
                    is_h = True
            if e.level <= L:
                if starts and starts[-1][0] == idx:
                    continue
                starts.append((idx, e.title, is_h, e.level))
                prev_idx = idx
            else:
                nav_extra.append((e.level, e.title, idx))
    else:
        # without an outline, chapters split only on headings with reliable evidence (not OCR size guesses)
        levels = Counter(b.level for b in blocks if isinstance(b, Heading) and not b.weak)
        split = next((lv for lv in sorted(levels) if levels[lv] >= 2), None)
        if split is not None:
            for i, b in enumerate(blocks):
                if isinstance(b, Heading) and b.level <= split and not b.weak:
                    starts.append((i, plain(b.runs), True, 1))

    chapters: list[Chapter] = []
    if not starts:
        first = blocks[0] if blocks else None
        if isinstance(first, Heading):  # a single heading doubles as the title: no synthetic h1 above it
            ch = Chapter(plain(first.runs) or doc_title, list(blocks), first_page=first.page)
            ch.title_is_heading = True
        else:
            ch = Chapter(doc_title, list(blocks), first_page=blocks[0].page if blocks else 1)
        chapters.append(ch)
    else:
        if starts[0][0] > 0:
            chapters.append(Chapter(doc_title, blocks[: starts[0][0]], first_page=blocks[0].page))
        bounds = [s[0] for s in starts] + [len(blocks)]
        for k, (idx, title, is_h, lvl) in enumerate(starts):
            ch = Chapter(title, blocks[idx:bounds[k + 1]], first_page=blocks[idx].page if idx < len(blocks) else 1)
            ch.nav_level = max(1, lvl - (min(s[3] for s in starts) - 1))
            ch.title_is_heading = is_h and bool(ch.blocks) and isinstance(ch.blocks[0], Heading)
            if is_h and ch.blocks and not isinstance(ch.blocks[0], Heading):
                ch.title_is_heading = False
            chapters.append(ch)
    for ch in chapters:
        _finalize_chapter(ch)
    # attach outline sub-entries as nav sections
    if nav_extra:
        _attach_extra(chapters, blocks, nav_extra)
    chapters = [c for c in chapters if c.blocks]
    chapters = _split_long(chapters)
    return chapters


def _finalize_chapter(ch: Chapter) -> None:
    """Normalise heading levels inside the chapter and make sure it starts with an h1."""
    heads = [b for b in ch.blocks if isinstance(b, Heading)]
    first = ch.blocks[0] if ch.blocks else None
    if ch.title_is_heading and isinstance(first, Heading):
        first.level = 1
        others = [h for h in heads if h is not first]
    else:
        others = heads
        if ch.title and ch.blocks:
            h = Heading(1, [Run(ch.title)], first.page, first.y0, 0.0, first.break_before)
            h.id = None
            ch.blocks.insert(0, h)
            ch.title_is_heading = True
    ranks = sorted({h.level for h in others})
    mapping = {r: min(2 + i, 4) for i, r in enumerate(ranks)}
    for h in others:
        h.level = mapping[h.level]
    ch.sections = []
    n = 0
    for b in ch.blocks:
        if isinstance(b, Heading) and b.level in (2, 3):
            if b.id is None:
                n += 1
                b.id = f"h{n}"
            ch.sections.append((b.level, plain(b.runs), b.id))
    if ch.blocks and isinstance(ch.blocks[0], Heading):
        ch.blocks[0].id = ch.blocks[0].id or "top"


def _attach_extra(chapters: list[Chapter], blocks: list[Block], extra) -> None:
    owner: dict[int, Chapter] = {}
    for ch in chapters:
        for b in ch.blocks:
            owner[id(b)] = ch
    for lvl, title, idx in extra:
        if idx >= len(blocks):
            continue
        b = blocks[idx]
        ch = owner.get(id(b))
        if ch is None:
            continue
        if b.id is None:
            b.id = f"b{idx}"
        if not any(s[2] == b.id for s in ch.sections):
            ch.sections.append((min(lvl, 3), title, b.id))
    for ch in chapters:
        order = {id(b): i for i, b in enumerate(ch.blocks)}
        ids = {b.id: order[id(b)] for b in ch.blocks if b.id}
        ch.sections.sort(key=lambda s: ids.get(s[2], 0))


def _split_long(chapters: list[Chapter], max_chars: int = 400_000) -> list[Chapter]:
    out: list[Chapter] = []
    for ch in chapters:
        size = sum(len(plain(b.runs)) for b in ch.blocks if isinstance(b, Paragraph))
        if size <= max_chars or len(ch.blocks) < 40:
            out.append(ch)
            continue
        parts = max(2, size // (max_chars // 2))
        per = len(ch.blocks) // parts + 1
        for k in range(parts):
            seg = ch.blocks[k * per:(k + 1) * per]
            if not seg:
                continue
            sub = Chapter(f"{ch.title} ({k + 1})" if k else ch.title, seg, first_page=seg[0].page)
            sub.nav_level = ch.nav_level
            sub.title_is_heading = k == 0 and ch.title_is_heading
            sub.sections = [s for s in ch.sections if any(b.id == s[2] for b in seg)]
            out.append(sub)
    return out


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def resolve_links(chapters: list[Chapter]) -> None:
    by_page: dict[int, list[tuple[float, Block]]] = {}
    for ch in chapters:
        for b in ch.blocks:
            by_page.setdefault(b.page, []).append((b.y0, b))
    pages = sorted(by_page)
    counter = 0

    def target(page: int, y: float):
        for pg in pages:
            if pg >= page:
                cands = by_page[pg]
                if pg == page:
                    after = [c for c in cands if c[0] >= y - 6]
                    if after:
                        return min(after, key=lambda c: c[0])[1]
                    return max(cands, key=lambda c: c[0])[1]
                return min(cands, key=lambda c: c[0])[1]
        return None

    def fix(runs: list[Run]) -> None:
        nonlocal counter
        for r in runs:
            if r.link and r.link[0] == "page":
                t = target(r.link[1], r.link[2])
                if t is None:
                    r.link = None
                    continue
                if t.id is None:
                    counter += 1
                    t.id = f"t{counter}"
                r.link = ("anchor", t.id)
            elif r.link and r.link[0] == "url":
                href = safe_url(r.link[1])
                r.link = ("url", href) if href else None

    for ch in chapters:
        for b in ch.blocks:
            if isinstance(b, (Paragraph, Heading)):
                fix(b.runs)
            elif isinstance(b, ListBlock):
                for it in b.items:
                    fix(it)
            elif isinstance(b, Table):
                for row in b.rows:
                    for c in row:
                        fix(c)
            elif isinstance(b, Figure) and b.caption:
                fix(b.caption)


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------
_STOP = {
    "en": "the and of to in is that for it with as was on be by this are at from or an have not which but you".split(),
    "fr": "le la les de des du et en un une est que qui dans pour pas sur au avec ce il elle nous vous sont par plus mais ou".split(),
    "es": "el la los las de del y en un una es que por con para no se su al lo como más pero sus le ya".split(),
    "de": "der die das und ist nicht ein eine zu den von mit sich auf für des dem im auch es dass wird sie als".split(),
    "it": "il lo la i gli le di del e in un una è che per con non si su al come più ma sono dei delle nel".split(),
    "pt": "o a os as de do da e em um uma é que para com não se por mais mas dos das no na como ao".split(),
    "nl": "de het een en van in is dat op te voor met niet zijn aan er ook als maar om bij door nog".split(),
}


def detect_language(text: str, default: str = "en") -> str:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 30:
        return default
    cnt = Counter(words)
    scores = {lang: sum(cnt[w] for w in set(sw)) for lang, sw in _STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 0.05 * len(words) else default


_UNSAFE_TEXT_RE = re.compile("[\ud800-\udfff\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffe\uffff\u200b-\u200f\u202a-\u202e"
                             "\u2066-\u2069\ufeff]")


def clean_text_field(t: str | None, limit: int = 300) -> str:
    """Metadata / navigation text safe for XML and for UTF-8 encoding: lone surrogates (from broken UTF-16 metadata or
    non-UTF-8 file names), control and bidi-override characters removed, whitespace collapsed. May return ""."""
    if not t:
        return ""
    t = _UNSAFE_TEXT_RE.sub("", str(t))
    return re.sub(r"\s+", " ", t).strip()[:limit]


_PCT_FIX_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HOST_RE = re.compile(r"[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\]")


def safe_url(href: str | None) -> str | None:
    """A valid absolute http(s) / ftp / mailto URL built from a PDF link annotation, or None.

    Annotations hold raw spaces, non-ASCII, stray '%' and control characters (epubcheck RSC-020): the host is IDNA-encoded,
    path / query / fragment are percent-encoded (existing %XX escapes kept), user info is dropped, anything else is refused.
    """
    h = clean_text_field(href, 2048)
    m = re.match(r"(?i)^(https?|ftp|mailto):", h)
    if not m:
        return None
    try:
        parts = urlsplit(h)
        scheme = parts.scheme.lower()
        q = lambda v, safe: _PCT_FIX_RE.sub("%25", quote(v, safe=safe + "%"))  # noqa: E731
        if scheme == "mailto":
            addr = q(parts.path, "@.+-_!~*'()")
            if not re.fullmatch(r"[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", addr):
                return None
            return urlunsplit(("mailto", "", addr, q(parts.query, "=&"), ""))
        host = parts.hostname
        if not host:
            return None
        if ":" in host:
            host = f"[{host}]"
        else:
            host = host.encode("idna").decode("ascii")
        if not _HOST_RE.fullmatch(host) or len(host) > 253:
            return None
        netloc = host + (f":{parts.port}" if parts.port is not None else "")
        sub = "!$&'()*+,;=:@"
        return urlunsplit((scheme, netloc, q(parts.path or "/", sub + "/"), q(parts.query, sub + "/?"),
                           q(parts.fragment, sub + "/?")))
    except (ValueError, UnicodeError):
        return None


def clean_meta_title(t: str | None) -> str | None:
    t = clean_text_field(t)
    if not t:
        return None
    if len(t) < 2 or re.search(r"\.(pdf|docx?|tex|indd|qxd|odt|rtf|txt)$", t, re.I):
        return None
    if re.match(r"(?i)^(microsoft word|untitled|document\d*|slide \d+|powerpoint presentation)", t):
        return None
    return t[:300]


def mark_pages(chapters: list[Chapter], labels: dict[int, str]) -> None:
    """A page-break marker where each labelled page begins: inside a paragraph that runs across the break (set by
    `merge_across_breaks`), otherwise at the start of the page's first block."""
    if not labels:
        return
    seen: set[int] = set()
    for ch in chapters:
        for b in ch.blocks:
            for r in getattr(b, "runs", []) or []:
                if r.pagebreak:
                    seen.add(r.pagebreak)
    for ch in chapters:
        out = []
        for b in ch.blocks:
            p = getattr(b, "page", 0)
            if p in labels and p not in seen:
                seen.add(p)
                if isinstance(b, (Paragraph, Heading)):
                    b.runs = [Run("", pagebreak=p)] + b.runs
                else:
                    out.append(Paragraph([Run("", pagebreak=p)], "pagebreak", p, getattr(b, "y0", 0.0)))
            out.append(b)
        ch.blocks = out
    for ch in chapters:  # markers that do not belong to a labelled page go
        for b in ch.blocks:
            if getattr(b, "runs", None):
                b.runs = [r for r in b.runs if not r.pagebreak or r.pagebreak in labels]

