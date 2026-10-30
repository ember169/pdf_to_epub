#!/usr/bin/env bash
# Report the minimum macOS (LC_BUILD_VERSION minos, or LC_VERSION_MIN_MACOSX) of every Mach-O under a folder/app.
#   audit_minos.sh DIR [LIMIT]   -> prints offenders above LIMIT (default 11.0) and the overall minimum; exit 1 if any
set -uo pipefail
DIR=$1; LIMIT=${2:-11.0}; MAX=0; BAD=0
ver_gt() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ] && [ "$1" != "$2" ]; }
while IFS= read -r f; do
  file -b "$f" | grep -q Mach-O || continue
  m=$(otool -l "$f" 2>/dev/null | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; b=0} /LC_VERSION_MIN_MACOSX/{v=1} v&&/version/{print $2; v=0}' | sort -V | tail -1)
  [ -z "$m" ] && continue
  ver_gt "$m" "$MAX" && MAX=$m
  if ver_gt "$m" "$LIMIT"; then echo "  $m  ${f#$DIR/}"; BAD=1; fi
done < <(find "$DIR" -type f)
echo "minimum macOS for $(basename "$DIR"): $MAX (limit $LIMIT)"
exit $BAD
