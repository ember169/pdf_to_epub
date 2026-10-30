"""Conservative corrections of common OCR misreads, for books read from an OCR layer or by OCR.

The lexicon is the book itself: a word is changed only when the corrected form occurs at least `MIN_SEEN` times in the
book and the original at most once ("Tolstoî" -> "Tolstoï", "Kaufrnan" -> "Kaufman"). Fixed patterns need no
lexicon: a superscript "c" after a roman numeral is an "e" ("xixᶜ siècle"), "lbid" is "Ibid", "Tbe" is "The", and
digits misread or spaced in years and page references ("i979", "2O09", "p. 4 05", "1 9 8 4") are rejoined.
"""
from __future__ import annotations

import re
from collections import Counter

from .ir import Endnotes, Heading, ListBlock, Paragraph, Table

MIN_SEEN = 3
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
ROMAN_RE = re.compile(r"(?i)(?:^|\s)[ivxlc]{1,6}$")
CAMEL_RE = re.compile(r"([a-zà-ÿ]{2,})([A-ZÀ-Þ][a-zà-ÿ]{2,})")
# (pattern, replacement, rule name); applied to plain runs
FIXED = [
    (re.compile(r"\blbid\b"), "Ibid", "lbid"),
    (re.compile(r"\bTbe\b"), "The", "Tbe"),
    (re.compile(r"\b([xvi]{1,6})c(?= si[eè]cles?\b)", re.I), r"\1e", "roman-c"),
    (re.compile(r"(?<=\d)[Oo](?=\d)|(?<=\d\d)[Oo]\b(?=[\s.,;)])"), "0", "O-digit"),
    (re.compile(r"\bi(?=(?:1[5-9]|20)\d\d\b)"), "1", "i-digit"),
    (re.compile(r"\b(p{1,2}\.\s*)(\d{1,2}) (\d{1,2})\b(?![\d,])"), r"\1\2\3", "spaced-page"),
    (re.compile(r"(?<![\d,.])\b((?:1[5-9]|20)) ?(\d) (\d)\b(?!\d|,\d)"), r"\1\2\3", "spaced-year"),
    (re.compile(r"(?<![\d,.])\b([12]) (\d) (\d) (\d)\b(?!\d|,\d)"), r"\1\2\3\4", "spaced-year"),
]
SWAPS = [("î", "ï"), ("î", "i"), ("rn", "m"), ("m", "rn")]  # the classic OCR confusions only


def _runs(blocks):
    for b in blocks:
        if isinstance(b, (Paragraph, Heading)):
            yield b.runs
        elif isinstance(b, ListBlock):
            yield from b.items
        elif isinstance(b, Table):
            for row in b.rows:
                yield from row
        elif isinstance(b, Endnotes):
            for fn in b.notes:
                yield fn.runs


def correct(blocks) -> Counter:
    """Edit the blocks' runs in place. Returns the number of changes per rule."""
    vocab: Counter = Counter()
    for runs in _runs(blocks):
        for w in WORD_RE.findall("".join(r.text for r in runs)):
            vocab[w] += 1
    done: Counter = Counter()

    def lexical(m: re.Match) -> str:
        w = m.group(0)
        if vocab[w] > 1 or len(w) < 4:
            return w
        c = CAMEL_RE.fullmatch(w)  # a space the layer lost between two words ("ofCalifornia")
        if c and vocab[c.group(1)] >= MIN_SEEN and vocab[c.group(2)] >= MIN_SEEN:
            done["camel"] += 1
            return f"{c.group(1)} {c.group(2)}"
        best = None
        for a, b in SWAPS:
            if a in w:
                for k in [i for i in range(len(w)) if w.startswith(a, i)]:
                    cand = w[:k] + b + w[k + len(a):]
                    if vocab[cand] >= MIN_SEEN and (best is None or vocab[cand] > vocab[best]):
                        best = cand
        if best:
            done["lexicon"] += 1
            return best
        return w

    for runs in _runs(blocks):
        for i, r in enumerate(runs):
            if r.pagebreak or r.image is not None or r.mono:
                continue
            if r.sup and r.text.strip() == "c" and i > 0 and ROMAN_RE.search(runs[i - 1].text.rstrip()):
                r.text = r.text.replace("c", "e")
                done["roman-c"] += 1
                continue
            t = r.text
            for rx, rep, name in FIXED:
                t, n = rx.subn(rep, t)
                done[name] += n
            r.text = WORD_RE.sub(lexical, t)
    return done
