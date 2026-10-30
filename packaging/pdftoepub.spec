# PyInstaller spec. Build with packaging/build.sh (one-file executable; ONEDIR=1 for a faster-starting folder).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

hidden = (collect_submodules("pdftoepub") + collect_submodules("uvicorn") + collect_submodules("pdfminer")
          + collect_submodules("multipart") + collect_submodules("anyio"))
datas = collect_data_files("pdftoepub") + collect_data_files("pdfminer") + collect_data_files("pypdfium2") \
    + collect_data_files("pypdfium2_raw")
# bundled tesseract (prepared by build.sh / Dockerfile.linux into $TESS_DIR: tesseract[.exe], libs, tessdata/)
if os.environ.get("TESS_DIR"):
    datas += [(os.environ["TESS_DIR"], "tesseract")]
if os.environ.get("LICENSES_FILE"):
    datas += [(os.environ["LICENSES_FILE"], ".")]
binaries = collect_dynamic_libs("pypdfium2") + collect_dynamic_libs("pypdfium2_raw")

a = Analysis(
    ["entry.py"], pathex=["../src"], binaries=binaries, datas=datas, hiddenimports=hidden,
    # AGPL: keep PyMuPDF out so the binary stays MIT-clean
    excludes=["pymupdf", "fitz", "pymupdf4llm", "pymupdf_layout", "pdftoepub.core.backends.pymupdf_backend",
              "tkinter", "pytest",
              # uvicorn[standard] extras we do not use (asyncio/h11 fallbacks are fine); smaller = faster cold start
              "uvloop", "watchfiles", "httptools", "websockets", "yaml", "dotenv", "setuptools", "pkg_resources",
              "PIL._avif", "PIL._webp", "unittest", "pydoc", "doctest", "lib2to3"],
)
pyz = PYZ(a.pure)
if os.environ.get("ONEDIR"):
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pdftoepub", console=True, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="pdftoepub")
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="pdftoepub", console=True, upx=False)
