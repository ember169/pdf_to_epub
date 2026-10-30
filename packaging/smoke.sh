#!/usr/bin/env bash
# Smoke-test every binary in dist/ in a clean environment, then regenerate dist/SHA256SUMS.
#   macOS: CLI (arm64 natively, x86_64 under Rosetta) under `env -i`, and each .app from its .dmg via `open`           Linux binaries: clean debian:11-slim and ubuntu:20.04 containers (no Python/tesseract)
#   Windows .exe: under Wine in Docker (needs the pte-winbase image: packaging/build.sh windows builds it)
# Per binary: multiprocessing spawn; CLI text conversion; CLI OCR of the scanned fixture with no system tesseract;
# no-argument launch starts the server (browser opening disabled via BROWSER=true); and with `serve`:
#   upload+poll+download, OCR through a web job, MAX_PAGES=1 -> too_many_pages, JOB_TIMEOUT_S=0.2 -> timeout
#   (jobs run in a spawned child process, so these prove freeze_support()/spawn work inside the frozen binary).
# Finally every EPUB produced is validated with epubcheck in the Docker test image (if built: see deploy/Dockerfile).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD; DIST=$ROOT/dist; W=$ROOT/build/smoke; rm -rf "$W"; mkdir -p "$W/fx" "$W/out"
PY=$ROOT/.venv/bin/python; [ -x "$PY" ] || PY=python3
"$PY" tests/fixtures/make_fixtures.py "$W/fx" >/dev/null || { echo "cannot generate fixtures (need reportlab, pypdfium2)"; exit 1; }
FAIL=0; pass() { echo "  PASS $*"; }; fail() { echo "  FAIL $*"; FAIL=1; }
BR="BROWSER=true"   # webbrowser.open() runs `true`: nothing opens

check_epub() { "$PY" -I - "$1" "$2" <<'PYEOF'
import re, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
assert z.namelist()[0] == "mimetype"
t = " ".join(re.sub("<[^>]+>", " ", z.read(n).decode()) for n in z.namelist() if n.endswith(".xhtml"))
sys.exit(0 if sys.argv[2] in re.sub(r"\s+", " ", t) else 1)
PYEOF
}
# result_of PREFIX OUTPUT-LINES: report RESULT lines emitted by smoke_web.sh
report_results() {  # $1 = label prefix ; stdin = smoke_web output
  while read -r l; do
    case $l in "RESULT PASS "*) pass "$1 ${l#RESULT PASS }";; "RESULT FAIL "*) fail "$1 ${l#RESULT FAIL }";; esac
  done
}
check_web_epubs() {  # $1 = file prefix in out/
  [ -f "$W/out/$1_ok.epub" ] && { check_epub "$W/out/$1_ok.epub" "The quick brown fox" && pass "web epub text" || fail "web epub text"; }
  [ -f "$W/out/$1_ocr.epub" ] && { check_epub "$W/out/$1_ocr.epub" "Optical character recognition" && pass "web epub OCR text" || fail "web epub OCR text"; }
}
# scan_log_ok FILE: chapters <= 2 on the scanned fixture, and no pdfium "potentially unsafe" noise on stderr
scan_log_ok() {
  local n; n=$(sed -n 's/.*[( ]\([0-9][0-9]*\) chapters.*/\1/p' "$1" | tail -1)
  if [ -n "$n" ] && [ "$n" -le 2 ] && ! grep -qi "potentially unsafe" "$1"; then pass "scanned: $n chapter(s), no 'potentially unsafe' output"; else fail "scanned: chapters='$n' or unsafe-noise ($(grep -ci 'potentially unsafe' "$1"))"; fi
}
# scenarios: "ENV...:modes"
SCEN_DEFAULT="ok ocr"; SCEN_PAGES="pages"; SCEN_TIMEOUT="timeout"

skip() { echo "  SKIP $*"; }

test_macos() {  # $1 = arm64 | x86_64 (x86_64 runs under Rosetta on Apple silicon)
  local a=${1:-arm64} bin T; bin=$DIST/pdftoepub-macos-$a; [ -x "$bin" ] || return 0
  [ "$a" = x86_64 ] && ! arch -x86_64 /usr/bin/true 2>/dev/null && { echo "== macOS x86_64: skipped (no Rosetta)"; return 0; }
  echo "== macOS $a CLI$([ "$a" = x86_64 ] && echo " under Rosetta") (env -i, no venv, no tesseract on PATH)"
  T=$(mktemp -d); cp "$bin" "$T/p"
  local P=mac_$a
  run() { env -i HOME="$T" PATH=/usr/bin:/bin "$BR" arch "-$a" "$@"; }
  [ "$(run "$T/p" --_spawn 2>&1 | tail -1)" = "spawn ok: 32" ] && pass "multiprocessing spawn" || fail "multiprocessing spawn"
  run "$T/p" "$W/fx/single_column.pdf" -o "$W/out/${P}_text.epub" -q >/dev/null 2>&1 && check_epub "$W/out/${P}_text.epub" "The quick brown fox" && pass "CLI text" || fail "CLI text"
  local ocr=1; run "$T/p" --_diag 2>&1 | head -1 | grep -q "/tesseract/tesseract" || ocr=0
  run "$T/p" "$W/fx/scanned.pdf" -o "$W/out/${P}_scan.epub" -q > "$W/out/${P}_scan.log" 2>&1; scan_log_ok "$W/out/${P}_scan.log"
  if [ $ocr = 1 ]; then
    grep -q "1 OCR" "$W/out/${P}_scan.log" && check_epub "$W/out/${P}_scan.epub" "Optical character recognition" && pass "CLI OCR (bundled tesseract)" || fail "CLI OCR"
  else skip "CLI OCR: this build has no bundled tesseract (see packaging/build_tesseract_macos.sh)"; fi
  run "$T/p" > "$T/noarg.log" 2>&1 & local pid=$! url="" port
  for _ in $(seq 1 60); do url=$(grep -o 'http://127.0.0.1:[0-9]*' "$T/noarg.log" | head -1); [ -n "$url" ] && break; sleep 1; done
  port=${url##*:}; [ -n "$port" ] && for _ in $(seq 1 60); do curl -sf "localhost:$port/healthz" >/dev/null && break; sleep 1; done
  [ -n "$port" ] && curl -sf "localhost:$port/healthz" >/dev/null && pass "no-argument launch serves ($url)" || fail "no-argument launch"
  pkill -P $pid 2>/dev/null; kill $pid 2>/dev/null; wait $pid 2>/dev/null
  local n=0 sc
  for sc in "X=1|ok$([ $ocr = 1 ] && echo " ocr")" "MAX_PAGES=1|$SCEN_PAGES" "JOB_TIMEOUT_S=0.2|$SCEN_TIMEOUT"; do
    n=$((n+1)); local envs=${sc%%|*} modes=${sc##*|} port=$((18090+n))
    run env "$envs" "$T/p" serve --port $port >/dev/null 2>&1 & pid=$!
    for m in $modes; do "$ROOT/packaging/smoke_web.sh" $port "$W/fx" "$W/out" $m | report_results "web[$envs] "; done
    pkill -P $pid 2>/dev/null; kill $pid 2>/dev/null; wait $pid 2>/dev/null
  done
  mv "$W/out/web_ok.epub" "$W/out/${P}_web_ok.epub" 2>/dev/null; mv "$W/out/web_ocr.epub" "$W/out/${P}_web_ocr.epub" 2>/dev/null
  check_web_epubs ${P}_web
  test_macos_app "$a" $ocr
}

test_macos_app() {  # $1 arch, $2 ocr(0/1): mount the .dmg, launch the .app with `open` (no Terminal), use it, stop it
  local a=$1 ocr=$2 dmg=$DIST/pdftoepub-macos-$1.dmg mnt T port pid
  [ -f "$dmg" ] || return 0
  echo "== macOS $a .app from the .dmg (open -n, BROWSER=true)"
  T=$(mktemp -d); mnt=$(hdiutil attach -nobrowse -readonly -noautoopen "$dmg" | awk -F'\t' '/\/Volumes\//{print $NF}' | tail -1)
  [ -d "$mnt/pdftoepub.app" ] && [ -L "$mnt/Applications" ] && pass "dmg contains pdftoepub.app + Applications link" || fail "dmg layout"
  cp -R "$mnt/pdftoepub.app" "$T/"; hdiutil detach -quiet "$mnt"
  codesign --verify --deep --strict "$T/pdftoepub.app" 2>/dev/null && pass "app signature valid ($(codesign -dv "$T/pdftoepub.app" 2>&1 | sed -n 's/^Authority=//p;s/^Signature=//p' | head -1))" || fail "app signature"
  [ "$(lipo -archs "$T/pdftoepub.app/Contents/MacOS/pdftoepub")" = "$a" ] && pass "app architecture $a" || fail "app architecture"
  pkill -f "pdftoepub.app/Contents/MacOS/pdftoepub" 2>/dev/null; sleep 1
  open -n --env "$BR" --env "DATA_DIR=$T/data" "$T/pdftoepub.app"
  for _ in $(seq 1 90); do port=$(lsof -nP -a -c pdftoepub -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | head -1); [ -n "$port" ] && break; sleep 1; done
  port=${port##*:}
  [ -n "$port" ] && pass "app started its server by itself (port $port)" || fail "app did not start a server"
  if [ -n "$port" ]; then
    "$ROOT/packaging/smoke_web.sh" "$port" "$W/fx" "$W/out" ok | report_results "app web "
    [ "$ocr" = 1 ] && "$ROOT/packaging/smoke_web.sh" "$port" "$W/fx" "$W/out" ocr | report_results "app web "
    mv "$W/out/web_ok.epub" "$W/out/app_${a}_web_ok.epub" 2>/dev/null; mv "$W/out/web_ocr.epub" "$W/out/app_${a}_web_ocr.epub" 2>/dev/null
  fi
  local pids; pids=$(pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" | tr '\n' ' ')
  [ -f "$T/data/desktop.json" ] && pass "desktop.json written ($(tr -d '\n' < "$T/data/desktop.json"))" || fail "desktop.json missing"
  [ -s "$T/data/desktop.log" ] && pass "desktop.log written" || fail "desktop.log missing"
  curl -s "localhost:$port/api/config" | grep -q '"desktop":true' && pass "desktop mode reported by /api/config" || fail "desktop flag"
  # single instance: a second launch must hand over to the running server and exit, not start another one
  open -n --env "$BR" --env "DATA_DIR=$T/data" "$T/pdftoepub.app"; sleep 8
  [ "$(lsof -nP -a -c pdftoepub -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1' | wc -l | tr -d ' ')" = 1 ] \
    && [ "$(pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" | wc -l | tr -d ' ')" = "$(echo $pids | wc -w | tr -d ' ')" ] \
    && pass "second launch reused the running instance" || fail "second launch started another server"
  # the guard must refuse a shutdown request without the front's header
  [ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "localhost:$port/api/shutdown")" != 202 ] && pass "shutdown refused without X-Requested-With" || fail "unguarded shutdown"
  # Quit, as the web UI's button does
  [ "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'X-Requested-With: pdftoepub' -H "Origin: http://127.0.0.1:$port" "http://127.0.0.1:$port/api/shutdown")" = 202 ] \
    && pass "POST /api/shutdown accepted" || fail "shutdown request"
  for _ in $(seq 1 20); do pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" >/dev/null || break; sleep 0.5; done
  pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" >/dev/null && { fail "app still running after shutdown"; pkill -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub"; } || pass "app exited after Quit"
  [ ! -f "$T/data/desktop.json" ] && pass "desktop.json removed on exit" || fail "stale desktop.json"
  # idle auto-exit (IDLE_EXIT_MIN=0.2 -> 12 s): pinging like an open page keeps it alive; once the "page" is closed it exits
  open -n --env "$BR" --env "DATA_DIR=$T/data" --env IDLE_EXIT_MIN=0.2 "$T/pdftoepub.app"
  port=""; for _ in $(seq 1 60); do port=$(lsof -nP -a -c pdftoepub -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | head -1); [ -n "$port" ] && break; sleep 1; done
  port=${port##*:}
  for _ in $(seq 1 10); do curl -s -o /dev/null "localhost:$port/api/ping"; sleep 3; done   # 30 s of heartbeats
  pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" >/dev/null && pass "idle: alive while the page pings (30 s > 12 s limit)" || fail "idle: exited despite activity"
  local t0=$SECONDS; for _ in $(seq 1 60); do pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" >/dev/null || break; sleep 1; done
  pgrep -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub" >/dev/null && { fail "idle: still running 60 s after the last request"; pkill -f "$T/pdftoepub.app/Contents/MacOS/pdftoepub"; } \
    || pass "idle: exited $((SECONDS - t0)) s after the last request (limit 12 s)"
  grep -q "no activity" "$T/data/desktop.log" && pass "idle exit logged in desktop.log" || fail "idle exit not logged"
}

test_linux() {  # $1 = arm64|x86_64
  local a=$1 plat=linux/arm64 bin; [ "$a" = x86_64 ] && plat=linux/amd64; bin=pdftoepub-linux-$a
  [ -x "$DIST/$bin" ] || return 0
  for img in debian:11-slim ubuntu:20.04; do
    echo "== linux-$a on $img (no python, no tesseract)"; local tag=${img//[:.]/_}
    docker run --rm --platform $plat -v "$DIST:/dist:ro" -v "$W:/w" "$img" bash -c '
      command -v tesseract python3 >/dev/null && echo "SYSTEM TOOLS PRESENT"; cp /dist/'$bin' /tmp/p
      /tmp/p --_spawn 2>&1 | tail -1 > /w/out/lin_'$a'_'$tag'.spawn
      /tmp/p /w/fx/single_column.pdf -o /w/out/lin_'$a'_'$tag'_text.epub -q >/dev/null 2>&1
      /tmp/p /w/fx/scanned.pdf -o /w/out/lin_'$a'_'$tag'_scan.epub -q > /w/out/lin_'$a'_'$tag'.scanlog 2>&1; grep -c "1 OCR" /w/out/lin_'$a'_'$tag'.scanlog > /w/out/lin_'$a'_'$tag'.ocr
      # no-argument launch: look for the printed URL, then GET /healthz through bash /dev/tcp
      BROWSER=true /tmp/p > /tmp/noarg.log 2>&1 &
      for i in $(seq 1 40); do u=$(grep -o "http://127.0.0.1:[0-9]*" /tmp/noarg.log | head -1); [ -n "$u" ] && break; sleep 1; done
      p=${u##*:}; sleep 2; exec 3<>/dev/tcp/127.0.0.1/$p && printf "GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n" >&3 && cat <&3 | grep -q "\"ok\":true" && echo ok > /w/out/lin_'$a'_'$tag'.noarg
    ' 2>&1 | grep -v "^$"
    [ "$(cat "$W/out/lin_${a}_${tag}.spawn")" = "spawn ok: 32" ] && pass "multiprocessing spawn" || fail "multiprocessing spawn"
    check_epub "$W/out/lin_${a}_${tag}_text.epub" "The quick brown fox" && pass "CLI text" || fail "CLI text"
    scan_log_ok "$W/out/lin_${a}_${tag}.scanlog"
    [ "$(cat "$W/out/lin_${a}_${tag}.ocr")" = 1 ] && check_epub "$W/out/lin_${a}_${tag}_scan.epub" "Optical character recognition" && pass "CLI OCR (bundled tesseract)" || fail "CLI OCR"
    [ "$(cat "$W/out/lin_${a}_${tag}.noarg" 2>/dev/null)" = ok ] && pass "no-argument launch serves" || fail "no-argument launch"
  done
  echo "== linux-$a serve scenarios (debian:11-slim container, host curl)"
  local n=0 sc
  for sc in "X=1|$SCEN_DEFAULT" "MAX_PAGES=1|$SCEN_PAGES" "JOB_TIMEOUT_S=0.2|$SCEN_TIMEOUT"; do
    n=$((n+1)); local envs=${sc%%|*} modes=${sc##*|} port=$((18100+n)) cid
    cid=$(docker run -d --rm --platform $plat -p $port:8000 -e "$envs" -v "$DIST:/dist:ro" debian:11-slim sh -c 'cp /dist/'$bin' /tmp/p; exec /tmp/p serve --host 0.0.0.0 --port 8000')
    for m in $modes; do "$ROOT/packaging/smoke_web.sh" $port "$W/fx" "$W/out" $m | report_results "web[$envs] "; done
    docker rm -f "$cid" >/dev/null 2>&1
  done
  mv "$W/out/web_ok.epub" "$W/out/lin_${a}_web_ok.epub" 2>/dev/null; mv "$W/out/web_ocr.epub" "$W/out/lin_${a}_web_ocr.epub" 2>/dev/null
  check_web_epubs lin_${a}_web
}

test_windows() {
  local bin=$DIST/pdftoepub-windows-x86_64.exe; [ -f "$bin" ] || return 0
  docker image inspect pte-winbase >/dev/null 2>&1 || { echo "== windows: skipped (pte-winbase image missing, see header)"; return 0; }
  echo "== windows-x86_64 .exe under Wine (Docker, linux/amd64)"
  # Rosetta/QEMU sometimes kills a Wine process ("xsave_header" assertion), so each phase gets retries.
  local WS='export WINEDEBUG=-all WINEPREFIX=/wine BROWSER=cmd.exe; cd /tmp; cp /dist/pdftoepub-windows-x86_64.exe p.exe'
  docker run --rm --platform linux/amd64 -v "$DIST:/dist:ro" -v "$W:/w" pte-winbase bash -c "$WS"'
    for t in 1 2 3; do wine p.exe --_spawn 2>&1 | tail -1 > /w/out/win.spawn; grep -q "spawn ok" /w/out/win.spawn && break; done
    wine p.exe Z:/w/fx/single_column.pdf -o Z:/w/out/win_text.epub -q >/dev/null 2>&1
    for t in 1 2 3; do wine p.exe Z:/w/fx/scanned.pdf -o Z:/w/out/win_scan.epub -q 2>&1 | cat > /w/out/win.scanlog; grep -q chapters /w/out/win.scanlog && break; done; grep -c "1 OCR" /w/out/win.scanlog > /w/out/win.ocr
    (tail -f /dev/null | wine p.exe 2>&1 | cat > /tmp/noarg.log &)
    for i in $(seq 1 60); do u=$(grep -o "http://127.0.0.1:[0-9]*" /tmp/noarg.log | head -1); [ -n "$u" ] && break; sleep 1; done
    p=${u##*:}; for i in $(seq 1 30); do curl -sf localhost:$p/healthz >/dev/null && echo ok > /w/out/win.noarg && break; sleep 1; done' >/dev/null 2>&1
  [ "$(tr -d '\r' < "$W/out/win.spawn" 2>/dev/null)" = "spawn ok: 32" ] && pass "multiprocessing spawn" || fail "multiprocessing spawn"
  check_epub "$W/out/win_text.epub" "The quick brown fox" && pass "CLI text" || fail "CLI text"
  tr -d '\r' < "$W/out/win.scanlog" > "$W/out/win.scanlog2" 2>/dev/null; grep -v "assertion failed\|rt_sigreturn" "$W/out/win.scanlog2" > "$W/out/win.scanlog3"; scan_log_ok "$W/out/win.scanlog3"
  [ "$(cat "$W/out/win.ocr" 2>/dev/null)" = 1 ] && check_epub "$W/out/win_scan.epub" "Optical character recognition" && pass "CLI OCR (bundled Windows tesseract)" || fail "CLI OCR"
  [ "$(cat "$W/out/win.noarg" 2>/dev/null)" = ok ] && pass "no-argument launch serves" || fail "no-argument launch"
  local sc n=0
  for sc in "X=1|$SCEN_DEFAULT" "MAX_PAGES=1|$SCEN_PAGES" "JOB_TIMEOUT_S=0.2|$SCEN_TIMEOUT"; do
    n=$((n+1)); local envs=${sc%%|*} modes=${sc##*|} got=0 attempt
    for attempt in 1 2 3 4 5 6 7 8; do
      docker run --rm --platform linux/amd64 -v "$DIST:/dist:ro" -v "$W:/w" -v "$ROOT/packaging:/pk:ro" pte-winbase bash -c "$WS"'
        export '"$envs"'
        (tail -f /dev/null | wine p.exe serve --port 18083 2>&1 | cat > /tmp/serve.log &)
        for m in '"$modes"'; do /pk/smoke_web.sh 18083 /w/fx /w/out $m; done' 2>/dev/null | grep "^RESULT" > "$W/out/win_res_$n.txt"
      grep -q "^RESULT" "$W/out/win_res_$n.txt" && ! grep -q "upload gave" "$W/out/win_res_$n.txt" && ! grep -q FAIL "$W/out/win_res_$n.txt" && { got=1; break; }
      echo "  (windows web[$envs] attempt $attempt failed, retrying)"
    done
    report_results "web[$envs] " < "$W/out/win_res_$n.txt"
    [ -f "$W/out/web_ok.epub" ] && mv "$W/out/web_ok.epub" "$W/out/win_web_ok.epub"; [ -f "$W/out/web_ocr.epub" ] && mv "$W/out/web_ocr.epub" "$W/out/win_web_ocr.epub"
  done
  check_web_epubs win_web
}

epubcheck_all() {
  docker image inspect pdftoepub-test >/dev/null 2>&1 || { echo "== epubcheck: skipped (build the test image: docker build -f deploy/Dockerfile --target test -t pdftoepub-test .)"; return 0; }
  echo "== epubcheck on every EPUB produced above (Docker test image)"
  local out; out=$(docker run --rm -i -v "$W/out:/o:ro" pdftoepub-test python - <<'PYEOF'
import sys, pathlib, tempfile
sys.path.insert(0, "tests"); import epubcheck
bad = 0
for f in sorted(pathlib.Path("/o").glob("*.epub")):
    errs = epubcheck.check(f, pathlib.Path(tempfile.mkdtemp()))
    print(("OK   " if not errs else "ERR  ") + f.name, errs[:2] if errs else "")
    bad += bool(errs)
print("EPUBCHECK_BAD", bad)
PYEOF
)
  echo "$out" | sed 's/^/  /'
  echo "$out" | grep -q "EPUBCHECK_BAD 0" && pass "epubcheck clean" || fail "epubcheck"
}

# ONLY=windows|macos|linux limits the run (debugging); default runs everything
case "${ONLY:-all}" in
  windows) test_windows;; macos) test_macos arm64; test_macos x86_64;; linux) test_linux arm64; test_linux x86_64;;
  *) test_windows; test_macos arm64; test_macos x86_64; test_linux arm64; test_linux x86_64; epubcheck_all;;
esac
(cd "$DIST" && : > SHA256SUMS && for f in pdftoepub-*; do case $f in *.zip|*-dir) ;; *) shasum -a 256 "$f" >> SHA256SUMS;; esac; done; echo; cat SHA256SUMS)
[ $FAIL = 0 ] && echo "ALL SMOKE TESTS PASSED" || { echo "SOME SMOKE TESTS FAILED"; exit 1; }
