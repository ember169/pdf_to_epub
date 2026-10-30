#!/usr/bin/env bash
# Exercise a RUNNING server with curl only (so it can run inside minimal containers too).
#   smoke_web.sh PORT FIXTURE_DIR OUT_DIR MODE
#   MODE ok       text PDF -> job done -> EPUB downloaded
#        ocr      scanned PDF -> job done with ocr_pages >= 1 -> EPUB downloaded (bundled tesseract, via the spawned job child)
#        pages    2-page PDF against a server with MAX_PAGES=1 -> error_code too_many_pages
#        timeout  scanned PDF against a server with JOB_TIMEOUT_S=0.2 -> error_code timeout
# Prints "RESULT PASS|FAIL <mode>: <detail>". The jobs run in a spawned child process, so ok/ocr/pages/timeout passing
# inside a frozen binary proves freeze_support()/spawn work there.
PORT=$1; FX=$2; OUT=$3; MODE=$4; B=localhost:$PORT
case $MODE in ok|pages) PDF=$FX/single_column.pdf;; ocr|timeout) PDF=$FX/scanned.pdf;; esac
for _ in $(seq 1 90); do curl -sf $B/healthz >/dev/null && break; sleep 1; done
for t in 1 2 3 4 5; do   # the first request after start-up can be reset under emulation
  R=$(curl -s -F "file=@$PDF" -F 'options={}' $B/api/jobs); id=$(echo "$R" | sed -n 's/.*"id":"\([0-9a-f]*\)".*/\1/p'); [ -n "$id" ] && break; sleep 3
done
[ -n "$id" ] || { echo "RESULT FAIL $MODE: upload gave '$R'"; exit 1; }
for _ in $(seq 1 120); do J=$(curl -s $B/api/jobs/$id); echo "$J" | grep -qE '"status":"(done|error)"' && break; sleep 1; done
case $MODE in
  ok|ocr)
    echo "$J" | grep -q '"status":"done"' || { echo "RESULT FAIL $MODE: $J"; exit 1; }
    [ $MODE = ocr ] && ! echo "$J" | grep -qE '"ocr_pages":[1-9]' && { echo "RESULT FAIL $MODE: no OCR pages: $J"; exit 1; }
    curl -sf -o "$OUT/web_$MODE.epub" $B/api/jobs/$id/download || { echo "RESULT FAIL $MODE: download"; exit 1; }
    echo "RESULT PASS $MODE";;
  pages)   echo "$J" | grep -q '"error_code":"too_many_pages"' && echo "RESULT PASS $MODE" || { echo "RESULT FAIL $MODE: $J"; exit 1; };;
  timeout) echo "$J" | grep -q '"error_code":"timeout"' && echo "RESULT PASS $MODE" || { echo "RESULT FAIL $MODE: $J"; exit 1; };;
esac
