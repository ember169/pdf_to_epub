"""Command line: `pdftoepub in.pdf -o out.epub` and `pdftoepub serve`."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import ConversionError, ConvertOptions, ProgressEvent, convert


def _convert_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdftoepub", description="Convert a PDF to a reflowable EPUB 3. "
                                "Use `pdftoepub serve` to run the web interface.")
    p.add_argument("input", type=Path, help="input PDF")
    p.add_argument("-o", "--output", type=Path, help="output EPUB (default: input with .epub)")
    p.add_argument("--title")
    p.add_argument("--author")
    p.add_argument("--language", help="BCP47 code, e.g. fr (default: detect)")
    p.add_argument("--ocr", choices=["auto", "off", "force"], default="auto")
    p.add_argument("--ocr-langs", default="fra+eng", help="tesseract languages (default: fra+eng)")
    p.add_argument("--keep-headers-footers", action="store_true", help="do not strip running headers/footers")
    p.add_argument("--no-columns", action="store_true", help="disable multi-column detection")
    p.add_argument("--no-images", action="store_true", help="omit images")
    p.add_argument("--timeout", type=float, metavar="SECONDS", help="stop the conversion after this long (runs it in a child process)")
    p.add_argument("--max-mem", type=int, metavar="MB", help="stop if the conversion needs more memory than this (child process)")
    p.add_argument("--max-pages", type=int, metavar="N", help="refuse documents with more pages than this")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


PORT = 8000
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _free_port(host: str, preferred: int = PORT) -> int:
    """Preferred port if free, else any free port chosen by the OS."""
    import socket

    for port in (preferred, 0):
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("no free port available")


def _default_data_dir() -> str:
    import os

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return str(base / "pdftoepub")


def run_server(host: str, port: int, *, open_browser: bool = False, reload: bool = False) -> int:
    import threading
    import webbrowser

    import uvicorn

    if host not in LOOPBACK:
        import os

        print("WARNING: listening on a non-loopback address; anyone who can reach it can use this server. "
              "Set AUTH_TOKEN to require a bearer token."
              + ("" if os.environ.get("AUTH_TOKEN") else " (AUTH_TOKEN is not set!)"), file=sys.stderr)
    if reload:
        uvicorn.run("pdftoepub.web.app:app", host=host, port=port, reload=True)
        return 0
    from .web.app import app

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}"
    if open_browser:
        def opener() -> None:
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if server.started:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

        threading.Thread(target=opener, daemon=True).start()
    print(f"pdftoepub tourne sur {url} - fermez cette fen\u00eatre (ou Ctrl+C) pour quitter\n"
          f"pdftoepub is running at {url} - close this window (or press Ctrl+C) to quit", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


def _serve(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pdftoepub serve", description="Run the web interface.")
    p.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (this computer only); use 0.0.0.0 to expose on the network")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--data-dir", help="override DATA_DIR")
    p.add_argument("--open", action="store_true", help="open the browser when ready")
    p.add_argument("--reload", action="store_true")
    a = p.parse_args(argv)
    if a.data_dir:
        import os
        os.environ["DATA_DIR"] = a.data_dir
    return run_server(a.host, a.port, open_browser=a.open, reload=a.reload)


def _launch_ui() -> int:
    """No arguments (double-click): local web UI on a free loopback port, browser opened."""
    import os

    os.environ.setdefault("DATA_DIR", _default_data_dir())
    host = "127.0.0.1"
    try:
        return run_server(host, _free_port(host), open_browser=True)
    except BaseException as e:  # keep the console open so the user can read what went wrong
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        print(f"\npdftoepub: {type(e).__name__}: {e}", file=sys.stderr)
        if sys.platform == "win32" and sys.stdin is not None:
            try:
                input("Appuyez sur Entr\u00e9e pour fermer / Press Enter to close...")
            except EOFError:
                pass
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _launch_ui()
    if argv[0] == "serve":
        return _serve(argv[1:])
    a = _convert_parser().parse_args(argv)
    if not a.input.is_file():
        print(f"pdftoepub: no such file: {a.input}", file=sys.stderr)
        return 2
    from .web.jobs import clean_text

    out = a.output or a.input.with_suffix(".epub")
    opts = ConvertOptions(
        title=clean_text(a.title), author=clean_text(a.author), language=a.language, ocr=a.ocr, ocr_langs=a.ocr_langs,
        drop_headers_footers=not a.keep_headers_footers, detect_columns=not a.no_columns,
        image_mode="none" if a.no_images else "inline",
    )

    def progress(ev: ProgressEvent) -> None:
        if not a.quiet:
            pages = f" {ev.page}/{ev.total_pages}" if ev.total_pages else ""
            print(f"\r[{ev.stage}]{pages} {ev.message}".ljust(60), end="", file=sys.stderr, flush=True)

    try:
        # In-process by default (no process start-up cost; the user's own files). Limits => isolated child.
        if a.timeout or a.max_mem or a.max_pages:
            from .core.isolation import convert_isolated

            res = convert_isolated(a.input, out, opts, progress, timeout_s=a.timeout or None,
                                   max_mem_mb=a.max_mem or None, max_pages=a.max_pages or None)
        else:
            res = convert(a.input, out, opts, progress)
    except ConversionError as e:
        print(f"\npdftoepub: error: {e}", file=sys.stderr)
        return 1
    if not a.quiet:
        print(file=sys.stderr)
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"{res.epub_path}  ({res.page_count} pages, {res.chapter_count} chapters, {res.ocr_pages} OCR)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
