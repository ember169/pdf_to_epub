"""Write THIRD_PARTY_LICENSES from the installed package metadata + fixed entries for bundled non-Python parts.
Usage: python gen_licenses.py OUT [--tesseract]"""
import sys
from importlib import metadata

FIXED_TESS = """\
== Tesseract OCR (bundled executable) ==
Apache License 2.0 - https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE
== Leptonica and image libraries linked by Tesseract (libpng, libjpeg, libtiff, zlib, libwebp, openjpeg, giflib, ...) ==
Leptonica: BSD 2-clause - https://github.com/DanBloomberg/leptonica/blob/master/leptonica-license.txt
The other libraries keep their own permissive licenses (libpng, IJG/BSD, libtiff, zlib, BSD-3, MIT-like).
macOS builds: tesseract/LICENSES.txt next to the executable holds the full Tesseract, Leptonica and libpng texts.
== tessdata_fast eng/fra traineddata ==
Apache License 2.0 - https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE
"""
FIXED = """\
== Python runtime (embedded by PyInstaller) ==
Python Software Foundation License - https://docs.python.org/3/license.html
== PyInstaller bootloader ==
GPL-2.0-or-later with the bootloader exception that permits use in non-GPL applications - https://pyinstaller.org/en/stable/license.html
== PDFium (via pypdfium2) ==
Apache-2.0 / BSD-3-Clause - https://pdfium.googlesource.com/pdfium/+/main/LICENSE
== wordfreq 3.2 word-frequency data (large_fr, large_en; pdftoepub/core/data/wordfreq, unmodified) ==
Data: CC BY-SA 4.0 - https://creativecommons.org/licenses/by-sa/4.0/ ; code: Apache-2.0 - https://github.com/rspeer/wordfreq/blob/v3.2/LICENSE.txt
By Robyn Speer, https://github.com/rspeer/wordfreq (commit 42233e6). Contains data from Google Books Ngrams (http://books.google.com/ngrams), OPUS OpenSubtitles 2018 (attribution to OpenSubtitles, http://www.opensubtitles.org/), SUBTLEX by Marc Brysbaert et al. (freely available data), Wikipedia, the Leeds Internet Corpus and ParaCrawl. Full notice: pdftoepub/core/data/wordfreq/NOTICE.txt
"""


def main(out, tess):
    parts = ["pdftoepub is MIT licensed. It bundles the following third-party software.\n\n", FIXED]
    if tess:
        parts.append(FIXED_TESS)
    parts.append("\n== Python packages ==\n")
    for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = d.metadata["Name"]
        if not name or name.lower() in ("pip", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "macholib",
                                        "packaging", "setuptools", "wheel", "pefile", "pywin32-ctypes"):
            continue
        lic = d.metadata.get("License-Expression") or d.metadata.get("License") or ""
        lic = lic.splitlines()[0][:120] if lic else ""
        if not lic:
            lic = "; ".join(c.split("::")[-1].strip() for c in d.metadata.get_all("Classifier") or [] if c.startswith("License ::")) or "see package"
        parts.append(f"{name} {d.version}: {lic}\n")
        for f in d.files or []:
            if f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")) and "dist-info" in str(f):
                try:
                    parts.append("    ---- " + f.name + " ----\n" + f.locate().read_text(encoding="utf-8", errors="replace") + "\n")
                except Exception:
                    pass
                break
    open(out, "w").write("".join(parts))


main(sys.argv[1], "--tesseract" in sys.argv)
