#!/usr/bin/env bash
# macOS code signing, 100% local. Used by packaging/build.sh; can also be run by hand.
#
#   sign_macos.sh payload DIR        sign every Mach-O under DIR, inside-out (CLI payload, before it is packed)
#   sign_macos.sh app APP DMG        sign APP inside-out, [notarize+staple APP], build DMG, sign it, [notarize+staple DMG]
#
# Environment:
#   APPLE_SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)" (or its SHA-1). Unset -> ad-hoc signature:
#                         the app runs, but Gatekeeper warns on first open (right-click > Open, or xattr -d).
#   APPLE_NOTARY_PROFILE  keychain profile created once with
#                         `xcrun notarytool store-credentials NAME --apple-id ... --team-id ... --password <app-specific>`
#                         Set -> notarize, staple, and check with spctl.
#   APPLE_KEYCHAIN        optional keychain holding the identity (default: the user's search list)
#   SIGN_ENTITLEMENTS     default packaging/entitlements.plist (hardened runtime, no exceptions)
set -euo pipefail
cd "$(dirname "$0")/.."
ID=${APPLE_SIGN_IDENTITY:-}
ENT=${SIGN_ENTITLEMENTS:-$PWD/packaging/entitlements.plist}
KC=()
if [ -n "${APPLE_KEYCHAIN:-}" ]; then
  # codesign only finds identities in the keychain search list: add it for the duration of this script
  KC=(--keychain "$APPLE_KEYCHAIN")
  ORIG_KCS=$(security list-keychains -d user | tr -d '"' | xargs)
  security list-keychains -d user -s "$APPLE_KEYCHAIN" $ORIG_KCS
  trap 'security list-keychains -d user -s $ORIG_KCS' EXIT
fi

if [ -n "$ID" ]; then
  # Developer ID: hardened runtime + secure timestamp (both required for notarization)
  SIGN=(codesign --force --timestamp --options runtime "${KC[@]}" -s "$ID")
else
  SIGN=(codesign --force -s -)
fi

TMPDIR_SIGN=$(mktemp -d)
is_macho() { file -b "$1" | grep -q "Mach-O"; }

# sign_tree DIR: every Mach-O file, deepest paths first, then executables with entitlements
sign_tree() {
  local dir=$1 f n=0
  while IFS= read -r f; do
    is_macho "$f" || continue
    local extra=(); [ -x "$f" ] && file -b "$f" | grep -q "executable" && extra=(--entitlements "$ENT")
    "${SIGN[@]}" "${extra[@]}" "$f" 2>"$TMPDIR_SIGN/err" || { cat "$TMPDIR_SIGN/err" >&2; echo "signing failed: $f" >&2; exit 1; }
    n=$((n + 1))
  done < <(find "$dir" -type f ! -path "*/_CodeSignature/*" | awk -F/ '{print NF "\t" $0}' | sort -rn | cut -f2-)
  echo "signed $n Mach-O files under $dir ($([ -n "$ID" ] && echo "identity: $ID" || echo ad-hoc))"
}

notarize() {  # notarize FILE (zip/dmg)
  [ -n "${APPLE_NOTARY_PROFILE:-}" ] || return 0
  xcrun notarytool submit "$1" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait
}

case ${1:-} in
  payload)
    sign_tree "$2"
    codesign --verify --strict "$2"/pdftoepub 2>/dev/null || true
    ;;
  app)
    APP=$2; DMG=$3
    sign_tree "$APP/Contents"
    "${SIGN[@]}" --entitlements "$ENT" "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"
    if [ -n "$ID" ] && [ -n "${APPLE_NOTARY_PROFILE:-}" ]; then
      Z=$(mktemp -d)/pdftoepub.zip; ditto -c -k --keepParent "$APP" "$Z"
      notarize "$Z" && xcrun stapler staple "$APP"
    fi
    # DMG: the app + an /Applications shortcut, so users drag and drop
    S=$(mktemp -d); cp -R "$APP" "$S/"; ln -s /Applications "$S/Applications"
    rm -f "$DMG"
    hdiutil create -quiet -volname "pdftoepub" -srcfolder "$S" -fs HFS+ -format UDZO "$DMG"
    rm -rf "$S"
    if [ -n "$ID" ]; then
      codesign --force --timestamp "${KC[@]}" -s "$ID" "$DMG"
      if [ -n "${APPLE_NOTARY_PROFILE:-}" ]; then
        notarize "$DMG" && xcrun stapler staple "$DMG"
        spctl -a -vvv -t install "$DMG"; spctl -a -vvv "$APP"
      else
        echo "NOTE: signed but NOT notarized (APPLE_NOTARY_PROFILE unset): Gatekeeper will still warn on other Macs."
      fi
    else
      echo "NOTE: ad-hoc signature only (APPLE_SIGN_IDENTITY unset): on other Macs Gatekeeper says the app"
      echo "      cannot be verified; users must right-click > Open once (or: xattr -dr com.apple.quarantine pdftoepub.app)."
    fi
    ;;
  *) sed -n '2,16p' "$0"; exit 2;;
esac
