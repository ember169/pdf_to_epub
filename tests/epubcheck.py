"""epubcheck harness: pinned release, cached under tests/.cache, needs `java`."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

VERSION = "5.4.0"
SHA256 = "33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c"
URL = f"https://github.com/w3c/epubcheck/releases/download/v{VERSION}/epubcheck-{VERSION}.zip"
CACHE = Path(__file__).parent / ".cache"


def java_available() -> bool:
    if not shutil.which("java"):
        return False
    try:  # macOS ships a /usr/bin/java stub that fails when no JRE is installed
        return subprocess.run(["java", "-version"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def jar_path() -> Path:
    """Return the epubcheck jar, downloading and verifying it on first use (or $EPUBCHECK_JAR)."""
    if os.environ.get("EPUBCHECK_JAR"):
        return Path(os.environ["EPUBCHECK_JAR"])
    jar = CACHE / f"epubcheck-{VERSION}" / "epubcheck.jar"
    if jar.exists():
        return jar
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / f"epubcheck-{VERSION}.zip"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=120) as r, open(archive, "wb") as f:
            shutil.copyfileobj(r, f)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        archive.unlink()
        raise RuntimeError("epubcheck download failed sha256 verification")
    with zipfile.ZipFile(archive) as z:
        z.extractall(CACHE)
    return jar


def check(epub: Path, tmp: Path) -> list[str]:
    """Run epubcheck; return list of ERROR/FATAL messages (empty = clean)."""
    report = tmp / "epubcheck.json"
    proc = subprocess.run(["java", "-jar", str(jar_path()), str(epub), "--json", str(report), "--quiet"],
                          capture_output=True, text=True, timeout=300)
    if not report.exists():
        return [f"epubcheck did not produce a report: {proc.stdout}{proc.stderr}"]
    msgs = json.loads(report.read_text())["messages"]
    return [f"{m['severity']} {m['ID']}: {m['message']} ({m['locations'][0]['path'] if m['locations'] else ''})"
            for m in msgs if m["severity"] in ("ERROR", "FATAL")]
