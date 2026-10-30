"""PDF backends. `get_backend()` picks one from $PDFTOEPUB_BACKEND ("auto" | "pdfminer" | "pymupdf").

"auto" means the MIT-clean default (pdfminer.six + pypdfium2) everywhere. PyMuPDF (AGPL) is only used when it is
installed AND explicitly requested; it is imported lazily from `pymupdf_backend.py` and nowhere else.
"""
from __future__ import annotations

import os

from .base import PdfBackend, PdfDocument  # noqa: F401


def get_backend(name: str | None = None) -> tuple[PdfBackend, str | None]:
    """Return (backend, warning). A warning is produced when the requested backend is unavailable."""
    choice = (name or os.environ.get("PDFTOEPUB_BACKEND") or "auto").strip().lower()
    warning = None
    if choice == "pymupdf":
        try:
            from .pymupdf_backend import PyMuPDFBackend

            if PyMuPDFBackend.available():
                return PyMuPDFBackend(), None
        except ImportError:
            pass
        warning = "PyMuPDF backend requested but not installed; using the pdfminer backend."
    elif choice not in ("auto", "pdfminer"):
        warning = f"Unknown PDFTOEPUB_BACKEND={choice!r}; using the pdfminer backend."
    from .pdfminer_backend import PdfMinerBackend

    return PdfMinerBackend(), warning
