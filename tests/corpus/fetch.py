"""Download the evaluation corpus into tests/.corpus/ (idempotent, sha256-verified).

    python tests/corpus/fetch.py            # fetch missing / mismatching files
    python tests/corpus/fetch.py --pin      # also write hashes of entries whose sha256 is still null

Files are never committed (tests/.corpus/ is git-ignored). Entries with "derive" are image-only excerpts built
locally from another entry with pypdfium2 + Pillow; their hash is only checked as a warning (JPEG output may differ
between Pillow builds).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
CORPUS = HERE.parent / ".corpus"
UA = "pdftoepub-corpus-fetch/1.0 (+evaluation of an open-source PDF to EPUB converter)"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def path_of(doc: dict) -> Path:
    return CORPUS / f"{doc['id']}.pdf"


def download(url: str, dest: Path) -> None:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r, tempfile.NamedTemporaryFile(dir=CORPUS, delete=False) as tmp:
                shutil.copyfileobj(r, tmp)
            Path(tmp.name).replace(dest)
            return
        except OSError as e:
            if attempt == 2:
                raise
            print(f"  retry after error: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def derive(spec: dict, src: Path, dest: Path) -> None:
    """Rasterise selected pages (1-based) of src to JPEG and wrap them in an image-only PDF."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(src))
    images = []
    for pno in spec["pages"]:
        page = pdf[pno - 1]
        img = page.render(scale=spec.get("dpi", 200) / 72, grayscale=True).to_pil().convert("L")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        buf.seek(0)
        from PIL import Image

        images.append(Image.open(buf))
    pdf.close()
    images[0].save(dest, "PDF", save_all=True, append_images=images[1:], resolution=spec.get("dpi", 200))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pin", action="store_true", help="record sha256 for entries that have none yet")
    ap.add_argument("ids", nargs="*", help="only these document ids")
    args = ap.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text())
    CORPUS.mkdir(exist_ok=True)
    by_id = {d["id"]: d for d in manifest["documents"]}
    failed = changed = 0
    # plain downloads first, so derived entries find their source
    for doc in sorted(manifest["documents"], key=lambda d: "derive" in d):
        if args.ids and doc["id"] not in args.ids and not any(by_id[i].get("derive", {}).get("from") == doc["id"] for i in args.ids):
            continue
        dest = path_of(doc)
        want = doc.get("sha256")
        if dest.exists() and (want is None or sha256(dest) == want):
            print(f"ok       {doc['id']}")
        else:
            if "derive" in doc:
                src = path_of(by_id[doc["derive"]["from"]])
                print(f"derive   {doc['id']} <- {src.name}")
                derive(doc["derive"], src, dest)
            else:
                print(f"download {doc['id']} <- {doc['url']}")
                download(doc["url"], dest)
        got = sha256(dest)
        if want is None:
            if args.pin:
                doc["sha256"] = got
                changed += 1
                print(f"  pinned {got}")
            else:
                print(f"  WARNING: no sha256 pinned (got {got}); run with --pin")
        elif got != want:
            if "derive" in doc:
                print(f"  WARNING: derived file differs from pinned hash (Pillow/pdfium version?): {got}")
            else:
                print(f"  ERROR: sha256 mismatch, expected {want} got {got}; file removed", file=sys.stderr)
                dest.unlink()
                failed += 1
    if changed:
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    total = sum(path_of(d).stat().st_size for d in manifest["documents"] if path_of(d).exists())
    print(f"corpus: {total / 1e6:.1f} MB in {CORPUS}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
