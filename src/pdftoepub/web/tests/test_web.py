import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from pdftoepub.web.app import create_app
from pdftoepub.web.config import Settings



def _real_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, 760, "Chapter One")
    c.setFont("Helvetica", 11)
    for i in range(12):
        c.drawString(72, 720 - i * 16, "The quick brown fox jumps over the lazy dog, again and again.")
    c.showPage()
    c.setFont("Helvetica", 11)
    for i in range(12):
        c.drawString(72, 760 - i * 16, "Second page body text continues the paragraph here.")
    c.save()
    return buf.getvalue()


PDF = _real_pdf()
FAKE_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"  # magic bytes only, not parseable


def make(tmp_path, **kw):
    kw.setdefault("allowed_hosts", ("testserver",))
    s = Settings(data_dir=tmp_path, janitor_interval_s=3600, **kw)
    return create_app(s)


def wait_done(c, jid, headers=None, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/jobs/{jid}", headers=headers).json()
        if st["status"] in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("timeout")


@pytest.fixture
def client(tmp_path):
    with TestClient(make(tmp_path)) as c:
        yield c


def post(c, data=PDF, name="My Book.pdf", options=None, headers=None):
    form = {"options": json.dumps(options)} if options is not None else {}
    return c.post("/api/jobs", files={"file": (name, io.BytesIO(data), "application/pdf")}, data=form, headers=headers)


def test_healthz_and_front(client):
    assert client.get("/healthz").json()["ok"] is True
    assert "PDF" in client.get("/").text


def test_upload_poll_download(client):
    r = post(client, options={"title": "Mon / Livre", "ocr": "off"})
    assert r.status_code == 201
    jid = r.json()["id"]
    st = wait_done(client, jid)
    assert st["status"] == "done", st
    d = client.get(f"/api/jobs/{jid}/download")
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/epub+zip"
    assert "Mon" in d.headers["content-disposition"] and "/" not in d.headers["content-disposition"].split("filename=")[1].split(";")[0]
    assert zipfile.ZipFile(io.BytesIO(d.content)).namelist()[0] == "mimetype"


def test_sse_stream(client):
    jid = post(client).json()["id"]
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
    assert events[-1]["status"] == "done"


def test_non_pdf_rejected(client):
    assert post(client, data=b"hello world").status_code == 415


def test_oversize(tmp_path):
    with TestClient(make(tmp_path, max_upload_mb=1)) as c:
        assert post(c, data=PDF + b"0" * (1024 * 1024 + 1)).status_code == 413
        assert not list((tmp_path / "tmp").glob("*"))


def test_bad_options(client):
    assert post(client, options={"ocr": "bogus"}).status_code == 422
    assert post(client, options={"ocr_langs": "fra; rm -rf"}).status_code == 422


def test_unknown_and_traversal(client):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/..%2f..%2fetc").status_code == 404


def test_download_before_done_and_delete(client):
    jid = post(client).json()["id"]
    wait_done(client, jid)
    assert client.delete(f"/api/jobs/{jid}").status_code == 204
    assert client.get(f"/api/jobs/{jid}").status_code == 404
    assert client.delete(f"/api/jobs/{jid}").status_code == 404


def test_auth(tmp_path):
    with TestClient(make(tmp_path, auth_token="s3cret")) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/").status_code == 200
        assert post(c).status_code == 401
        assert post(c, headers={"Authorization": "Bearer nope"}).status_code == 401
        h = {"Authorization": "Bearer s3cret"}
        jid = post(c, headers=h).json()["id"]
        assert c.get(f"/api/jobs/{jid}").status_code == 401
        assert wait_done(c, jid, h)["status"] == "done"
        assert c.get(f"/api/jobs/{jid}/download", headers=h).status_code == 200


def test_ttl_cleanup_and_persistence(tmp_path):
    app = make(tmp_path, job_ttl_hours=1)
    with TestClient(app) as c:
        jid = post(c).json()["id"]
        wait_done(c, jid)
        assert app.state.jobs.cleanup() == 0
        assert app.state.jobs.cleanup(now=time.time() + 7200) == 1
        assert c.get(f"/api/jobs/{jid}").status_code == 404
    # state survives a restart
    with TestClient(make(tmp_path)) as c1:
        jid = post(c1).json()["id"]
        wait_done(c1, jid)
    with TestClient(make(tmp_path)) as c2:
        assert c2.get(f"/api/jobs/{jid}").json()["status"] == "done"
        assert c2.get(f"/api/jobs/{jid}/download").status_code == 200


def test_interrupted_job_marked_error(tmp_path):
    app = make(tmp_path)
    m = app.state.jobs
    d = m.root / ("a" * 32)
    d.mkdir(parents=True)
    m._write(d, {"id": "a" * 32, "status": "running", "created": time.time(), "updated": time.time()})
    with TestClient(app) as c:
        st = c.get(f"/api/jobs/{'a' * 32}").json()
        assert st["status"] == "error"


def test_conversion_error_is_user_safe(client, monkeypatch):
    from pdftoepub import ConversionError
    import pdftoepub.web.jobs as jobs

    def boom(*a, **k):
        raise ConversionError("PDF is encrypted")

    monkeypatch.setattr(jobs, "convert_isolated", boom)
    jid = post(client).json()["id"]
    st = wait_done(client, jid)
    assert st["status"] == "error" and st["error"] == "PDF is encrypted"

    monkeypatch.setattr(jobs, "convert_isolated", lambda *a, **k: 1 / 0)
    st = wait_done(client, post(client).json()["id"])
    assert st["error"] == "Internal error during conversion"


def test_fake_pdf_fails_with_safe_message(client):
    st = wait_done(client, post(client, data=FAKE_PDF).json()["id"])
    assert st["status"] == "error"
    assert st["error"] and "Traceback" not in st["error"] and "/" not in st["error"]


def test_zip_download(client):
    ids = [post(client, name=f"b{i}.pdf").json()["id"] for i in range(2)]
    for i in ids:
        wait_done(client, i)
    r = client.post("/api/jobs/zip", json={"ids": ids + ["../x", "0" * 32]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and len(set(names)) == 2 and all(n.endswith(".epub") for n in names)
    assert client.post("/api/jobs/zip", json={"ids": ["0" * 32]}).status_code == 404


def test_preview_is_sandboxed_html(client):
    jid = post(client).json()["id"]
    wait_done(client, jid)
    r = client.get(f"/api/jobs/{jid}/preview")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"]
    assert "<script" not in r.text.lower()
    assert "Chapter One" in r.text or "quick brown fox" in r.text


def test_preview_strips_active_content(tmp_path):
    from pdftoepub.web.preview import render_preview

    ns = 'xmlns="http://www.w3.org/1999/xhtml"'
    chapter = (f'<html {ns}><head><title>T</title><script>alert(1)</script></head><body>'
               '<p onclick="x()" style="color:red">' + "text " * 80 + '</p><script>evil()</script>'
               '<a href="javascript:alert(1)">bad</a><a href="https://example.org">ok</a>'
               '<img src="../../etc/passwd" onerror="x()"/><iframe src="http://x"></iframe></body></html>')
    opf = ('<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest>'
           '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c"/></spine></package>')
    epub = tmp_path / "x.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/c.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/c.opf", opf)
        z.writestr("OEBPS/c.xhtml", chapter)
    html = render_preview(epub)
    low = html.lower()
    for bad in ("<script", "onclick", "onerror", "javascript:", "<iframe", "color:red", "evil"):
        assert bad not in low
    assert 'href="https://example.org"' in html and "text text" in html


def test_error_and_warning_classification():
    from pdftoepub.web.jobs import classify_error, summarise_warnings

    assert classify_error("This PDF is password-protected; remove it") == "encrypted"
    assert classify_error("This file could not be read as a PDF.") == "corrupt"
    assert classify_error("No text could be extracted from this PDF. If it is a scan") == "no_text"
    assert classify_error("???") == "failed"
    notes = summarise_warnings(["Page 3 could not be read (X) and was skipped.", "Page 4 could not be read (X) and was skipped.",
                                "5 page(s) have no usable text layer and OCR is unavailable; kept", "weird"], ocr_pages=12)
    by = {n["code"]: n for n in notes}
    assert by["ocr_used"]["n"] == 12 and by["page_skipped"]["n"] == 2 and by["ocr_unavailable"]["n"] == 5 and by["other"]["text"] == "weird"


def test_error_code_exposed(client, monkeypatch):
    from pdftoepub import ConversionError
    import pdftoepub.web.jobs as jobs

    def boom(*a, **k):
        raise ConversionError("This PDF is password-protected; remove the password and try again.")

    monkeypatch.setattr(jobs, "convert_isolated", boom)
    st = wait_done(client, post(client).json()["id"])
    assert st["error_code"] == "encrypted"


def test_status_has_stats(client):
    st = wait_done(client, post(client).json()["id"])
    assert st["page_count"] == 2 and isinstance(st["notes"], list)


def test_static_assets_served_locally(client):
    html = client.get("/").text
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    for f in ("app.js", "i18n.js", "style.css"):
        assert client.get("/" + f).status_code == 200
