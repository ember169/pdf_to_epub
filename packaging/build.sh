#!/usr/bin/env bash
# Local portable builds (no CI). Usage: packaging/build.sh [mac|mac-arm64] [mac-x86_64] [linux-arm64] [linux-x86_64] [windows]
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
  mkdir -p build
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

# Tesseract for a macOS build: the universal from-source build (packaging/build_tesseract_macos.sh, macOS 11+, both
# archs) when present; otherwise Homebrew's (arm64 only, needs the newest macOS); x86_64 without it needs ALLOW_NO_OCR=1.
mac_tess() {  # $1 arch -> prints TESS_DIR (or nothing)
  local arch=$1 d=$ROOT/build/mac-tess-$1
  if [ -x build/tess-macos/tesseract ]; then
    packaging/fetch_tessdata.sh >/dev/null
    rm -rf "$d"; mkdir -p "$d/tessdata"; lipo -thin "$arch" build/tess-macos/tesseract -output "$d/tesseract"
    cp build/tess-macos/LICENSES.txt "$d/"; cp -R build/tess-macos/tessdata/. "$d/tessdata/"
    cp packaging/tessdata/eng.traineddata packaging/tessdata/fra.traineddata "$d/tessdata/"; echo "$d"
  elif [ "$arch" = arm64 ]; then
    prepare_tess_mac "$d" >&2 && echo "$d"
  elif [ -n "${ALLOW_NO_OCR:-}" ]; then
    echo "WARNING: building $arch WITHOUT bundled OCR (run packaging/build_tesseract_macos.sh first)" >&2
  else
    echo "ERROR: no $arch tesseract: run packaging/build_tesseract_macos.sh (or set ALLOW_NO_OCR=1)" >&2; return 1
  fi
}

build_mac() {  # $1 = arm64 | x86_64 (x86_64 runs under Rosetta on Apple silicon)
  [ "$(uname -s)" = Darwin ] || { echo "mac target needs macOS"; return 1; }
  local arch=${1:-arm64} uvarch=aarch64; [ "$arch" = x86_64 ] && uvarch=x86_64
  local name="pdftoepub-macos-$arch" W=$ROOT/build/mac-$arch v=$ROOT/packaging/.buildvenv-$arch
  local A=(arch "-$arch")
  rm -rf "$W" "$v"; mkdir -p "$W"
  # python-build-standalone CPython (via uv): per-arch, built for macOS 11+, unlike Homebrew's Python
  local py; py=$(uv python find "cpython-3.12.13-macos-$uvarch-none") || { uv python install "cpython-3.12.13-macos-$uvarch-none" && py=$(uv python find "cpython-3.12.13-macos-$uvarch-none"); }
  "${A[@]}" "$py" -m venv "$v"
  "${A[@]}" "$v/bin/python" -m pip install -q --upgrade pip
  # same exact, hash-checked versions as the Docker image (requirements.lock) + pinned PyInstaller
  local locks=(-r requirements.lock -r packaging/build.lock -r packaging/build-backend.lock)
  [ "$arch" = x86_64 ] && locks=(-r packaging/macos-x86_64.lock)  # Intel: last versions that still ship x86_64 wheels
  "${A[@]}" "$v/bin/python" -m pip install -q --require-hashes --no-deps --only-binary :all: "${locks[@]}"
  # pypdfium2 >= 5.12 ships PDFium built for macOS 13; 5.9.0 (wheel tagged 11.0, PDFium actually built for 12.0) passes
  # the same test suite, so macOS builds pin it: macOS 12 Monterey is then the floor of the whole app
  "${A[@]}" "$v/bin/python" -m pip install -q --require-hashes --no-deps --only-binary :all: -r packaging/macos-pdfium.lock
  "${A[@]}" "$v/bin/python" -m pip install -q --no-deps --no-build-isolation .
  "${A[@]}" "$v/bin/python" -I -c "import importlib.util as u,sys; sys.exit(1 if u.find_spec('pymupdf') else 0)" \
    || { echo "pymupdf in build venv; refusing"; exit 1; }
  local tess; tess=$(mac_tess "$arch") || exit 1
  "${A[@]}" "$v/bin/python" packaging/gen_licenses.py "$W/THIRD_PARTY_LICENSES" ${tess:+--tesseract}
  # Folder build + .app bundle. The folder becomes the self-extracting CLI, the .app goes into the .dmg.
  (cd packaging && ONEDIR=1 MAC_APP=1 TESS_DIR="$tess" LICENSES_FILE="$W/THIRD_PARTY_LICENSES" \
    "${A[@]}" "$v/bin/pyinstaller" --noconfirm --clean --distpath "$W/out" --workpath "$W/work" pdftoepub.spec) >"$W/pyinstaller.log" 2>&1 \
    || { tail -20 "$W/pyinstaller.log"; exit 1; }
  find "$W/out" \( -iname "*pymupdf*" -o -iname "fitz*" \) | grep . && { echo "ERROR: PyMuPDF files present"; exit 1; }
  [ -n "$(find "$W/out/pdftoepub.app" -name large_fr.msgpack.gz)" ] || { echo "ERROR: wordfreq lexicon not bundled"; exit 1; }
  lipo -archs "$W/out/pdftoepub/pdftoepub" | grep -qw "$arch" || { echo "ERROR: wrong architecture"; exit 1; }
  packaging/audit_minos.sh "$W/out/pdftoepub.app" "${MAC_MIN_OS:-12.0}" || [ -n "${ALLOW_NEWER_MACOS:-}" ] \
    || { echo "ERROR: some code needs a newer macOS than ${MAC_MIN_OS:-12.0} (ALLOW_NEWER_MACOS=1 to accept)"; exit 1; }
  # sign the CLI payload BEFORE packing it, so the code extracted on users' machines is already signed
  packaging/sign_macos.sh payload "$W/out/pdftoepub"
  make_sfx "$W/out/pdftoepub" "dist/$name"
  packaging/sign_macos.sh app "$W/out/pdftoepub.app" "dist/$name.dmg"
  cp "$W/THIRD_PARTY_LICENSES" dist/THIRD_PARTY_LICENSES
  echo "OK: dist/$name (CLI) + dist/$name.dmg (app), no PyMuPDF inside, $([ -n "$tess" ] && echo "with bundled OCR" || echo "WITHOUT bundled OCR")"
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

# wordfreq lexicons (glued-word splitter), fetched once into src/ (pinned, sha256-checked; no-op when present): the
# spec bundles them from there, and the Docker builds below copy src/ with them
python3 src/pdftoepub/core/lexicon.py fetch >/dev/null || { echo "cannot fetch the wordfreq lexicons"; exit 1; }
for t in "${TARGETS[@]}"; do
  case $t in mac|mac-arm64) build_mac arm64;; mac-x86_64) build_mac x86_64;; linux-arm64) build_linux arm64;; linux-x86_64) build_linux x86_64;; windows) build_windows;; *) echo "unknown target $t"; exit 1;; esac
done
(cd dist && : > SHA256SUMS && for f in pdftoepub-*; do case $f in *.zip|*-dir) ;; *) shasum -a 256 "$f" >> SHA256SUMS;; esac; done; cat SHA256SUMS)
