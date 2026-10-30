# pdftoepub

Self-hostable PDF → **reflowable EPUB 3** converter. The output contains real text (headings, paragraphs,
lists, tables, inline images), not page images, so it scales with the reader's font size and screen.
Scanned pages are recognised with Tesseract OCR. A small web front (drag & drop, progress, download) and a CLI are included.

## Quickstart

### Docker (recommended)

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Open <http://localhost:8000>. The compose file publishes the port on **127.0.0.1 only**; to host it publicly, keep that mapping, put Caddy in front (`deploy/Caddyfile.example`) and set `AUTH_TOKEN`. The container runs read-only, with a memory limit (`MEM_LIMIT`, default 2g), 256 pids and dropped capabilities. Uploads and results live in the `pdftoepub-data` volume and are purged after `JOB_TTL_HOURS`.
The image includes Tesseract with English and French language data.

### Local

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pdftoepub book.pdf -o book.epub        # CLI
pdftoepub serve                        # web front on :8000
# or: uvicorn pdftoepub.web.app:app --port 8000
```

For OCR from a source install, install `tesseract` plus language packs (`brew install tesseract tesseract-lang`, `apt install tesseract-ocr-fra`); the binaries and the Docker image already include it.
Without Tesseract, scanned pages are skipped with a warning.

## Portable binary (no Python, no Tesseract to install)

Everything is built locally (no CI) with `packaging/build.sh`; the files land in `dist/` with `SHA256SUMS` and
`THIRD_PARTY_LICENSES`. **OCR is built in**: every binary ships Tesseract 5 (Windows 5.4, macOS 5.5, Linux 4.1) with
French and English data (`tessdata_fast`, ~5 MB for both, chosen over `tessdata_best` ~20 MB for size/speed; accuracy
is a bit lower on poor scans).

| File | Size | Runs on | How it was built / tested |
|---|---|---|---|
| `pdftoepub-macos-arm64` | 40 MB | Apple-silicon Macs, **macOS 26 or newer** (see below) | native; tested with `env -i` |
| `pdftoepub-linux-x86_64` | 73 MB | glibc ≥ 2.31 (Debian 11, Ubuntu 20.04 and newer) | Docker (bullseye); tested on debian:11 + ubuntu:20.04 |
| `pdftoepub-linux-arm64` | 72 MB | same, ARM | same |
| `pdftoepub-windows-x86_64.exe` | 88 MB | 64-bit Windows | built under **Wine** in Docker; tested under Wine only, never on real Windows |

```bash
chmod +x pdftoepub-linux-x86_64              # macOS/Linux
./pdftoepub-linux-x86_64 book.pdf -o book.epub
./pdftoepub-linux-x86_64 serve --open        # web front on http://127.0.0.1:8000
./pdftoepub-linux-x86_64                     # no arguments: starts the web UI and opens the browser
```

- **macOS Gatekeeper:** the binary is not signed or notarised. If macOS refuses to open it, run
  `xattr -d com.apple.quarantine ./pdftoepub-macos-arm64` (or right-click → Open once).
- **Windows SmartScreen:** the `.exe` is unsigned, so Windows shows "Windows protected your PC": click *More info* →
  *Run anyway*.
- **macOS version:** the bundled Python, OpenSSL and Tesseract come from Homebrew and are built for macOS 26 (Tahoe),
  so the macOS binary does not run on older macOS. Building with a python.org/uv Python and a from-source Tesseract
  with a lower deployment target would fix this; not done yet.
- **Linux glibc:** built on Debian 11 (glibc 2.31). The highest glibc symbol needed by the bundled Tesseract is
  `GLIBC_2.29`, by the launcher `GLIBC_2.17`/`2.14`; verified by running in clean `debian:11-slim` and `ubuntu:20.04`
  containers with no Python or Tesseract installed.
- **Startup (macOS, measured):** the macOS file is a self-extracting launcher. The first run unpacks ~100 MB into
  `~/Library/Caches/pdftoepub/<hash>/` (override: `PDFTOEPUB_HOME`) and warms it up while macOS security-scans the new
  files: about 15 s once. After that: `--help` 0.06 s, converting a 2-page PDF 0.3 s, an OCR page 0.5 s. Delete the
  cache folder to uninstall. Linux and Windows files are plain one-file builds and start in a couple of seconds.
- **Using another Tesseract:** `TESSERACT_CMD=/path/to/tesseract` and `TESSDATA_PREFIX=/path/to/tessdata` take
  precedence over the bundled copy; a `tesseract/` folder next to the executable does too; a Tesseract on `PATH` is the
  last fallback.
- **Licences:** the binaries are MIT-clean (no PyMuPDF; build scripts fail if it is present). Third-party licences are in
  `THIRD_PARTY_LICENSES` (also embedded in each binary).

### Building

Docker image and binaries install the same exact, hash-checked versions from `requirements.lock`
(`pyproject.toml` keeps ranges; `packaging/relock.sh` regenerates the locks).

```bash
packaging/build.sh                 # macOS (needs: brew install tesseract dylibbundler) + linux-arm64
packaging/build.sh linux-x86_64    # QEMU/Rosetta emulation, ~1-5 min
packaging/build.sh windows         # Wine in Docker, experimental
packaging/relock.sh                # regenerate the hash-pinned lock files (needs uv)
packaging/smoke.sh                 # tests every binary in dist/ in clean environments (CLI, bundled OCR, serve, spawned-job
                                   # limits, no-argument launch, epubcheck of every output), rewrites dist/SHA256SUMS
```

Windows notes: CPython 3.12.10 (nuget) and Tesseract 5.4.0 (UB-Mannheim release, unpacked not run) are pinned and
sha256-verified in `packaging/Dockerfile.windows`. `packaging/build.ps1` is a native-Windows alternative that has never
been run.

## Options

| Option | Default | Meaning |
|---|---|---|
| `title`, `author` | from PDF metadata | Override metadata |
| `language` | detected | BCP 47 code, e.g. `fr` |
| `ocr` | `auto` | `auto` (pages without text), `off`, `force` |
| `ocr_langs` | `fra+eng` | Tesseract language string |
| `drop_headers_footers` | on | Remove running headers/footers and page numbers |
| `detect_columns` | on | Multi-column reading order |
| `image_mode` | `inline` | `inline` or `none` |

Server environment variables: `DATA_DIR` (`/data` in Docker), `MAX_UPLOAD_MB` (100), `JOB_TTL_HOURS` (24),
`MAX_CONCURRENT_JOBS` (2), `AUTH_TOKEN` (optional bearer token), `GET /healthz` for health checks.

## Public hosting

Set `AUTH_TOKEN`, bind the container to localhost and put a TLS proxy in front. See
[`deploy/Caddyfile.example`](deploy/Caddyfile.example) (disables SSE buffering, caps body size).

## Tests

```bash
pip install -e ".[dev]"
pytest                      # fixtures are generated on the fly
python tests/fixtures/make_fixtures.py out/   # write the sample PDFs
docker build -f deploy/Dockerfile --target test -t pdftoepub-test . && docker run --rm pdftoepub-test
```

The Docker test image has Java, Tesseract and runs **epubcheck** (v5.4.0, downloaded once into `tests/.cache`,
sha256-verified; set `EPUBCHECK_JAR` to use your own). Locally, epubcheck tests are skipped when `java` is missing.
The suite runs once per backend (`PDFTOEPUB_BACKEND` = `pdfminer`, `pymupdf`; the latter skipped if PyMuPDF isn't installed).
Tests marked `core` are xfailed automatically while the stub converter is active.

## Limits

- Max upload `MAX_UPLOAD_MB`; encrypted (password-protected) and non-PDF files are rejected.
- Layout analysis is heuristic: complex layouts (nested tables, magazines, math) may need manual cleanup.
- Vector figures are rasterised; OCR quality depends on scan quality and the chosen languages.
- Jobs are processed in-process; there is no multi-node scaling.

## License

MIT (see `LICENSE`). Default PDF backend: pdfminer.six (MIT) + pypdfium2 (Apache-2.0/BSD-3).
An optional backend uses [PyMuPDF](https://pymupdf.readthedocs.io/) (`pip install ".[pymupdf]"`, select with
`PDFTOEPUB_BACKEND=pymupdf`): PyMuPDF is **AGPL-3.0**, so an installation that includes it is subject to the AGPL
(source offer for network services). The Docker image does not include it.

Other third-party components: Tesseract OCR (Apache-2.0), epubcheck (BSD-3-Clause, tests only), pypdf (BSD-3, tests only).
