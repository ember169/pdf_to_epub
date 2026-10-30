import json
import time

import pytest
from fastapi.testclient import TestClient

from pdftoepub import cli
from pdftoepub.web.app import create_app
from pdftoepub.web.config import Settings
from pdftoepub.web.tests.test_security import _big_pdf, _convert_children
from pdftoepub.web.tests.test_web import post

LOCAL = ("127.0.0.1", 50000)
HDR = {"X-Requested-With": "pdftoepub"}


def desk(tmp_path, **kw):
    kw.setdefault("desktop", True)
    kw.setdefault("allowed_hosts", ("testserver",))
    exits = []
    app = create_app(Settings(data_dir=tmp_path, janitor_interval_s=3600, **kw))
    app.state.request_exit = lambda: exits.append(1)
    return app, exits


def test_config_and_healthz_identify_app(tmp_path):
    app, _ = desk(tmp_path)
    with TestClient(app, client=LOCAL) as c:
        assert c.get("/api/config").json()["desktop"] is True
        h = c.get("/healthz").json()
        assert h["ok"] and h["app"] == "pdftoepub" and h["version"]
        assert c.get("/api/ping").json() == {"ok": True}
    app2, _ = desk(tmp_path, desktop=False)
    with TestClient(app2) as c:
        assert c.get("/api/config").json()["desktop"] is False


def test_shutdown_404_outside_desktop(tmp_path):
    app, exits = desk(tmp_path, desktop=False)
    with TestClient(app, client=LOCAL) as c:
        assert c.post("/api/shutdown", headers=HDR).status_code == 404
    assert not exits


def test_shutdown_ok_cancels_jobs_and_exits_after_flush(tmp_path):
    app, exits = desk(tmp_path)
    killed = []
    app.state.jobs.cancel_all = lambda: killed.append(1) or 0
    with TestClient(app, client=LOCAL) as c:
        r = c.post("/api/shutdown", headers=HDR)
        assert r.status_code == 202 and r.json() == {"ok": True}
        assert killed and not exits  # exit is deferred so the response is flushed first
        time.sleep(0.8)
        assert exits == [1]


@pytest.mark.parametrize("client,headers,code", [
    (("203.0.113.9", 1), HDR, 403),                                   # not a loopback client
    (LOCAL, {}, 403),                                                  # no CSRF header
    (LOCAL, {**HDR, "Origin": "http://evil.example"}, 403),            # cross-origin
    (LOCAL, {**HDR, "Sec-Fetch-Site": "cross-site"}, 403),
    (LOCAL, {**HDR, "Host": "evil.example"}, 400),                     # DNS rebinding
])
def test_shutdown_refused(tmp_path, client, headers, code):
    app, exits = desk(tmp_path)
    with TestClient(app, client=client) as c:
        assert c.post("/api/shutdown", headers=headers).status_code == code
        time.sleep(0.7)
    assert not exits


def test_shutdown_requires_token_when_set(tmp_path):
    app, exits = desk(tmp_path, auth_token="s3cret")
    with TestClient(app, client=LOCAL) as c:
        assert c.post("/api/shutdown", headers=HDR).status_code == 401
        assert c.post("/api/shutdown", headers={**HDR, "Authorization": "Bearer s3cret"}).status_code == 202


def test_shutdown_kills_running_conversion_child(tmp_path):
    app, exits = desk(tmp_path, job_timeout_s=120)
    with TestClient(app, client=LOCAL) as c:
        jid = post(c, data=_big_pdf(600)).json()["id"]
        end = time.time() + 30
        while time.time() < end and c.get(f"/api/jobs/{jid}").json()["stage"] in ("queued", "start"):
            time.sleep(0.05)
        assert _convert_children()
        assert c.post("/api/shutdown", headers=HDR).status_code == 202
        end = time.time() + 15
        while time.time() < end and _convert_children():
            time.sleep(0.1)
        assert not _convert_children()


def test_idle_exit(tmp_path):
    app, exits = desk(tmp_path, idle_exit_min=1)
    with TestClient(app, client=LOCAL) as c:
        assert app.state.idle_check() is False and not exits       # just started
        app.state.last_activity -= 61
        assert app.state.idle_check() is True and exits == [1]


def test_idle_exit_waits_for_pending_jobs_and_activity(tmp_path):
    app, exits = desk(tmp_path, idle_exit_min=1)
    with TestClient(app, client=LOCAL) as c:
        app.state.last_activity -= 61
        app.state.jobs._pending = 1
        assert app.state.idle_check() is False
        app.state.jobs._pending = 0
        c.get("/api/ping")                                          # any request counts as activity
        assert app.state.idle_check() is False
        assert not exits


def test_idle_exit_disabled_or_not_desktop(tmp_path):
    for kw in ({"idle_exit_min": 0}, {"desktop": False, "idle_exit_min": 1}):
        app, exits = desk(tmp_path, **kw)
        with TestClient(app, client=LOCAL):
            app.state.last_activity -= 10_000
            assert app.state.idle_check() is False and not exits


def test_idle_exit_env(monkeypatch):
    monkeypatch.setenv("IDLE_EXIT_MIN", "0")
    assert Settings.from_env().idle_exit_min == 0
    monkeypatch.delenv("IDLE_EXIT_MIN")
    assert Settings.from_env().idle_exit_min == 15


# ---- CLI side -----------------------------------------------------------------------------------------------------

def test_instance_file_is_private_atomic_and_removed_only_by_owner(tmp_path):
    cli._write_instance(tmp_path, 8123)
    f = tmp_path / "desktop.json"
    assert json.loads(f.read_text()) == {"port": 8123, "pid": __import__("os").getpid()}
    assert (f.stat().st_mode & 0o777) == 0o600 or __import__("sys").platform == "win32"
    assert not list(tmp_path.glob("*.tmp"))
    f.write_text(json.dumps({"port": 1, "pid": 1}))                  # someone else's
    cli._remove_instance(tmp_path)
    assert f.exists()
    cli._write_instance(tmp_path, 8123)
    cli._remove_instance(tmp_path)
    assert not f.exists()


def _serve_healthz(payload):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(payload).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_running_instance_detection(tmp_path):
    assert cli._running_instance(tmp_path) is None                  # no file
    ours = _serve_healthz({"ok": True, "app": "pdftoepub"})
    other = _serve_healthz({"ok": True})
    try:
        cli._write_instance(tmp_path, ours.server_address[1])
        assert cli._running_instance(tmp_path) == f"http://127.0.0.1:{ours.server_address[1]}"
        cli._write_instance(tmp_path, other.server_address[1])     # port reused by something else
        assert cli._running_instance(tmp_path) is None
    finally:
        ours.shutdown(); other.shutdown()
    cli._write_instance(tmp_path, ours.server_address[1])          # stale file, nothing listening
    assert cli._running_instance(tmp_path) is None


def test_launch_reuses_running_instance(monkeypatch, tmp_path, capsys):
    import webbrowser

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    monkeypatch.setattr(cli, "run_server", lambda *a, **k: pytest.fail("must not start a second server"))
    srv = _serve_healthz({"ok": True, "app": "pdftoepub"})
    try:
        cli._write_instance(tmp_path, srv.server_address[1])
        assert cli.main([]) == 0
    finally:
        srv.shutdown()
    assert opened == [f"http://127.0.0.1:{srv.server_address[1]}"]


def test_launch_starts_desktop_server_when_none_running(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cli, "run_server", lambda h, p, **k: seen.update(k) or 0)
    assert cli.main([]) == 0
    assert seen["desktop"] is True and seen["open_browser"] is True


def test_desktop_logging_writes_rotating_file(tmp_path):
    import logging

    names = ("pdftoepub", "uvicorn", "uvicorn.error", "uvicorn.access")
    before = {n: list(logging.getLogger(n).handlers) for n in names}
    try:
        cli._setup_desktop_logging(tmp_path)
        cli._say("hello desktop")
        h = [x for x in logging.getLogger("pdftoepub").handlers if x not in before["pdftoepub"]][0]
        h.flush()
        assert "hello desktop" in (tmp_path / "desktop.log").read_text()
        assert (h.maxBytes, h.backupCount) == (1_000_000, 2)
    finally:
        for n in names:
            lg = logging.getLogger(n)
            lg.handlers[:] = before[n]


def test_run_server_desktop_end_to_end(monkeypatch, tmp_path):
    """Real uvicorn: instance file appears, /api/shutdown stops the server, file removed, log written."""
    import threading
    import urllib.request

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    port = cli._free_port("127.0.0.1", 0)
    rc = []
    t = threading.Thread(target=lambda: rc.append(cli.run_server("127.0.0.1", port, desktop=True)), daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    end = time.time() + 15
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    assert json.loads((tmp_path / "desktop.json").read_text())["port"] == port
    req = urllib.request.Request(url + "/api/shutdown", method="POST", headers=HDR, data=b"")
    assert urllib.request.urlopen(req, timeout=5).status == 202
    t.join(10)
    assert rc == [0] and not t.is_alive()
    assert not (tmp_path / "desktop.json").exists()
    assert "stopped" in (tmp_path / "desktop.log").read_text()
