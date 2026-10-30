"""PyInstaller entry point: points the app at the bundled tesseract (system one is the fallback), then runs the CLI."""
import os
import sys
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("PDFTOEPUB_EXE_DIR"):  # set by the macOS self-extracting launcher
        dirs.append(Path(os.environ["PDFTOEPUB_EXE_DIR"]) / "tesseract")
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / "tesseract")  # user override next to the executable
        dirs.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "tesseract")  # bundled copy
    return dirs


def _setup_tesseract() -> None:
    """Order: $TESSERACT_CMD, tesseract/ next to the executable, bundled copy, then whatever is on PATH."""
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd:  # core looks tesseract up on PATH, so expose the chosen binary's directory
        os.environ["PATH"] = str(Path(cmd).resolve().parent) + os.pathsep + os.environ.get("PATH", "")
        return
    exe_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    for d in _candidate_dirs():
        if (d / exe_name).is_file():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            os.environ["TESSERACT_CMD"] = str(d / exe_name)
            if "TESSDATA_PREFIX" not in os.environ and (d / "tessdata").is_dir():
                os.environ["TESSDATA_PREFIX"] = str(d / "tessdata")
            return


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # must stay first: spawned workers re-enter this file inside the frozen binary
    if sys.platform == "darwin":  # leptonica rewrites paths under /tmp using $TMPDIR, so make sure it is set
        os.environ.setdefault("TMPDIR", "/var/tmp")
    _setup_tesseract()
    if sys.argv[1:] == ["--_spawn"]:  # smoke test: a spawn-context worker process must work inside the binary
        with multiprocessing.get_context("spawn").Pool(1) as pool:
            print("spawn ok:", pool.apply(pow, (2, 5)))
        raise SystemExit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "--_diag":  # --_diag IMAGE: run tesseract on it
        import subprocess
        r = subprocess.run([os.environ.get("TESSERACT_CMD", "tesseract"), sys.argv[2], "stdout", "-l", "eng+fra", "--psm", "3", "tsv"],
                           capture_output=True, text=True)
        print(r.returncode, r.stdout[:600], r.stderr[:600])
        raise SystemExit(0)
    if sys.argv[1:] == ["--_diag"]:  # prints which tesseract is used and whether it starts
        import subprocess
        cmd = os.environ.get("TESSERACT_CMD") or "tesseract"
        print("tesseract:", cmd, "| TESSDATA_PREFIX:", os.environ.get("TESSDATA_PREFIX"))
        r = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True)
        print(r.returncode, r.stdout.strip().replace("\n", " "), r.stderr.strip()[:500])
        raise SystemExit(0)
    if sys.argv[1:] == ["--_warmup"]:  # first-run helper: touch every native lib once so macOS scans them now, not later
        import subprocess
        for m in ("pdftoepub.web.app", "pdftoepub.core.pipeline", "pdfminer.high_level", "pypdfium2", "PIL.Image", "cryptography.hazmat.backends"):
            try:
                __import__(m)
            except Exception:
                pass
        if os.environ.get("TESSERACT_CMD"):
            try:
                subprocess.run([os.environ["TESSERACT_CMD"], "--version"], capture_output=True, timeout=120)
            except Exception:
                pass
        raise SystemExit(0)
    from pdftoepub.cli import main
    raise SystemExit(main())
