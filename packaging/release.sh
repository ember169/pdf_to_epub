#!/usr/bin/env bash
# Publish the locally built artefacts in dist/ as a GitHub Release (no CI: everything is built and checked on this machine).
#
#   packaging/release.sh vX.Y.Z [--notes FILE] [--publish]
#
# Default is a dry run: checks the artefacts, rewrites dist/SHA256SUMS and prints the `gh release create` command.
# --publish actually creates the release (needs `gh auth login` and a GitHub remote). Build first with packaging/build.sh
# (all targets) and test with packaging/smoke.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=${PDFTOEPUB_REPO:-ember169/pdftoepub}   # GitHub slug: the one place to change it (also used in README links)
TAG=${1:-}; shift || true
NOTES=""; PUBLISH=""
while [ $# -gt 0 ]; do
  case $1 in
    --notes) NOTES=$2; shift 2;;
    --publish) PUBLISH=1; shift;;
    *) echo "unknown option: $1"; exit 2;;
  esac
done
[[ $TAG =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { sed -n '2,8p' "$0"; exit 2; }

ARTEFACTS=(pdftoepub-macos-arm64.dmg pdftoepub-macos-arm64 pdftoepub-macos-x86_64.dmg pdftoepub-macos-x86_64
           pdftoepub-linux-arm64 pdftoepub-linux-x86_64 pdftoepub-windows-x86_64.exe)
for f in "${ARTEFACTS[@]}"; do [ -f "dist/$f" ] || { echo "missing dist/$f (run packaging/build.sh)"; exit 1; }; done
VERSION=$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml | head -1)
[ "v$VERSION" = "$TAG" ] || echo "WARNING: tag $TAG differs from pyproject.toml version $VERSION"

(cd dist && shasum -a 256 "${ARTEFACTS[@]}" > SHA256SUMS)
FILES=("${ARTEFACTS[@]/#/dist/}" dist/SHA256SUMS dist/THIRD_PARTY_LICENSES)
if [ -z "$NOTES" ]; then
  NOTES=$(mktemp); trap 'rm -f "$NOTES"' EXIT
  { echo "Portable builds: download the file for your system (see the README's Download table)."
    echo "macOS and Windows builds are not signed yet: see \"First launch of an unsigned build\" in the README."
    echo; echo '```'; cat dist/SHA256SUMS; echo '```'; } > "$NOTES"
fi
ls -l "${FILES[@]}"
CMD=(gh release create "$TAG" "${FILES[@]}" --repo "$REPO" --title "pdftoepub $TAG" --notes-file "$NOTES")
if [ -n "$PUBLISH" ]; then
  "${CMD[@]}"
else
  echo "DRY RUN (add --publish to run it):"; printf ' %q' "${CMD[@]}"; echo
fi
