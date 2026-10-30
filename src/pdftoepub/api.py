"""Frozen public contract. Web/CLI call only `convert`. Do not change signatures without the master session."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal


class ConversionError(Exception):
    """Unrecoverable conversion failure (not a PDF, encrypted, ...). Message is user-safe."""


@dataclass
class ConvertOptions:
    title: str | None = None
    author: str | None = None
    language: str | None = None  # BCP47; None = detect
    ocr: Literal["auto", "off", "force"] = "auto"
    ocr_langs: str = "fra+eng"  # tesseract syntax
    drop_headers_footers: bool = True
    detect_columns: bool = True
    image_mode: Literal["inline", "none"] = "inline"


@dataclass
class ProgressEvent:
    stage: str  # "extract" | "ocr" | "analyze" | "build" | "done"
    page: int = 0
    total_pages: int = 0
    message: str = ""


@dataclass
class ConvertResult:
    epub_path: Path
    title: str
    page_count: int
    chapter_count: int
    ocr_pages: int = 0
    warnings: list[str] = field(default_factory=list)


ProgressCb = Callable[[ProgressEvent], None]


def convert(
    pdf_path: str | Path,
    epub_path: str | Path,
    options: ConvertOptions | None = None,
    progress: ProgressCb | None = None,
) -> ConvertResult:
    options = options or ConvertOptions()
    pdf_path, epub_path = Path(pdf_path), Path(epub_path)
    try:
        from .core.pipeline import run
    except ImportError:
        return _stub(pdf_path, epub_path, options, progress)
    return run(pdf_path, epub_path, options, progress)


def _stub(pdf_path: Path, epub_path: Path, options: ConvertOptions, progress: ProgressCb | None) -> ConvertResult:
    """Placeholder until core lands: minimal valid-ish EPUB so web/CLI can be developed end to end."""
    import time

    with open(pdf_path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise ConversionError("Not a PDF file")
    for i in range(1, 4):
        if progress:
            progress(ProgressEvent("extract", i, 3, "stub"))
        time.sleep(0.2)
    title = options.title or pdf_path.stem
    with zipfile.ZipFile(epub_path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="c.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("c.opf", f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="i"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="i">stub</dc:identifier><dc:title>{title}</dc:title><dc:language>en</dc:language></metadata><manifest><item id="n" href="n.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="n"/></spine></package>')
        z.writestr("n.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>stub</title></head><body><nav epub:type="toc"><ol><li><a href="n.xhtml">stub</a></li></ol></nav></body></html>')
    if progress:
        progress(ProgressEvent("done", 3, 3))
    return ConvertResult(epub_path, title, 3, 1, 0, ["stub converter: core not installed"])
