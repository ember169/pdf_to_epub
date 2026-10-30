import sys

import pytest

from pdftoepub import cli


def test_no_args_launches_ui_on_loopback_and_opens_browser(monkeypatch, tmp_path, capsys):
    calls = {}
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_free_port", lambda host, preferred=8000: 8123)

    def fake_run(host, port, *, open_browser=False, reload=False, desktop=False):
        calls.update(host=host, port=port, open=open_browser)
        return 0

    monkeypatch.setattr(cli, "run_server", fake_run)
    assert cli.main([]) == 0
    assert calls == {"host": "127.0.0.1", "port": 8123, "open": True}


def test_no_args_sets_default_data_dir(monkeypatch):
    import os

    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(cli, "run_server", lambda *a, **k: 0)
    cli.main([])
    assert os.environ["DATA_DIR"].endswith("pdftoepub")
    monkeypatch.delenv("DATA_DIR")


def test_serve_defaults_to_loopback(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run_server", lambda host, port, **k: seen.update(host=host, port=port, **k) or 0)
    cli.main(["serve"])
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8000 and not seen["open_browser"]
    cli.main(["serve", "--host", "0.0.0.0", "--port", "9000", "--open"])
    assert seen["host"] == "0.0.0.0" and seen["port"] == 9000 and seen["open_browser"]


def test_free_port_falls_back_when_busy():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        port = cli._free_port("127.0.0.1", busy)
    assert port != busy and port > 0


def test_run_server_warns_when_exposed_and_opens_browser(monkeypatch, capsys):
    import types
    import uvicorn
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    class FakeServer:
        started = False
        should_exit = False

        def __init__(self, config):
            self.config = config

        def run(self):
            self.started = True
            import time
            time.sleep(0.4)

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    cli.run_server("0.0.0.0", 8555, open_browser=True)
    out = capsys.readouterr()
    assert "AUTH_TOKEN" in out.err and "http://127.0.0.1:8555" in out.out
    assert "tourne" in out.out and "running" in out.out
    assert opened == ["http://127.0.0.1:8555"]


def test_launch_failure_pauses_on_windows(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_free_port", lambda *a, **k: 1)
    monkeypatch.setattr(cli, "run_server", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "")
    monkeypatch.setattr(sys, "stdin", object())
    assert cli.main([]) == 1
    assert asked and "boom" in capsys.readouterr().err


def test_convert_cli(tmp_path):
    from pdftoepub.web.tests.test_web import PDF

    src = tmp_path / "a.pdf"
    src.write_bytes(PDF)
    out = tmp_path / "a.epub"
    assert cli.main([str(src), "-o", str(out), "-q"]) == 0 and out.exists()
    assert cli.main([str(tmp_path / "missing.pdf")]) == 2
