# UNTESTED on real Windows (the supported path is `packaging/build.sh windows`, which builds under Wine in Docker and
# bundles Tesseract). This native script builds the same exe WITHOUT bundled OCR unless you pass -TessDir <folder
# containing tesseract.exe, its DLLs and tessdata\>.
param([string]$TessDir = "")
# Requires Python 3.12+ on PATH. Run from PowerShell:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
Remove-Item -Recurse -Force packaging\.buildvenv, build -ErrorAction SilentlyContinue
python -m venv packaging\.buildvenv
$v = "packaging\.buildvenv\Scripts"
& "$v\python" -m pip install -q --upgrade pip
& "$v\python" -m pip install -q . pyinstaller
& "$v\python" -I -c "import importlib.util as u,sys; sys.exit(1 if u.find_spec('pymupdf') else 0)"
if ($LASTEXITCODE -ne 0) { throw "pymupdf present in build venv (AGPL); refusing" }
if ($TessDir) { $env:TESS_DIR = (Resolve-Path $TessDir).Path }
Push-Location packaging
& "..\$v\pyinstaller" --noconfirm --clean --distpath ..\build\out --workpath ..\build\work pdftoepub.spec
Pop-Location
New-Item -ItemType Directory -Force dist | Out-Null
Move-Item -Force build\out\pdftoepub.exe dist\pdftoepub-windows-x86_64.exe
$list = & "$v\pyi-archive_viewer" -l -r dist\pdftoepub-windows-x86_64.exe
if (($list | Measure-Object).Count -lt 100 -or ($list | Select-String -Pattern "pymupdf|fitz")) { throw "PyMuPDF found or archive unreadable" }
Remove-Item -Recurse -Force build
$h = (Get-FileHash dist\pdftoepub-windows-x86_64.exe -Algorithm SHA256).Hash.ToLower()
"$h  pdftoepub-windows-x86_64.exe" | Add-Content dist\SHA256SUMS-windows.txt
Get-Content dist\SHA256SUMS-windows.txt
