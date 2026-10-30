import importlib.util
import os

import pytest


@pytest.fixture(autouse=True, params=["pdfminer", "pymupdf"])
def backend(request, monkeypatch):
    """Run every core test once per PDF backend."""
    if request.param == "pymupdf" and importlib.util.find_spec("pymupdf") is None:
        pytest.skip("pymupdf not installed")
    monkeypatch.setenv("PDFTOEPUB_BACKEND", request.param)
    return request.param
