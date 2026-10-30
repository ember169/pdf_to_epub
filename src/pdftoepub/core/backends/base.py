"""Backend interface: everything layout/structure/epub need from a PDF library.

A backend opens a file and yields, per page, a `PageData` (lines -> spans with font size / bold / italic /
sup / sub / mono / link, bboxes in PDF points with a top-left origin; images already decoded and stored in
the shared `ImageStore`; vector figures rasterised; ruled tables). It can also render a page for OCR / cover.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..ir import PageData
from .common import ImageStore

if TYPE_CHECKING:
    from PIL import Image


# PDFium is not thread-safe, not even across different documents (pypdfium2 docs): every pdfium call - including
# closing pages / bitmaps, which pypdfium2 otherwise leaves to GC finalisers - must hold this lock. Keep the sections
# short: pdfminer parsing, layout analysis and OCR run outside it, so concurrent jobs only queue on rendering.
PDFIUM_LOCK = threading.RLock()


class TocEntry(tuple):
    """(level, title, page_1_based, y_top_left or 0.0)"""


class PdfDocument(ABC):
    name = "?"
    page_count: int = 0
    # backend-level notes (e.g. "rendering was downscaled") that the pipeline adds to ConvertResult.warnings
    warnings: list[str]

    @abstractmethod
    def metadata(self) -> dict[str, str]:
        """Keys 'title', 'author' (strings, possibly empty)."""

    @abstractmethod
    def toc(self) -> list[tuple[int, str, int, float]]:
        """Outline entries (level, title, page, y). May raise; the caller degrades to heading detection."""

    @abstractmethod
    def extract_page(self, pno: int, image_mode: str, store: ImageStore, warnings: list[str]) -> PageData:
        """Extract page `pno` (1-based). `image_mode == "none"` means: do not extract images/figures."""

    @abstractmethod
    def render_page(self, pno: int, dpi: float, gray: bool = False) -> "Image.Image":
        """Render the whole page for OCR or the cover."""

    @abstractmethod
    def close(self) -> None: ...


class PdfBackend(ABC):
    name = "?"
    # True when the library keeps global state that cannot be locked call by call (MuPDF): the pipeline then
    # serialises every call into the document (but not OCR, layout analysis or packaging)
    needs_global_lock = False

    @classmethod
    @abstractmethod
    def available(cls) -> bool: ...

    @abstractmethod
    def open(self, path) -> PdfDocument:
        """Open a PDF. Raises ConversionError for unreadable / not a PDF / password-protected / zero pages."""
