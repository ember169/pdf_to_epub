"""Optional Tesseract OCR (subprocess, TSV output). Degrades gracefully when tesseract is not installed."""
from __future__ import annotations

import os
import re
import shutil
import statistics
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .ir import Line, Span

OCR_DPI = 300
_LANG_RE = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")


@dataclass
class OcrEngine:
    exe: str
    langs: str  # tesseract syntax, validated against installed languages
    warning: str | None = None


def find_engine(requested_langs: str) -> tuple[OcrEngine | None, str | None]:
    """Return (engine, warning). engine is None when tesseract (or any usable language) is unavailable."""
    exe = shutil.which("tesseract")
    if not exe:
        return None, "Tesseract is not installed; pages without a text layer were not recognised."
    try:
        res = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30)
        installed = {l.strip() for l in res.stdout.splitlines()[1:] if l.strip()} - {"osd"}
    except (OSError, subprocess.SubprocessError):
        return None, "Tesseract could not be started; OCR was skipped."
    wanted = [l for l in (requested_langs or "eng").split("+") if l] if _LANG_RE.match(requested_langs or "eng") else ["eng"]
    have = [l for l in wanted if l in installed]
    warn = None
    if have != wanted:
        missing = [l for l in wanted if l not in installed]
        warn = f"OCR language data missing: {', '.join(missing)}"
    if not have:
        if "eng" in installed:
            have = ["eng"]
        elif installed:
            have = [sorted(installed)[0]]
        else:
            return None, "Tesseract has no language data installed; OCR was skipped."
    return OcrEngine(exe, "+".join(have), warn), None


def ocr_image(engine: OcrEngine, image, pno: int, timeout: int = 300) -> list[Line] | None:
    """Run tesseract on a PIL image rendered at OCR_DPI. Returns Lines (sizes in points) or None on failure."""
    with tempfile.TemporaryDirectory(prefix="pdftoepub-ocr-") as tmp:
        img = Path(tmp) / "page.png"
        try:
            image.save(str(img))
        except Exception:  # noqa: BLE001
            return None
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        try:
            res = subprocess.run(
                [engine.exe, str(img), "stdout", "-l", engine.langs, "--psm", "3", "tsv"],
                capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return None
    if res.returncode != 0:
        return None
    return parse_tsv(res.stdout, pno, 72.0 / OCR_DPI)


# Share of the em a word box spans, by the glyph zones its letters reach: x-height only ("une"), ascenders / capitals /
# digits / accents ("été"), descenders ("pas"), both ("lequel"). Dividing the box height by it gives a font size that
# no longer depends on which letters a line happens to contain (raw box heights vary by a factor of two).
_ASC = set("bdfhklt0123456789ij'\"!?/()[]{}|ßŀ")
_DESC = set("gjpqyµç,;")
_ZONE = {(False, False): 0.48, (True, False): 0.73, (False, True): 0.70, (True, True): 0.95}


def _word_em(text: str) -> float | None:
    letters = [c for c in text if c.isalnum()]
    if len(letters) < 2:
        return None
    up = desc = False
    cap_accent = False
    for c in text:
        base = unicodedata.normalize("NFD", c)
        if c.isupper() or c in _ASC or (len(base) > 1 and c.isalpha()):
            up = True
        if c.isupper() and len(base) > 1:
            cap_accent = True
        if c in _DESC:
            desc = True
    return _ZONE[(up, desc)] + (0.12 if cap_accent else 0.0)


def line_size_px(words) -> float:
    """Font size (px) of an OCR line: median over its words of box height / glyph-zone share (see _ZONE)."""
    est = sorted(w[3] / em for w in words if (em := _word_em(w[5])))
    if not est:
        hs = sorted(w[3] for w in words)
        return hs[len(hs) // 2] / 0.73
    return est[len(est) // 2]


def parse_tsv(tsv: str, pno: int, scale: float) -> list[Line]:
    rows = tsv.splitlines()
    if not rows:
        return []
    groups: dict[tuple, list[tuple[int, int, int, int, float, str]]] = {}
    order: list[tuple] = []
    for r in rows[1:]:
        c = r.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        text = c[11].strip()
        try:
            conf = float(c[10])
            left, top, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        except ValueError:
            continue
        if not text or conf < 0:
            continue
        key = (c[2], c[3], c[4])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((left, top, w, h, conf, text))
    lines: list[Line] = []
    for key in order:
        words = sorted(groups[key], key=lambda w: w[0])
        mean_conf = statistics.mean(w[4] for w in words)
        text = " ".join(w[5] for w in words)
        if mean_conf < 25 and len(text) < 40:
            continue
        x0 = min(w[0] for w in words)
        y0 = min(w[1] for w in words)
        x1 = max(w[0] + w[2] for w in words)
        y1 = max(w[1] + w[3] for w in words)
        size = max(line_size_px(words) * scale, 4.0)
        span = Span(text, size, False, False, False, False, False, (x0 * scale, y0 * scale, x1 * scale, y1 * scale))
        lines.append(Line([span], (x0 * scale, y0 * scale, x1 * scale, y1 * scale), pno))
    return lines
