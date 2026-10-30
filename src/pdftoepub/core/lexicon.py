"""Word frequency lexicons (French, English) for repairing OCR text: wordfreq 3.2 "large" lists, shipped unmodified.

The data files are not in the repository: `python -m pdftoepub.core.lexicon fetch` downloads them into
`core/data/wordfreq/` (pinned commit, sha256 checked) with wordfreq's licence and the attributions its data requires.
Without them, `zipf()` knows no word and the repairs that use it do nothing.

wordfreq (https://github.com/rspeer/wordfreq, tag v3.2, commit 42233e6) by Robyn Speer: code under the Apache License 2.0,
data files under Creative Commons Attribution-ShareAlike 4.0. Its data comes from Google Books Ngrams, OpenSubtitles 2018
(OPUS; attribution to OpenSubtitles), SUBTLEX (Marc Brysbaert et al.; freely available data, credited), Wikipedia,
the Leeds Internet Corpus, ParaCrawl and Twitter statistics. The files are used as published (no conversion) and are
read with the small MessagePack reader below.

A list is a MessagePack array: a header map, then one array of words per frequency bin; bin i holds the words seen
10^(-i/100) of the time, so their Zipf value is 9 - i/100 (wordfreq's own definition).
"""
from __future__ import annotations

import gzip
import hashlib
import os
import struct
import sys
import urllib.request
from functools import lru_cache
from pathlib import Path

COMMIT = "42233e6c36ce792031bcccfa17cdd0cec9af5fa7"  # wordfreq tag v3.2
BASE = f"https://raw.githubusercontent.com/rspeer/wordfreq/{COMMIT}"
FILES = {
    "large_fr.msgpack.gz": (f"{BASE}/wordfreq/data/large_fr.msgpack.gz",
                            "6f16cd80b9b66c5698ed002becea83ae30d0584c3205f1cf01714ad562c00c8b"),
    "large_en.msgpack.gz": (f"{BASE}/wordfreq/data/large_en.msgpack.gz",
                            "dffae8066b78dce0a6667cf5f58e567054f902674667090a7ac8a8a44628b05c"),
    "LICENSE.txt": (f"{BASE}/LICENSE.txt", "8990c551671a51765c4dfe9428f3e1d58dc327f49aca346a32d28cc0fcc7aa88"),
}
LANGS = ("fr", "en")
NOTICE = """wordfreq data (large_fr.msgpack.gz, large_en.msgpack.gz), unmodified
=====================================================================
From wordfreq 3.2 by Robyn Speer, https://github.com/rspeer/wordfreq (commit 42233e6c36ce792031bcccfa17cdd0cec9af5fa7).
wordfreq's code is under the Apache License 2.0 (LICENSE.txt). These data files are under the Creative Commons
Attribution-ShareAlike 4.0 license, https://creativecommons.org/licenses/by-sa/4.0/ .

The data contains material from:
- Google Books Ngrams (http://books.google.com/ngrams) and Google Books Syntactic Ngrams;
- OPUS OpenSubtitles 2018 (http://opus.nlpl.eu/OpenSubtitles.php), from the OpenSubtitles project
  (http://www.opensubtitles.org/), used with attribution to OpenSubtitles;
- SUBTLEX word lists by Marc Brysbaert et al. (http://crr.ugent.be/programs-data/subtitle-frequencies); SUBTLEX is
  freely available data;
- Wikipedia (http://www.wikipedia.org), the Leeds Internet Corpus (http://corpus.leeds.ac.uk/list.html) and ParaCrawl
  (https://paracrawl.eu), Creative Commons-licensed sources;
- word statistics from the Twitter streaming API (no Twitter content is republished).
"""


def data_dir() -> Path:
    env = os.environ.get("PDFTOEPUB_LEXICON_DIR")
    if env:
        return Path(env)
    base = Path(getattr(sys, "_MEIPASS", "")) / "pdftoepub" / "core" if hasattr(sys, "_MEIPASS") else Path(__file__).parent
    return base / "data" / "wordfreq"


def fetch(dest: Path | None = None) -> Path:
    dest = dest or data_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for name, (url, sha) in FILES.items():
        path = dest / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            continue
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - pinned https URL
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != sha:
            raise RuntimeError(f"{name}: sha256 {got}, expected {sha}")
        path.write_bytes(data)
    (dest / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    return dest


def _unpack(b: bytes):
    """The MessagePack subset wordfreq's lists use: arrays, maps, strings, small integers."""
    def read(i: int):
        t = b[i]
        if t <= 0x7F:
            return t, i + 1
        if 0x80 <= t <= 0x8F or t in (0xDE, 0xDF):
            n, i = (t & 0x0F, i + 1) if t <= 0x8F else (
                (struct.unpack_from(">H", b, i + 1)[0], i + 3) if t == 0xDE else (struct.unpack_from(">I", b, i + 1)[0], i + 5))
            out = {}
            for _ in range(n):
                k, i = read(i)
                v, i = read(i)
                out[k] = v
            return out, i
        if 0x90 <= t <= 0x9F or t in (0xDC, 0xDD):
            n, i = (t & 0x0F, i + 1) if t <= 0x9F else (
                (struct.unpack_from(">H", b, i + 1)[0], i + 3) if t == 0xDC else (struct.unpack_from(">I", b, i + 1)[0], i + 5))
            out = []
            for _ in range(n):
                v, i = read(i)
                out.append(v)
            return out, i
        if 0xA0 <= t <= 0xBF or t in (0xD9, 0xDA, 0xDB):
            if t <= 0xBF:
                n, i = t & 0x1F, i + 1
            elif t == 0xD9:
                n, i = b[i + 1], i + 2
            elif t == 0xDA:
                n, i = struct.unpack_from(">H", b, i + 1)[0], i + 3
            else:
                n, i = struct.unpack_from(">I", b, i + 1)[0], i + 5
            return b[i:i + n].decode("utf-8"), i + n
        if t == 0xC0:
            return None, i + 1
        if t == 0xCC:
            return b[i + 1], i + 2
        if t == 0xCD:
            return struct.unpack_from(">H", b, i + 1)[0], i + 3
        raise ValueError(f"unsupported MessagePack type 0x{t:02x} at {i}")

    value, _ = read(0)
    return value


@lru_cache(maxsize=4)
def table(lang: str, min_zipf: float = 0.0) -> dict[str, float]:
    """word -> Zipf frequency, words at least `min_zipf` (empty when the list is not installed)."""
    if lang not in LANGS:
        return {}
    path = data_dir() / f"large_{lang}.msgpack.gz"
    try:
        bins = _unpack(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return {}
    if not isinstance(bins, list) or not bins or not isinstance(bins[0], dict) or bins[0].get("format") != "cB":
        return {}
    out: dict[str, float] = {}
    for i, words in enumerate(bins[1:]):
        z = 9 - i / 100
        if z < min_zipf:
            break
        for w in words or []:
            out.setdefault(w, z)
    return out


def available(lang: str) -> bool:
    return bool(table(lang))


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        print(fetch())
    else:
        print("usage: python -m pdftoepub.core.lexicon fetch")
