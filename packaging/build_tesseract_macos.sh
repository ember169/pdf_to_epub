#!/usr/bin/env bash
# Build a self-contained, universal (arm64 + x86_64) tesseract for macOS 11+ from pinned, sha256-checked sources:
# libpng + leptonica (static, PNG/zlib only) + tesseract (static, no training tools/curl/libarchive/OpenMP).
# Why: Homebrew no longer ships Intel bottles, and its arm64 bottles target only the newest macOS.
# Output: build/tess-macos/tesseract (fat binary, only system libraries) + tessdata/{configs,tessconfigs}
# Usage: packaging/build_tesseract_macos.sh   (needs Xcode command line tools + cmake; ~5 min, cached afterwards)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; OUT=$ROOT/build/tess-macos; SRC=$ROOT/build/tess-src; mkdir -p "$SRC"
[ -x "$OUT/tesseract" ] && { echo "cached: $OUT/tesseract"; exit 0; }
fetch() {  # url file sha256
  [ -f "$SRC/$2" ] || curl -fsSL -o "$SRC/$2" "$1"
  echo "$3  $SRC/$2" | shasum -a 256 -c - >/dev/null || { echo "sha256 mismatch for $2"; rm -f "$SRC/$2"; exit 1; }
  tar xzf "$SRC/$2" -C "$SRC"
}
fetch https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.59.tar.gz libpng-1.6.59.tar.gz 2540302a1844ad2b2b501977abecfa850f265f97b78f065a712ab4074a89f5b5
fetch https://github.com/DanBloomberg/leptonica/releases/download/1.87.0/leptonica-1.87.0.tar.gz leptonica-1.87.0.tar.gz c73363397f96eb1295602bf44d708a994ad42046c791bf03ea0505d829bdb6a7
fetch https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.5.4.tar.gz tesseract-5.5.4.tar.gz a8dbf8b8c8ee427ff6ad1d99116502feaf59440af1adb893caf60a6576826cf4
export MACOSX_DEPLOYMENT_TARGET=11.0
JOBS=$(sysctl -n hw.ncpu)
for arch in arm64 x86_64; do
  P=$ROOT/build/tess-prefix-$arch; B=$ROOT/build/tess-build-$arch; rm -rf "$B"; mkdir -p "$B"
  # When the target arch differs from the host, CMAKE_SYSTEM_NAME makes CMake treat this as a cross build, so
  # CMAKE_SYSTEM_PROCESSOR is the target arch and tesseract does not enable host-only SIMD (NEON on Apple Silicon).
  # Cross builds can't try_run, so seed leptonica's TIFF probe (TIFF is disabled anyway).
  X=""; [ "$arch" != "$(uname -m)" ] && X="-DCMAKE_SYSTEM_NAME=Darwin -DCMAKE_SYSTEM_PROCESSOR=$arch -DLEPT_TIFF_RESULT=1 -DLEPT_TIFF_RESULT__TRYRUN_OUTPUT="
  C="$X -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=$arch -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 -DCMAKE_INSTALL_PREFIX=$P -DCMAKE_PREFIX_PATH=$P -DBUILD_SHARED_LIBS=OFF -DCMAKE_FIND_FRAMEWORK=NEVER -DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local"
  cmake -S "$SRC/libpng-1.6.59" -B "$B/png" $C -DPNG_SHARED=OFF -DPNG_STATIC=ON -DPNG_TESTS=OFF -DPNG_TOOLS=OFF \
        -DPNG_FRAMEWORK=OFF -DPNG_HARDWARE_OPTIMIZATIONS=OFF >/dev/null
  cmake --build "$B/png" -j "$JOBS" --target install >/dev/null
  cmake -S "$SRC/leptonica-1.87.0" -B "$B/lept" $C -DSW_BUILD=OFF -DENABLE_GIF=OFF -DENABLE_JPEG=OFF -DENABLE_TIFF=OFF \
        -DENABLE_WEBP=OFF -DENABLE_OPENJPEG=OFF -DENABLE_ZLIB=ON -DENABLE_PNG=ON -DBUILD_PROG=OFF >/dev/null
  cmake --build "$B/lept" -j "$JOBS" --target install >/dev/null
  cmake -S "$SRC/tesseract-5.5.4" -B "$B/tess" $C -DSW_BUILD=OFF -DBUILD_TRAINING_TOOLS=OFF -DDISABLE_ARCHIVE=ON \
        -DDISABLE_CURL=ON -DGRAPHICS_DISABLED=ON -DOPENMP_BUILD=OFF -DBUILD_TESTS=OFF -DDISABLE_TIFF=ON \
        -DLeptonica_DIR="$P/lib/cmake/leptonica" >/dev/null
  # build the executable only: the install target re-runs configure, whose try_run fails for the cross (x86_64) build
  cmake --build "$B/tess" -j "$JOBS" --target tesseract >/dev/null
  echo "built tesseract for $arch"
done
mkdir -p "$OUT/tessdata"
lipo -create build/tess-build-arm64/tess/bin/tesseract build/tess-build-x86_64/tess/bin/tesseract -output "$OUT/tesseract"
cp -R "$SRC/tesseract-5.5.4/tessdata/configs" "$SRC/tesseract-5.5.4/tessdata/tessconfigs" "$OUT/tessdata/"
{ for f in tesseract-5.5.4/LICENSE leptonica-1.87.0/leptonica-license.txt libpng-1.6.59/LICENSE; do
    echo "==== ${f%%/*} ===="; cat "$SRC/$f"; echo; done; } > "$OUT/LICENSES.txt"   # BSD/libpng terms: ship the notices
lipo -info "$OUT/tesseract"; otool -L "$OUT/tesseract" | tail -n +2
! otool -L "$OUT/tesseract" | tail -n +2 | grep -v -E "^\s+/(usr/lib|System/Library)/" || { echo "non-system library dependency"; exit 1; }
