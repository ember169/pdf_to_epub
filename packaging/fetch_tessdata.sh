#!/usr/bin/env bash
# Fetch tessdata_fast eng+fra (pinned commit, sha256-verified) into packaging/tessdata/.
# tessdata_fast: ~5 MB for both vs ~20 MB for 'best'; accuracy is a little lower but fine for clean scans, and it is faster.
set -euo pipefail
cd "$(dirname "$0")"
COMMIT=87416418657359cb625c412a48b6e1d6d41c29bd
mkdir -p tessdata
for l in eng fra; do
  [ -f tessdata/$l.traineddata ] || curl -fsSL -o tessdata/$l.traineddata \
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$COMMIT/$l.traineddata"
done
cat > tessdata/SHA256SUMS <<'EOS'
7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2  eng.traineddata
ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca  fra.traineddata
EOS
(cd tessdata && if command -v sha256sum >/dev/null; then sha256sum -c SHA256SUMS; else shasum -a 256 -c SHA256SUMS; fi)
