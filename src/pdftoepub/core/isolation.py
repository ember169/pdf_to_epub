"""Run one conversion in a child process with a wall-clock timeout, a memory cap and a page limit.

    from pdftoepub.core.isolation import convert_isolated
    result = convert_isolated(pdf, epub, options, progress, timeout_s=600, max_mem_mb=2048, max_pages=2000)

A hostile or simply huge PDF can make the PDF libraries allocate many GB (a 100 MB file of Flate / object streams
inflates without bound in pdfminer), loop for a long time, or crash in native code (pdfium / MuPDF cannot be
interrupted from Python). In a child process all of that is contained: the parent enforces the deadline and the memory
cap (resident set size, polled; plus RLIMIT_AS as a hard backstop on Linux) by killing the child, and maps every breach
to a user-safe `ConversionError`. Progress events are relayed to the caller's callback through a pipe.

The child is started with the "spawn" method on every platform (forking a threaded web server is unsafe). Frozen
executables (PyInstaller) must call `multiprocessing.freeze_support()` at the start of the program's entry point.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

from ..api import ConversionError, ConvertOptions, ConvertResult, ProgressCb

POLL_S = 0.2


def convert_isolated(pdf_path: str | Path, epub_path: str | Path, options: ConvertOptions | None = None,
                     progress: ProgressCb | None = None, timeout_s: float | None = 600,
                     max_mem_mb: int | None = 2048, max_pages: int | None = None) -> ConvertResult:
    """Same result as `pdftoepub.convert`, computed in a child process. `None` disables a limit."""
    pdf_path, epub_path = Path(pdf_path), Path(epub_path)
    existed = epub_path.exists()
    ctx = mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(send, str(pdf_path), str(epub_path), options or ConvertOptions(),
                                            max_pages, max_mem_mb), daemon=True, name="pdftoepub-convert")
    deadline = time.monotonic() + timeout_s if timeout_s else None
    result: ConvertResult | None = None
    ok = False
    try:
        proc.start()
        send.close()
        last_mem = 0.0
        while result is None:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise ConversionError(f"The conversion took longer than {timeout_s:g} seconds and was stopped.")
            if max_mem_mb and time.monotonic() - last_mem >= POLL_S:
                last_mem = time.monotonic()
                rss = _rss_mb(proc.pid)
                if rss is not None and rss > max_mem_mb:
                    raise ConversionError(f"The PDF needs more than {max_mem_mb} MB of memory to convert "
                                          "and was stopped.")
            wait = POLL_S if deadline is None else max(0.0, min(POLL_S, deadline - now))
            if recv.poll(wait):
                try:
                    kind, payload = recv.recv()
                except (EOFError, OSError):
                    break  # the child died without a word
                if kind == "progress":
                    if progress:
                        progress(payload)
                elif kind == "result":
                    result = payload
                elif kind == "error":
                    raise ConversionError(payload)
                continue
            if not proc.is_alive() and not recv.poll():
                break
        if result is None:
            proc.join(5)
            code = proc.exitcode
            if code is not None and code < 0:  # killed by a signal: OOM killer, RLIMIT_AS, native crash
                raise ConversionError("The conversion process was stopped by the system (out of memory or a crash "
                                      "in the PDF library). The PDF may be too large or damaged.")
            raise ConversionError("The conversion process stopped unexpectedly; the PDF may be too large or damaged.")
        ok = True
        return result
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(10)
        recv.close()
        if not ok and not existed:
            try:
                epub_path.unlink()
            except OSError:
                pass


def _child(conn, pdf: str, epub: str, options: ConvertOptions, max_pages: int | None, max_mem_mb: int | None) -> None:
    _set_limits(max_mem_mb)
    try:
        from . import pipeline

        res = pipeline.run(Path(pdf), Path(epub), options, lambda ev: conn.send(("progress", ev)), max_pages=max_pages)
        conn.send(("result", res))
    except ConversionError as exc:
        conn.send(("error", str(exc)))
    except MemoryError:
        conn.send(("error", "The PDF is too large to convert with the available memory."))
    except BaseException as exc:  # noqa: BLE001 - never leak a traceback to the user
        try:
            conn.send(("error", f"The PDF could not be converted ({type(exc).__name__})."))
        except Exception:  # noqa: BLE001
            pass
    finally:
        conn.close()


def _set_limits(max_mem_mb: int | None) -> None:
    """Hard address-space backstop (Linux; macOS accepts but does not enforce it; absent on Windows). Virtual memory is
    much larger than the resident set, so the cap is generous; the parent's RSS watchdog enforces `max_mem_mb`."""
    if not max_mem_mb:
        return
    try:
        import resource
    except ImportError:
        return
    limit = max(2 * max_mem_mb, max_mem_mb + 1024) * 1024 * 1024
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError):
        pass


def _rss_mb(pid: int) -> float | None:
    """Resident set size of `pid` in MB, or None if it cannot be measured (best effort, no hard dependency)."""
    try:
        import psutil  # optional

        return psutil.Process(pid).memory_info().rss / 2**20
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - process gone
        return None
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        try:
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except OSError:
            return None
    if sys.platform == "darwin" or os.name == "posix":
        try:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / 1024 if out.stdout.strip() else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None
