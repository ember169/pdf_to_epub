"""FastAPI application: `pdftoepub.web.app:app`."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .jobs import JOB_ID_RE, JobManager, parse_options, safe_filename
from .preview import CSP, render_preview

try:
    from importlib.metadata import version as _dist_version

    VERSION = _dist_version("pdftoepub")
except Exception:  # not installed (frozen / source tree)
    VERSION = "0.1.0"
LOCAL_CLIENTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
STATIC = Path(__file__).parent / "static"
CHUNK = 1024 * 1024
FRAMING_SLACK = 256 * 1024  # multipart boundaries + the options field on top of the file itself
MIN_FREE_BYTES = 256 * 1024 * 1024
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _TooLarge(Exception):
    pass


class UploadLimit:
    """Pure-ASGI guard: refuse oversized uploads from Content-Length, and count streamed bytes otherwise,
    so that a body is never fully spooled to disk before the size limit is looked at."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/jobs":
            return await self.app(scope, receive, send)
        too_big = JSONResponse({"detail": "File too large"}, status_code=413, headers={"Connection": "close"})
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.limit:
            return await too_big(scope, receive, send)
        seen = 0

        async def counting():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge
            return msg

        started = False

        async def tracking(msg):
            nonlocal started
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, counting, tracking)
        except BaseException as exc:  # BaseHTTPMiddleware downstream wraps errors in an ExceptionGroup
            if not (isinstance(exc, _TooLarge) or (isinstance(exc, BaseExceptionGroup) and exc.subgroup(_TooLarge))):
                raise
            if not started:
                await too_big(scope, receive, send)


log = logging.getLogger("pdftoepub.web")


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class ZipRequest(BaseModel):
    ids: list[str]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = JobManager(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.recover()
        manager.start_janitor()
        stop = threading.Event()
        if settings.desktop and settings.idle_exit_min:
            app.state.last_activity = time.monotonic()
            threading.Thread(target=idle_loop, args=(stop,), name="idle-exit", daemon=True).start()
        yield
        stop.set()
        manager.shutdown()

    app = FastAPI(title="pdftoepub", lifespan=lifespan)
    app.state.settings = settings
    app.state.jobs = manager
    app.state.request_exit = None  # set by the desktop launcher: callable that makes the server stop
    app.state.last_activity = time.monotonic()

    def idle_check() -> bool:
        """Desktop safety net: stop when nobody has talked to us for IDLE_EXIT_MIN and no job is pending."""
        if not settings.desktop or not settings.idle_exit_min or manager.pending():
            return False
        if time.monotonic() - app.state.last_activity < settings.idle_exit_min * 60:
            return False
        log.info("no activity for %s min and no job pending: exiting", settings.idle_exit_min)
        if app.state.request_exit:
            app.state.request_exit()
        return True

    app.state.idle_check = idle_check

    def idle_loop(stop: threading.Event) -> None:
        while not stop.wait(max(1.0, min(30.0, settings.idle_exit_min * 15))):
            if idle_check():
                return

    def auth(request: Request) -> None:
        if not settings.auth_token:
            return
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        # compare bytes: str inputs with non-ASCII characters make compare_digest raise
        given = token.strip().encode("latin-1", "replace")
        if scheme.lower() != "bearer" or not hmac.compare_digest(given, settings.auth_token.encode("utf-8")):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})

    def get_state(job_id: str) -> dict:
        st = manager.get(job_id)
        if st is None:
            raise HTTPException(404, "Job not found")
        return st

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "app": "pdftoepub", "version": VERSION}

    @app.get("/api/ping", dependencies=[Depends(auth)])
    def ping():
        return {"ok": True}  # the middleware below counts any request as activity; this one is the front's heartbeat

    @app.get("/api/config")
    def config():
        return {"auth_required": bool(settings.auth_token), "max_upload_mb": settings.max_upload_mb,
                "desktop": settings.desktop}

    @app.post("/api/shutdown", status_code=202, dependencies=[Depends(auth)])
    def shutdown(request: Request):
        # Desktop mode only; the Host/Origin guard below has already run. The custom header cannot be set by a
        # cross-origin page without a CORS preflight, which this app never answers.
        if not settings.desktop:
            raise HTTPException(404, "Not Found")
        if (request.client.host if request.client else "") not in LOCAL_CLIENTS:
            raise HTTPException(403, "Only this computer may stop the application")
        if request.headers.get("x-requested-with") != "pdftoepub":
            raise HTTPException(403, "Missing X-Requested-With header")
        n = manager.cancel_all()
        log.info("shutdown requested from the web UI (%d job(s) cancelled)", n)
        if app.state.request_exit:
            t = threading.Timer(0.5, app.state.request_exit)  # let the 202 reach the browser first
            t.daemon = True
            t.start()
        return {"ok": True}

    @app.post("/api/jobs", status_code=201, dependencies=[Depends(auth)])
    async def create_job(request: Request):
        if manager.pending() >= settings.max_queued_jobs:
            raise HTTPException(503, "The server is busy, please try again in a few minutes", headers={"Retry-After": "60"})
        tmp_dir = settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        limit = settings.max_upload_mb * 1024 * 1024
        if shutil.disk_usage(tmp_dir).free < max(MIN_FREE_BYTES, 2 * limit):
            raise HTTPException(507, "The server is out of disk space")
        form = await request.form(max_files=1, max_fields=4)
        try:
            file = form.get("file")
            if file is None or not hasattr(file, "read"):
                raise HTTPException(422, "Missing file")
            try:
                opts = parse_options(form.get("options") if isinstance(form.get("options"), str) else None)
            except ValueError as e:
                raise HTTPException(422, str(e))
            head = await file.read(5)
            if head != b"%PDF-":
                raise HTTPException(415, "The file is not a PDF")
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".upload", delete=False) as out:
                    tmp = Path(out.name)
                    out.write(head)
                    size = len(head)
                    while chunk := await file.read(CHUNK):
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit")
                        out.write(chunk)
                job_id = manager.create(tmp, file.filename or "book.pdf", opts)
            except BaseException:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
                raise
        finally:
            await form.close()
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(auth)])
    def job_status(job_id: str):
        return manager.public(get_state(job_id))

    @app.get("/api/jobs/{job_id}/events", dependencies=[Depends(auth)])
    async def job_events(job_id: str, request: Request):
        get_state(job_id)

        async def gen():
            last = None
            idle = 0
            while True:
                if await request.is_disconnected():
                    return
                st = manager.get(job_id)
                if st is None:
                    yield "event: gone\ndata: {}\n\n"
                    return
                pub = manager.public(st)
                if pub != last:
                    last, idle = pub, 0
                    yield f"event: progress\ndata: {json.dumps(pub)}\n\n"
                    if pub["status"] in ("done", "error"):
                        return
                else:
                    idle += 1
                    if idle % 15 == 0:
                        yield ": keepalive\n\n"
                await asyncio.get_running_loop().run_in_executor(None, manager.wait_change, 1.0)

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/download", dependencies=[Depends(auth)])
    def download(job_id: str):
        st = get_state(job_id)
        path = manager.dir(job_id) / "output.epub"  # type: ignore[operator]
        if st["status"] != "done" or not path.exists():
            raise HTTPException(409, "The EPUB is not ready")
        name = safe_filename(st.get("filename"), "book.epub")
        ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "book.epub"
        return FileResponse(
            path, media_type="application/epub+zip",
            headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, errors='replace')}"},
        )

    @app.get("/api/jobs/{job_id}/preview", dependencies=[Depends(auth)])
    def preview(job_id: str):
        st = get_state(job_id)
        path = manager.dir(job_id) / "output.epub"  # type: ignore[operator]
        if st["status"] != "done" or not path.exists():
            raise HTTPException(409, "The EPUB is not ready")
        try:
            html = render_preview(path)
        except Exception:
            html = None
        if html is None:
            raise HTTPException(404, "No preview available")
        return HTMLResponse(html, headers={"Content-Security-Policy": CSP + "; sandbox", "Cache-Control": "no-store"})

    @app.post("/api/jobs/zip", dependencies=[Depends(auth)])
    def download_zip(req: ZipRequest):
        ids = list(dict.fromkeys(req.ids))[:200]
        spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        used: set[str] = set()
        n = 0
        with zipfile.ZipFile(spool, "w", zipfile.ZIP_STORED) as z:
            for jid in ids:
                st = manager.get(jid) if JOB_ID_RE.match(jid) else None
                d = manager.dir(jid) if st else None
                if not st or d is None or st["status"] != "done" or not (d / "output.epub").exists():
                    continue
                name = st.get("filename") or "book.epub"
                stem, dot, ext = name.rpartition(".")
                k, cand = 1, name
                while cand.lower() in used:
                    k += 1
                    cand = f"{stem} ({k}).{ext}"
                used.add(cand.lower())
                z.write(d / "output.epub", cand)
                n += 1
        if n == 0:
            spool.close()
            raise HTTPException(404, "No finished jobs")
        spool.seek(0)

        def chunks():
            try:
                while data := spool.read(CHUNK):
                    yield data
            finally:
                spool.close()

        return StreamingResponse(chunks(), media_type="application/zip",
                                 headers={"Content-Disposition": 'attachment; filename="epubs.zip"'})

    @app.delete("/api/jobs/{job_id}", status_code=204, dependencies=[Depends(auth)])
    def delete_job(job_id: str):
        if not manager.delete(job_id):
            raise HTTPException(404, "Job not found")

    explicit_hosts = set(settings.allowed_hosts)
    allowed_hosts = LOOPBACK_HOSTS | explicit_hosts
    # With a bearer token configured, ambient-browser attacks (DNS rebinding, CSRF) cannot succeed because the
    # token is not sent automatically, so hostnames are then only restricted when ALLOWED_HOSTS is set.
    enforce_host = (not settings.auth_token) or bool(explicit_hosts)

    @app.middleware("http")
    async def host_and_origin_guard(request: Request, call_next):
        if "*" not in explicit_hosts and enforce_host:
            host = _host_only(request.headers.get("host", ""))
            if host not in allowed_hosts:
                return JSONResponse({"detail": "Invalid host header"}, status_code=400)
            if request.method in UNSAFE_METHODS:
                if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                    return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
                for hdr in ("origin", "referer"):
                    val = request.headers.get(hdr)
                    if val:
                        netloc = urlsplit(val).netloc.lower()
                        if netloc != request.headers.get("host", "").lower() and _host_only(netloc) not in explicit_hosts:
                            return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
                        break
        return await call_next(request)

    @app.middleware("http")
    async def activity(request: Request, call_next):
        app.state.last_activity = time.monotonic()
        try:
            return await call_next(request)
        finally:
            app.state.last_activity = time.monotonic()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    app.add_middleware(UploadLimit, limit=settings.max_upload_mb * 1024 * 1024 + FRAMING_SLACK)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
