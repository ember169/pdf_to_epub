import io
import json
import os
import shutil
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from pdftoepub.web.jobs import clean_text, parse_options, safe_filename
from pdftoepub.web.tests.test_web import PDF, make, post, wait_done


def fds() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.mark.skipif(sys.platform == "win32", reason="/dev/fd")
def test_bad_uploads_do_not_leak_fds(tmp_path):
    with TestClient(make(tmp_path)) as c:
        post(c, data=b"not a pdf")  # warm up
        before = fds()
        for _ in range(60):
            assert post(c, data=b"nope nope").status_code == 415
            assert post(c, options={"ocr": "bogus"}).status_code == 422
        assert fds() - before < 10
        assert not list((tmp_path / "tmp").glob("*"))


def test_oversize_rejected_from_content_length_without_spooling(tmp_path):
    with TestClient(make(tmp_path, max_upload_mb=1)) as c:
        r = post(c, data=PDF + b"0" * (3 * 1024 * 1024))
        assert r.status_code == 413
        assert not list((tmp_path / "tmp").glob("*"))


def test_oversize_streamed_without_content_length(tmp_path, monkeypatch):
    spooled = []
    import starlette.formparsers as fp

    orig = fp.MultiPartParser.__init__

    def spy(self, *a, **k):
        orig(self, *a, **k)
        spooled.append(self)

    monkeypatch.setattr(fp.MultiPartParser, "__init__", spy)
    boundary = "XBOUNDARY"

    def body():
        yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n"
               "Content-Type: application/pdf\r\n\r\n").encode() + PDF
        for _ in range(40):  # 40 MB, never declared
            yield b"0" * (1024 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()

    with TestClient(make(tmp_path, max_upload_mb=1)) as c:
        r = c.post("/api/jobs", content=body(), headers={"content-type": f"multipart/form-data; boundary={boundary}"})
        assert r.status_code == 413
        assert not list((tmp_path / "tmp").glob("*"))


def test_part_count_capped(tmp_path):
    with TestClient(make(tmp_path)) as c:
        files = [("file", (f"{i}.pdf", io.BytesIO(PDF), "application/pdf")) for i in range(5)]
        assert c.post("/api/jobs", files=files).status_code == 400
        data = {f"f{i}": "x" for i in range(10)}
        assert c.post("/api/jobs", files={"file": ("a.pdf", io.BytesIO(PDF))}, data=data).status_code == 400


def test_host_header_rebinding_blocked(tmp_path):
    with TestClient(make(tmp_path, allowed_hosts=())) as c:  # loopback names only
        for host in ("evil.example", "evil.example:8000", "127.0.0.1.evil.example"):
            assert c.get("/healthz", headers={"host": host}).status_code == 400
            assert post(c, headers={"host": host}).status_code == 400
        for host in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST"):
            assert c.get("/healthz", headers={"host": host}).status_code == 200


def test_cross_origin_post_blocked_same_origin_ok(tmp_path):
    with TestClient(make(tmp_path, allowed_hosts=())) as c:
        h = {"host": "127.0.0.1:8000"}
        assert post(c, headers={**h, "origin": "http://evil.example"}).status_code == 403
        assert post(c, headers={**h, "origin": "null"}).status_code == 403
        assert post(c, headers={**h, "referer": "http://evil.example/x"}).status_code == 403
        assert post(c, headers={**h, "sec-fetch-site": "cross-site"}).status_code == 403
        assert post(c, headers={**h, "origin": "http://localhost:8000"}).status_code == 403  # other origin, same machine
        assert c.delete("/api/jobs/" + "0" * 32, headers={**h, "origin": "http://evil.example"}).status_code == 403
        ok = post(c, headers={**h, "origin": "http://127.0.0.1:8000"})
        assert ok.status_code == 201
        assert post(c, headers=h).status_code == 201  # curl-style, no Origin


def test_allowed_hosts_env_for_reverse_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "Books.Example.com, other.example")
    from pdftoepub.web.config import Settings

    s = Settings.from_env()
    assert s.allowed_hosts == ("books.example.com", "other.example")
    with TestClient(make(tmp_path, allowed_hosts=s.allowed_hosts)) as c:
        h = {"host": "books.example.com", "origin": "https://books.example.com"}
        assert post(c, headers=h).status_code == 201
        assert post(c, headers={"host": "books.example.com", "origin": "https://evil.example"}).status_code == 403


def test_queue_cap_returns_503(tmp_path, monkeypatch):
    import pdftoepub.web.jobs as jobs

    gate = threading.Event()
    monkeypatch.setattr(jobs, "convert_isolated", lambda *a, **k: gate.wait(10) or (_ for _ in ()).throw(RuntimeError("x")))
    with TestClient(make(tmp_path, max_concurrent_jobs=1, max_queued_jobs=2)) as c:
        assert post(c).status_code == 201
        assert post(c).status_code == 201
        r = post(c)
        assert r.status_code == 503 and r.headers["retry-after"]
        gate.set()
        time.sleep(0.5)
        assert post(c).status_code == 201  # capacity is released when jobs finish


def test_disk_space_checked_before_accepting(tmp_path, monkeypatch):
    import pdftoepub.web.app as appmod

    monkeypatch.setattr(appmod.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    with TestClient(make(tmp_path)) as c:
        assert post(c).status_code == 507


def test_janitor_sweeps_stale_tmp_uploads(tmp_path):
    app = make(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    old, fresh = tmp / "old.upload", tmp / "fresh.upload"
    old.write_bytes(b"x"); fresh.write_bytes(b"x")
    os.utime(old, (time.time() - 7200,) * 2)
    app.state.jobs.cleanup()
    assert not old.exists() and fresh.exists()


def test_non_ascii_bearer_is_401_not_500(tmp_path):
    with TestClient(make(tmp_path, auth_token="s3cret"), raise_server_exceptions=False) as c:
        for raw in ("Bearer é".encode("utf-8"), "Bearer \xff\xfe".encode("latin-1"), b"Bearer \xe2\x82\xac"):
            r = c.get("/api/jobs/" + "0" * 32, headers={"authorization": raw})
            assert r.status_code == 401
    with TestClient(make(tmp_path, auth_token="clé€"), raise_server_exceptions=False) as c:
        assert post(c, headers={"authorization": "Bearer clé€".encode("utf-8")}).status_code == 201


def test_clean_text_and_options():
    assert clean_text("\ud800") is None
    assert clean_text("\x00\x07\x1b") is None
    assert clean_text("  Hel\ud800lo\x00  world‮ ") == "Hello world"
    assert parse_options(json.dumps({"title": "\ud800", "author": "\x01"})).title is None
    assert parse_options('{"title": "\\ud800x"}').title == "x"
    assert safe_filename("\ud800\x00") == "book"


def test_surrogate_title_end_to_end(tmp_path):
    with TestClient(make(tmp_path)) as c:
        r = c.post("/api/jobs", files={"file": ("\ud800bad.pdf".encode("utf-8", "surrogatepass").decode("latin-1"), io.BytesIO(PDF))},
                   data={"options": '{"title": "\\ud800", "author": "\\u0000\\u0001"}'})
        assert r.status_code == 201
        st = wait_done(c, r.json()["id"])
        assert st["status"] == "done", st
        d = c.get(f"/api/jobs/{r.json()['id']}/download")
        assert d.status_code == 200


def test_download_header_robust_to_bad_stored_filename(tmp_path):
    app = make(tmp_path)
    with TestClient(app) as c:
        jid = post(c).json()["id"]
        wait_done(c, jid)
        m = app.state.jobs
        st = m.get(jid)
        m._update(jid, filename="\ud800évil\r\n.epub")
    with TestClient(app) as c:
        assert c.get(f"/api/jobs/{jid}/download").status_code == 200


def test_cli_title_sanitised(tmp_path):
    from pdftoepub import cli

    src = tmp_path / "a.pdf"
    src.write_bytes(PDF)
    out = tmp_path / "a.epub"
    assert cli.main([str(src), "-o", str(out), "-q", "--title", "\udcff\x00", "--author", "\x01"]) == 0


def _big_pdf(pages: int = 400) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for p in range(pages):
        c.setFont("Helvetica", 10)
        for i in range(45):
            c.drawString(60, 800 - i * 16, f"Page {p} line {i} lorem ipsum dolor sit amet consectetur adipiscing elit.")
        c.showPage()
    c.save()
    return buf.getvalue()


def _convert_children():
    import multiprocessing as mp
    return [p for p in mp.active_children() if p.name == "pdftoepub-convert"]


def test_timeout_breach_is_friendly_error(tmp_path):
    with TestClient(make(tmp_path, job_timeout_s=0.05)) as c:
        st = wait_done(c, post(c).json()["id"], timeout=30)
    assert st["status"] == "error" and st["error_code"] == "timeout"
    assert "took longer than" in st["error"] and "Traceback" not in st["error"]


def test_page_limit_breach(tmp_path):
    with TestClient(make(tmp_path, max_pages=1)) as c:
        st = wait_done(c, post(c).json()["id"], timeout=30)
    assert st["status"] == "error" and st["error_code"] == "too_many_pages"


def test_delete_running_job_kills_child(tmp_path):
    with TestClient(make(tmp_path, job_timeout_s=120)) as c:
        jid = post(c, data=_big_pdf(600)).json()["id"]
        end = time.time() + 30
        while time.time() < end and c.get(f"/api/jobs/{jid}").json()["stage"] in ("queued", "start"):
            time.sleep(0.05)
        assert _convert_children(), "child process should be running"
        assert c.delete(f"/api/jobs/{jid}").status_code == 204
        end = time.time() + 15
        while time.time() < end and _convert_children():
            time.sleep(0.1)
        assert not _convert_children()
        assert c.get(f"/api/jobs/{jid}").status_code == 404


def test_progress_streams_over_sse_from_isolated_child(tmp_path):
    with TestClient(make(tmp_path)) as c:
        jid = post(c, data=_big_pdf(60)).json()["id"]
        with c.stream("GET", f"/api/jobs/{jid}/events") as r:
            body = "".join(r.iter_text())
    events = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
    running = [e for e in events if e["status"] == "running" and e["total_pages"]]
    assert running, events
    assert events[-1]["status"] == "done" and events[-1]["page_count"] == 60


def test_cli_isolated_flags(tmp_path):
    from pdftoepub import cli

    src = tmp_path / "a.pdf"
    src.write_bytes(PDF)
    assert cli.main([str(src), "-o", str(tmp_path / "a.epub"), "-q", "--timeout", "120", "--max-pages", "10"]) == 0
    assert cli.main([str(src), "-o", str(tmp_path / "b.epub"), "-q", "--max-pages", "1"]) == 1
