"""Disk-backed job manager. All state lives in DATA_DIR/jobs/<id>/ so it survives restarts."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .. import ConversionError, ConvertOptions, ProgressEvent
from ..core.isolation import convert_isolated
from .config import Settings

log = logging.getLogger("pdftoepub.web")

TMP_MAX_AGE_S = 3600
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
OCR_MODES = {"auto", "off", "force"}
OCR_LANGS_RE = re.compile(r"^[A-Za-z0-9_]{2,16}(\+[A-Za-z0-9_]{2,16}){0,7}$")
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")


_BAD_CHARS = re.compile(r"[\ud800-\udfff\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def clean_text(value: str | None, limit: int = 300) -> str | None:
    """Strip lone surrogates / control / bidi-override chars, collapse whitespace; None when nothing is left."""
    if not value:
        return None
    v = " ".join(_BAD_CHARS.sub("", value).split())[:limit]
    return v or None


def parse_options(raw: str | None) -> ConvertOptions:
    """Validate client-supplied options JSON into ConvertOptions. Raises ValueError."""
    if not raw or not raw.strip():
        return ConvertOptions()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("options is not valid JSON") from e
    if not isinstance(data, dict):
        raise ValueError("options must be a JSON object")
    opts = ConvertOptions()

    def text(key: str, limit: int = 300) -> str | None:
        v = data.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"{key} must be a string")
        return clean_text(v, limit)

    opts.title = text("title")
    opts.author = text("author")
    lang = text("language", 20)
    if lang and not LANG_RE.match(lang):
        raise ValueError("invalid language")
    opts.language = lang
    if "ocr" in data:
        if data["ocr"] not in OCR_MODES:
            raise ValueError("ocr must be auto, off or force")
        opts.ocr = data["ocr"]
    langs = text("ocr_langs", 100)
    if langs:
        if not OCR_LANGS_RE.match(langs):
            raise ValueError("invalid ocr_langs")
        opts.ocr_langs = langs
    for key in ("drop_headers_footers", "detect_columns"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError(f"{key} must be a boolean")
            setattr(opts, key, data[key])
    if "image_mode" in data:
        if data["image_mode"] not in ("inline", "none"):
            raise ValueError("image_mode must be inline or none")
        opts.image_mode = data["image_mode"]
    return opts


_ERROR_PATTERNS = [
    ("encrypted", re.compile(r"password-protected|encrypted", re.I)),
    ("no_text", re.compile(r"No text could be extracted", re.I)),
    ("empty", re.compile(r"No readable text|no text or images|no pages", re.I)),
    ("timeout", re.compile(r"took longer than", re.I)),
    ("too_many_pages", re.compile(r"limit is \d+", re.I)),
    ("too_complex", re.compile(r"too large to convert|memory|stopped by the system|stopped unexpectedly", re.I)),
    ("corrupt", re.compile(r"could not be read|not a PDF|could not be found", re.I)),
]
_WARNING_PATTERNS = [
    ("ocr_unavailable", re.compile(r"(\d+) page\(s\) have no usable text layer and OCR is unavailable")),
    ("ocr_off", re.compile(r"(\d+) page\(s\) have no usable text layer and OCR is turned off")),
    ("page_skipped", re.compile(r"Page \d+ could not be read|layout analysis failed", re.I)),
    ("ocr_failed", re.compile(r"OCR failed", re.I)),
    ("image_failed", re.compile(r"image could not be extracted", re.I)),
]


def classify_error(msg: str) -> str:
    for code, rx in _ERROR_PATTERNS:
        if rx.search(msg):
            return code
    return "failed"


def summarise_warnings(warnings: list[str], ocr_pages: int = 0) -> list[dict[str, Any]]:
    """Group core warnings into language-neutral notes {code, n, text}; the front localises by code."""
    notes: list[dict[str, Any]] = []
    if ocr_pages:
        notes.append({"code": "ocr_used", "n": ocr_pages, "text": f"{ocr_pages} page(s) were read with OCR"})
    counts: dict[str, dict[str, Any]] = {}
    for w in warnings:
        for code, rx in _WARNING_PATTERNS:
            m = rx.search(w)
            if m:
                n = int(m.group(1)) if m.groups() else 1
                if code in counts:
                    counts[code]["n"] += n
                else:
                    counts[code] = {"code": code, "n": n, "text": w}
                break
        else:
            notes.append({"code": "other", "n": 1, "text": w})
    return notes + list(counts.values())


def safe_filename(title: str | None, fallback: str = "book") -> str:
    """ASCII-safe-ish file stem derived from a title (no path separators/control chars)."""
    s = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]+", " ", _BAD_CHARS.sub("", title or ""))
    s = " ".join(s.split()).strip(". ")[:120]
    return s or fallback


class _Cancelled(Exception):
    """Raised from the progress callback to make convert_isolated kill its child process."""


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir / "jobs"
        self.pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="convert")
        self._lock = threading.Lock()
        self._cond = threading.Condition()  # notifies SSE listeners
        self._stop = threading.Event()
        self._pending = 0
        self._cancelled: set[str] = set()
        self._janitor: threading.Thread | None = None

    def pending(self) -> int:
        return self._pending

    def _submit(self, job_id: str) -> None:
        with self._lock:
            self._pending += 1
        self.pool.submit(self._run, job_id)

    # ---- paths / state -------------------------------------------------
    def dir(self, job_id: str) -> Path | None:
        if not JOB_ID_RE.match(job_id):
            return None
        d = self.root / job_id
        return d if d.is_dir() else None

    def _write(self, d: Path, state: dict[str, Any]) -> None:
        tmp = d / "state.json.tmp"
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, d / "state.json")

    def get(self, job_id: str) -> dict[str, Any] | None:
        d = self.dir(job_id)
        if d is None:
            return None
        try:
            return json.loads((d / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            d = self.dir(job_id)
            st = self.get(job_id)
            if d is None or st is None:
                return
            st.update(changes)
            st["updated"] = time.time()
            self._write(d, st)
        with self._cond:
            self._cond.notify_all()

    def public(self, st: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "status", "stage", "page", "total_pages", "message", "warnings", "notes", "error", "error_code",
                "title", "filename", "page_count", "chapter_count", "ocr_pages")
        return {k: st.get(k) for k in keys}

    # ---- lifecycle -----------------------------------------------------
    def create(self, pdf_tmp: Path, original_name: str, options: ConvertOptions) -> str:
        job_id = uuid.uuid4().hex
        d = self.root / job_id
        d.mkdir(parents=True)
        os.replace(pdf_tmp, d / "input.pdf")
        st = {
            "id": job_id, "status": "queued", "stage": "queued", "page": 0, "total_pages": 0,
            "message": "", "warnings": [], "error": None, "title": None, "filename": None,
            "source_name": safe_filename(Path(original_name.replace("\\", "/")).stem),
            "options": asdict(options), "created": time.time(), "updated": time.time(),
        }
        self._write(d, st)
        self._submit(job_id)
        return job_id

    def _run(self, job_id: str) -> None:
        d = self.dir(job_id)
        st = self.get(job_id)
        if d is None or st is None:  # deleted while still queued
            with self._lock:
                self._pending = max(0, self._pending - 1)
                self._cancelled.discard(job_id)
            return
        self._update(job_id, status="running", stage="start")

        def progress(ev: ProgressEvent) -> None:
            if job_id in self._cancelled:
                raise _Cancelled
            self._update(job_id, stage=ev.stage, page=ev.page, total_pages=ev.total_pages, message=clean_text(ev.message, 200) or "")

        try:
            opts = ConvertOptions(**st["options"])
            tmp_out = d / "output.epub.part"
            res = convert_isolated(
                d / "input.pdf", tmp_out, opts, progress, timeout_s=self.settings.job_timeout_s,
                max_mem_mb=self.settings.job_max_mem_mb, max_pages=self.settings.max_pages,
            )
            os.replace(res.epub_path if Path(res.epub_path).exists() else tmp_out, d / "output.epub")
            warnings = [clean_text(w, 500) or "" for w in res.warnings]
            title = clean_text(res.title) or st["source_name"]
            self._update(
                job_id, status="done", stage="done", page=res.page_count, total_pages=res.page_count,
                warnings=warnings, notes=summarise_warnings(warnings, res.ocr_pages),
                page_count=res.page_count, chapter_count=res.chapter_count, ocr_pages=res.ocr_pages, title=title, filename=safe_filename(title, st["source_name"]) + ".epub",
            )
        except _Cancelled:
            pass  # deleted while running: the child has been killed, nothing left to report
        except ConversionError as e:
            msg = clean_text(str(e), 500) or "Conversion failed"
            self._update(job_id, status="error", error=msg, error_code=classify_error(msg))
        except Exception:  # never leak internals to the client
            log.exception("job %s failed", job_id)
            self._update(job_id, status="error", error="Internal error during conversion", error_code="internal")
        finally:
            with self._lock:
                self._pending = max(0, self._pending - 1)
                self._cancelled.discard(job_id)
            try:
                (d / "input.pdf").unlink(missing_ok=True)
                (d / "output.epub.part").unlink(missing_ok=True)
            except OSError:
                pass

    def delete(self, job_id: str) -> bool:
        d = self.dir(job_id)
        if d is None:
            return False
        with self._lock:
            st = self.get(job_id)
            if st and st.get("status") in ("queued", "running"):
                self._cancelled.add(job_id)  # next progress event (or the timeout) kills the child
        shutil.rmtree(d, ignore_errors=True)
        with self._cond:
            self._cond.notify_all()
        return True

    def recover(self) -> None:
        """After a restart: requeue queued jobs whose input remains; fail interrupted ones."""
        self.root.mkdir(parents=True, exist_ok=True)
        for d in self.root.iterdir():
            st = self.get(d.name) if d.is_dir() else None
            if not st or st.get("status") not in ("queued", "running"):
                continue
            if st["status"] == "queued" and (d / "input.pdf").exists():
                self._submit(d.name)
            else:
                self._update(d.name, status="error", error="Interrupted by a server restart", error_code="interrupted")

    def cleanup(self, now: float | None = None) -> int:
        now = now or time.time()
        ttl = self.settings.job_ttl_hours * 3600
        n = 0
        tmp = self.settings.data_dir / "tmp"
        if tmp.is_dir():
            for f in tmp.iterdir():  # abandoned uploads
                try:
                    if now - f.stat().st_mtime > TMP_MAX_AGE_S:
                        f.unlink()
                except OSError:
                    pass
        if not self.root.is_dir():
            return 0
        for d in list(self.root.iterdir()):
            if not d.is_dir():
                continue
            st = self.get(d.name)
            try:
                age_ref = (st or {}).get("updated") or d.stat().st_mtime
            except OSError:
                continue
            busy = st and st.get("status") in ("queued", "running")
            if not busy and now - age_ref > ttl:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        return n

    def start_janitor(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self.settings.janitor_interval_s):
                try:
                    self.cleanup()
                except Exception:
                    log.exception("janitor failed")

        self.cleanup()
        self._janitor = threading.Thread(target=loop, name="janitor", daemon=True)
        self._janitor.start()

    def shutdown(self) -> None:
        self._stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def wait_change(self, timeout: float) -> None:
        with self._cond:
            self._cond.wait(timeout)
