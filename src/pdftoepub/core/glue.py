"""Words an OCR layer ran together without a space ("danslavie" -> "dans la vie"), split with a frequency lexicon.

OCR'd text only, French and English (`lexicon.py`; nothing happens without the lexicon or for another language).
A token is split only when all of these hold:
* it is all lower case, at least 5 letters, with no digit, apostrophe or hyphen, and not part of a URL or e-mail;
* it occurs only once in the book (a word the book repeats is the book's own word);
* it is not a common word itself (Zipf < 3.5: wordfreq's lists also hold frequent typos such as "dela"), nor a word of
  the other language (Zipf >= 3: "differently abled" in a French book);
* its best segmentation into 2 or 3 words is far more probable than the token: the parts' summed log-frequencies beat the
  token's own by `MARGIN` (log10 units); each part is a common word (Zipf >= 3), or an allowed one-letter word beside a
  function word ("il a", "à la"; not "drap a");
* it is not one letter away from a common word (an OCR misread: "auleurs" is "auteurs", not "au leurs");
* parts of one or two letters are function words ("la", "de", "of"; not "ci", "es"), and after a prefix-like word
  ("in", "all", "en", "sur", "anti") only a function word may follow ("in the", not "in dwellers").
"""
from __future__ import annotations

import re
from collections import Counter

from . import lexicon
from .ir import Endnotes, Heading, ListBlock, Paragraph, Table

KNOWN = 3.5  # a token this common is a word, not two
PART = 3.0  # each part of a split is at least this common
MARGIN = 1.5  # the split must be 10^1.5 times more probable than the token
GLUE_WORD = 5.5  # a function word ("de", "la", "il", "the", "of")
AFTER_PREFIX = 6.0  # after a prefix-like word, only a very common one ("in the", "sur la"; not "anti es")
PART3 = 4.0  # a three-letter part is a common word, not an abbreviation ("sci")
OTHER = 3.0  # a word of the other language this common is left alone ("differently abled" in French text)
MISREAD = 3.0  # a word this common one letter away: the token is that word misread
SINGLE = {"fr": {"à", "a", "y"}, "en": {"a", "i"}}
PREFIXES = {"fr": {"en", "entre", "contre", "sous", "sur", "anti", "re", "dé", "pré", "in", "a", "non", "auto", "co"},
            "en": {"in", "on", "a", "all", "over", "out", "up", "under", "for", "with", "be", "re", "un", "pre", "non",
                   "co", "anti", "self", "down", "back"}}
TOKEN_RE = re.compile(r"(?<![\w'’@/.\-])[a-zà-öø-ÿœæ]{5,40}(?![\w'’@/\-]|\.\w)")


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


def segment(token: str, lang: str, freq: dict[str, float]) -> list[str] | None:
    """The best split of `token` into 2-3 lexicon words, or None."""
    singles = SINGLE.get(lang, set())

    def ok(p: str) -> bool:
        if len(p) <= 2:  # "la", "de", "of", "à": function words only (not "ci", "es", "ii")
            return (len(p) == 2 or p in singles) and freq.get(p, 0.0) >= GLUE_WORD
        return freq.get(p, 0.0) >= (PART3 if len(p) == 3 else PART)  # short ones: not abbreviations ("sci")

    best, best_score = None, None
    n = len(token)
    for i in range(1, n):
        a = token[:i]
        if not ok(a):
            continue
        rest = token[i:]
        cands = [[a, rest]] if ok(rest) else []
        for j in range(1, len(rest)):
            if ok(rest[:j]) and ok(rest[j:]):
                cands.append([a, rest[:j], rest[j:]])
        for parts in cands:
            if any(len(p) == 1 and not any(freq[q] >= GLUE_WORD for q in parts[max(0, k - 1):k + 2] if q != p)
                   for k, p in enumerate(parts)):
                continue  # a one-letter word only beside a very common one ("il a", "à la"), not "drap a"
            if parts[0] in PREFIXES.get(lang, ()) and freq[parts[1]] < AFTER_PREFIX:
                continue  # "in dwellers", "anti es": a word built on a prefix, unless a function word follows ("in the")
            score = sum(freq[p] - 9 for p in parts)
            if best_score is None or score > best_score:
                best, best_score = parts, score
    if best is None:
        return None
    own = freq.get(token, 0.0) - 9  # absent: the floor of the list
    return best if best_score > own + MARGIN else None


def misread(token: str, freq: dict[str, float]) -> bool:
    """One letter away from a common word ("auleurs" / auteurs, "planle" / plante, "suile" / suite): an OCR misread of
    that word, not two words run together."""
    letters = "abcdefghijklmnopqrstuvwxyzàâçéèêëîïôûùüÿœæ"
    for i, c in enumerate(token):
        for x in letters:
            if x != c and freq.get(token[:i] + x + token[i + 1:], 0.0) >= MISREAD:
                return True
    return False


def split_glued(blocks, lang: str) -> list[tuple[str, str]]:
    """Edit the runs in place. Returns the changes [(token, replacement)]."""
    lang = (lang or "").split("-")[0].lower()
    freq = lexicon.table(lang)
    if not freq:
        return []
    other = lexicon.table("en" if lang == "fr" else "fr", OTHER)  # only its common words matter (smaller in memory)
    counts: Counter = Counter()
    for runs in _runs(blocks):
        for r in runs:
            if not r.mono and r.image is None:
                counts.update(TOKEN_RE.findall(r.text))
    changes: list[tuple[str, str]] = []

    def fix(m: re.Match) -> str:
        w = m.group(0)
        if counts[w] > 1 or freq.get(w, 0.0) >= KNOWN or other.get(w, 0.0) >= OTHER or misread(w, freq):
            return w
        parts = segment(w, lang, freq)
        if not parts:
            return w
        new = " ".join(parts)
        changes.append((w, new))
        return new

    for runs in _runs(blocks):
        for r in runs:
            if r.mono or r.image is not None or r.link or r.pagebreak or not r.text:
                continue
            if "@" in r.text or "://" in r.text or "www." in r.text:
                continue  # an address: its pieces are not words
            r.text = TOKEN_RE.sub(fix, r.text)
    return changes
