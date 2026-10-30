from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # allow `import fixtures.make_fixtures`, `import epubcheck`

from fixtures import make_fixtures  # noqa: E402

import pdftoepub  # noqa: E402
from pdftoepub.api import ConvertOptions  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "core: needs the real conversion core (xfail/skip while the stub is active)")
    config.addinivalue_line("markers", "epubcheck: needs java for epubcheck (skipped if missing)")


@pytest.fixture(scope="session", autouse=True, params=["pdfminer", "pymupdf"])
def backend(request):
    """Run every test once per extraction backend via PDFTOEPUB_BACKEND."""
    import importlib.util
    import os
    if request.param == "pymupdf" and importlib.util.find_spec("pymupdf") is None:
        pytest.skip("pymupdf not installed")
    old = os.environ.get("PDFTOEPUB_BACKEND")
    os.environ["PDFTOEPUB_BACKEND"] = request.param
    yield request.param
    if old is None:
        os.environ.pop("PDFTOEPUB_BACKEND", None)
    else:
        os.environ["PDFTOEPUB_BACKEND"] = old


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    return make_fixtures.build_all(tmp_path_factory.mktemp("pdfs"))


@pytest.fixture(scope="session")
def convert_fixture(fixtures, tmp_path_factory):
    """Convert a named fixture once; returns (ConvertResult, Spec)."""
    cache: dict = {}
    out = tmp_path_factory.mktemp("epubs")

    def run(name: str, **opts):
        key = (name, tuple(sorted(opts.items())))
        if key not in cache:
            pdf, spec = fixtures[name]
            cache[key] = (pdftoepub.convert(pdf, out / f"{name}-{len(cache)}.epub", ConvertOptions(**opts)), spec)
        return cache[key]

    return run


def _stub_active(tmp_path_factory) -> bool:
    d = tmp_path_factory.mktemp("probe")
    pdf, _ = make_fixtures.build("single_column", d)
    return any("stub" in w for w in pdftoepub.convert(pdf, d / "p.epub").warnings)


@pytest.fixture(scope="session")
def stub_active(tmp_path_factory):
    return _stub_active(tmp_path_factory)


@pytest.fixture(autouse=True)
def _skip_core_on_stub(request, stub_active):
    if request.node.get_closest_marker("core") and stub_active:
        pytest.xfail("stub converter active (real core not installed)")
