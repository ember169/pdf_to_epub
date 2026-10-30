#!/usr/bin/env bash
# Local portable builds (no CI). Usage: packaging/build.sh [mac] [linux-arm64] [linux-x86_64] [windows]
# Output in dist/: pdftoepub-<os>-<arch> and SHA256SUMS.  Windows: use packaging/build.ps1 on a Windows machine.
# macOS output is a self-extracting launcher around a PyInstaller folder build (see make_sfx).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
TARGETS=(); 
for a in "$@"; do TARGETS+=("$a"); done
if [ ${#TARGETS[@]} -eq 0 ]; then TARGETS=(mac linux-arm64); [ -n "${LINUX_X86:-}" ] && TARGETS+=(linux-x86_64); fi
mkdir -p dist

# make_sfx DIR OUT: one shell-script+tar.gz file. First run unpacks to ~/Library/Caches/pdftoepub/<hash>/, later runs
# exec straight into it (macOS rescans freshly extracted files on every launch of a PyInstaller one-file build, ~4 s).
make_sfx() {
  local dir=$1 out=$2 payload=build/payload.tgz hdr=build/hdr.sh
  (cd "$(dirname "$dir")" && COPYFILE_DISABLE=1 tar czf "$ROOT/$payload" "$(basename "$dir")")
  local h; h=$(shasum -a 256 "$payload" | cut -c1-16)
  cat > $hdr <<EOF2
#!/bin/sh
# pdftoepub self-extracting executable (payload: tar.gz appended after the last line of this header)
D="\${PDFTOEPUB_HOME:-\${XDG_CACHE_HOME:-\$HOME/Library/Caches}/pdftoepub}/$h"
if [ ! -x "\$D/pdftoepub/pdftoepub" ]; then
  echo "pdftoepub: first run, unpacking (one-time, can take ~20 s on macOS while it is security-scanned)..." >&2
  T="\$D.\$\$.tmp"; mkdir -p "\$T" || exit 1
  tail -n +@LINES@ "\$0" | tar xzf - -C "\$T" || { rm -rf "\$T"; echo "pdftoepub: extraction failed" >&2; exit 1; }
  mv "\$T" "\$D" 2>/dev/null || rm -rf "\$T"
  "\$D/pdftoepub/pdftoepub" --_warmup >/dev/null 2>&1
fi
PDFTOEPUB_EXE_DIR="\$(cd "\$(dirname "\$0")" && pwd)"; export PDFTOEPUB_EXE_DIR
exec "\$D/pdftoepub/pdftoepub" "\$@"
exit 1
EOF2
  local lines; lines=$(( $(wc -l < $hdr) + 1 ))
  sed -i '' "s/@LINES@/$lines/" $hdr
  cat $hdr $payload > "$out"; chmod +x "$out"
}

# prepare_tess_mac DIR: copy Homebrew tesseract + all its dylibs (relocated with dylibbundler), configs and tessdata_fast eng/fra
prepare_tess_mac() {
  local d=$1; command -v tesseract >/dev/null && command -v dylibbundler >/dev/null \
    || { echo "need: brew install tesseract dylibbundler"; return 1; }
  packaging/fetch_tessdata.sh
  rm -rf "$d"; mkdir -p "$d/libs" "$d/tessdata"
  cp "$(brew --prefix tesseract)/bin/tesseract" "$d/tesseract"; chmod u+w "$d/tesseract"
  dylibbundler -od -b -x "$d/tesseract" -d "$d/libs" -p @executable_path/libs >/dev/null
  cp -R "$(brew --prefix tesseract)/share/tessdata/configs" "$(brew --prefix tesseract)/share/tessdata/tessconfigs" "$d/tessdata/"
  cp packaging/tessdata/eng.traineddata packaging/tessdata/fra.traineddata "$d/tessdata/"
  find "$d" -type f \( -name "*.dylib" -o -name tesseract \) -exec codesign --force -s - {} \; 2>/dev/null
  "$d/tesseract" --version 2>&1 | head -1
  ! otool -L "$d/tesseract" "$d"/libs/*.dylib | grep -E "/opt/homebrew|/usr/local" || { echo "unrelocated dylib references remain"; return 1; }
}

build_mac() {
  [ "$(uname -s)" = Darwin ] || { echo "mac target needs macOS"; return 1; }
  local arch; arch=$(uname -m); [ "$arch" = aarch64 ] && arch=arm64
  local name="pdftoepub-macos-$arch"
  rm -rf packaging/.buildvenv build
  ${PYTHON:-python3} -m venv packaging/.buildvenv
  local v=packaging/.buildvenv/bin
  $v/python -m pip install -q --upgrade pip
  # same exact, hash-checked versions as the Docker image (requirements.lock) + pinned PyInstaller
  $v/python -m pip install -q --require-hashes --no-deps -r requirements.lock -r packaging/build.lock -r packaging/build-backend.lock
  $v/python -m pip install -q --no-deps --no-build-isolation .
  # clean venv with ONLY runtime deps: PyMuPDF (AGPL) must not be present
  $v/python -I -c "import importlib.util as u,sys; sys.exit(1 if u.find_spec('pymupdf') else 0)" \
    || { echo "pymupdf in build venv; refusing"; exit 1; }
  prepare_tess_mac build/tess
  $v/python packaging/gen_licenses.py build/THIRD_PARTY_LICENSES --tesseract
  # Folder build (fast: no re-extraction on every launch), wrapped into ONE self-extracting file below.
  (cd packaging && ONEDIR=1 TESS_DIR="$ROOT/build/tess" LICENSES_FILE="$ROOT/build/THIRD_PARTY_LICENSES" "$ROOT/$v/pyinstaller" --noconfirm --clean --distpath "$ROOT/build/out" --workpath "$ROOT/build/work" pdftoepub.spec)
  $v/pyi-archive_viewer -l -r build/out/pdftoepub/pdftoepub 2>/dev/null > build/list || true
  local n; n=$(wc -l < build/list)
  [ "$n" -gt 100 ] && ! grep -i -E "pymupdf|fitz" build/list || { echo "ERROR: PyMuPDF found or archive unreadable"; exit 1; }
  find build/out/pdftoepub \( -iname "*pymupdf*" -o -iname "fitz*" \) | grep . && { echo "ERROR: PyMuPDF files present"; exit 1; }
  make_sfx build/out/pdftoepub "dist/$name"
  echo "OK: $name built, no PyMuPDF inside"
  cp build/THIRD_PARTY_LICENSES dist/THIRD_PARTY_LICENSES
  rm -rf build
}

build_linux() {  # $1 = arm64 | x86_64
  local arch=$1 plat=linux/arm64; [ "$arch" = x86_64 ] && plat=linux/amd64
  docker build --platform "$plat" -f packaging/Dockerfile.linux --target out \
    --output "type=local,dest=build/linux-$arch" .
  mv "build/linux-$arch/pdftoepub" "dist/pdftoepub-linux-$arch"; chmod +x "dist/pdftoepub-linux-$arch"
  cp "build/linux-$arch/THIRD_PARTY_LICENSES" dist/THIRD_PARTY_LICENSES
  echo "glibc minimum: tesseract bundle $(cat build/linux-$arch/glibc_tess_min), bootloader $(cat build/linux-$arch/glibc_bootloader_min)"
  rm -rf "build/linux-$arch"
  echo "OK: pdftoepub-linux-$arch built"
}

build_windows() {  # experimental: PyInstaller + Windows Python + Windows Tesseract under Wine in Docker (linux/amd64)
  docker build --platform linux/amd64 -f packaging/Dockerfile.windows --target out --output type=local,dest=build/win .
  mv build/win/pdftoepub.exe dist/pdftoepub-windows-x86_64.exe; cp build/win/THIRD_PARTY_LICENSES dist/THIRD_PARTY_LICENSES; rm -rf build/win
  docker build -q --platform linux/amd64 -f packaging/Dockerfile.windows --target base -t pte-winbase . >/dev/null  # image used by smoke.sh
  echo "OK: pdftoepub-windows-x86_64.exe built (under Wine)"
}

for t in "${TARGETS[@]}"; do
  case $t in mac) build_mac;; linux-arm64) build_linux arm64;; linux-x86_64) build_linux x86_64;; windows) build_windows;; *) echo "unknown target $t"; exit 1;; esac
done
(cd dist && : > SHA256SUMS && for f in pdftoepub-*; do case $f in *.zip|*-dir) ;; *) shasum -a 256 "$f" >> SHA256SUMS;; esac; done; cat SHA256SUMS)
