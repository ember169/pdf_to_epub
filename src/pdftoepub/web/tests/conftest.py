import pytest

from pdftoepub import cli


@pytest.fixture(autouse=True)
def _isolated_desktop_state(monkeypatch, tmp_path_factory):
    """Same result whether or not a real pdftoepub desktop instance runs on this machine: never read the real
    default data dir (desktop.json) and never reuse a running server."""
    root = tmp_path_factory.mktemp("appdata")
    monkeypatch.setattr(cli, "_default_data_dir", lambda: str(root / "pdftoepub"))
    monkeypatch.setenv("DATA_DIR", str(root / "pdftoepub"))
