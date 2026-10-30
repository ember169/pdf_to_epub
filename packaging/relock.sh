#!/usr/bin/env bash
# Regenerate all pinned, hashed lock files (needs uv). Commit the results; builds use them with --require-hashes.
set -euo pipefail
cd "$(dirname "$0")/.."
C="uv pip compile --universal --generate-hashes -q"
$C pyproject.toml -o requirements.lock
$C pyproject.toml --extra dev -o requirements-dev.lock
$C packaging/build.in -o packaging/build.lock
$C packaging/build-backend.in -o packaging/build-backend.lock
printf 'pyinstaller\n' > packaging/build.in
uv pip compile pyproject.toml packaging/build.in --python-platform x86_64-pc-windows-msvc --python-version 3.12 --generate-hashes -q -o packaging/windows-requirements.txt
uv pip compile pyproject.toml packaging/build.in packaging/build-backend.in --python-platform x86_64-apple-darwin --python-version 3.12 --only-binary :all: --generate-hashes -q -o packaging/macos-x86_64.lock
uv pip compile packaging/macos-pdfium.in --universal --generate-hashes -q -o packaging/macos-pdfium.lock
