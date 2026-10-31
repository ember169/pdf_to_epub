#!/usr/bin/env bash
# Authenticode-sign the Windows .exe locally with osslsigncode (brew install osslsigncode), with an RFC 3161 timestamp.
#
#   sign_windows.sh [EXE]          default EXE: dist/pdf_to_epub-windows-x86_64.exe (signed in place)
#
# Environment:
#   WIN_SIGN_PFX        path to a .pfx/.p12 holding the code-signing certificate + private key (OV certificate).
#   WIN_SIGN_PASSWORD   its password (read from the environment, never put on the command line or in a file).
#   WIN_SIGN_TSA        timestamp server (default http://timestamp.digicert.com; any RFC 3161 TSA works).
#   WIN_SIGN_CAFILE     optional: CA bundle for the verification step (needed for a self-signed test certificate).
# Not covered: EV certificates on hardware tokens (osslsigncode can use them via -pkcs11engine/-pkcs11module) and
# Azure Trusted Signing (needs Microsoft's signtool/dlib on Windows).
set -euo pipefail
cd "$(dirname "$0")/.."
EXE=${1:-dist/pdf_to_epub-windows-x86_64.exe}
TSA=${WIN_SIGN_TSA:-http://timestamp.digicert.com}
command -v osslsigncode >/dev/null || { echo "need osslsigncode (brew install osslsigncode)"; exit 1; }
[ -f "$EXE" ] || { echo "no such file: $EXE"; exit 1; }
if [ -z "${WIN_SIGN_PFX:-}" ]; then
  echo "NOTE: WIN_SIGN_PFX unset: $EXE stays unsigned. Windows SmartScreen will show 'Windows protected your PC'"
  echo "      (More info > Run anyway)."
  exit 0
fi
: "${WIN_SIGN_PASSWORD:?WIN_SIGN_PASSWORD must be set}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
PASSFILE=$TMP/pass; (umask 077; printf '%s' "$WIN_SIGN_PASSWORD" > "$PASSFILE")   # never on the command line
osslsigncode sign -pkcs12 "$WIN_SIGN_PFX" -readpass "$PASSFILE" \
  -n "pdf_to_epub" -h sha256 -ts "$TSA" \
  -in "$EXE" -out "$TMP/signed.exe"
mv "$TMP/signed.exe" "$EXE"
echo "signed: $EXE"
VERIFY=(osslsigncode verify -in "$EXE"); [ -n "${WIN_SIGN_CAFILE:-}" ] && VERIFY+=(-CAfile "$WIN_SIGN_CAFILE" -TSA-CAfile /etc/ssl/cert.pem)
"${VERIFY[@]}"
