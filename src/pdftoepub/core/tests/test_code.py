import re
import zipfile

import pytest
from lxml import etree

from pdftoepub.api import convert
from pdftoepub.core import structure
from pdftoepub.core.backends.common import style_from_name
from pdftoepub.core.ir import Line, Paragraph, Run, Span
from pdftoepub.core.tests import code_fixture

XHTML = "{http://www.w3.org/1999/xhtml}"


@pytest.mark.parametrize("name,mono", [
    ("ABCDEF+Courier", True), ("CourierNewPSMT", True), ("DejaVuSansMono", True), ("UbuntuMono-Regular", True),
    ("SourceCodePro-Regular", True), ("Hack-Regular", True), ("Consolas", True), ("Menlo-Regular", True),
    ("FiraCode-Retina", True), ("JetBrainsMono-Bold", True), ("Inconsolata", True), ("LiberationMono", True),
    ("Code-Regular", True),
    ("ArialUnicodeMS", False), ("Barcode128", False), ("Times-Roman", False), ("Helvetica-Bold", False), ("Hackney-Roman", False),
])
def test_monospace_font_names(name, mono):
    assert style_from_name(name)[2] is mono


def _line(x0, y0, text, size=10.0, mono=True, w=6.0):
    x1 = x0 + w * len(text)
    return Line([Span(text, size, mono=mono, bbox=(x0, y0, x1, y0 + 12))], (x0, y0, x1, y0 + 12))


def test_pre_text_keeps_indentation_and_blank_lines():
    lines = [_line(90, 100, "if x:"), _line(114, 112, "run()"), _line(90, 137, "done")]  # 2nd gap = one blank line
    assert structure._pre_text(lines) == "if x:\n    run()\n\ndone"


def test_code_blocks_split_by_page_break_are_merged():
    a = Paragraph([Run("a\nb", mono=True)], "pre", 1, 700, None, False, 10.0, y1=760)
    b = Paragraph([Run("c", mono=True)], "pre", 2, 80, "page", False, 10.0, y1=92)
    far = Paragraph([Run("z", mono=True)], "pre", 2, 400, None, False, 10.0, y1=412)
    out = structure.merge_code_blocks([a, b, far])
    assert len(out) == 2 and out[0].runs[0].text == "a\nb\nc"


def convert_fixture(tmp_path, aliased=False):
    pdf = code_fixture.make(tmp_path / "code.pdf", aliased)
    res = convert(pdf, tmp_path / "code.epub")
    z = zipfile.ZipFile(tmp_path / "code.epub")
    roots = [etree.fromstring(z.read(n)) for n in sorted(z.namelist()) if re.match(r"OEBPS/ch\d+\.xhtml", n)]
    return z, roots, res


def check_code_output(z, roots):
    pres = [e for r in roots for e in r.iter(XHTML + "pre")]
    texts = ["".join(p.itertext()) for p in pres]
    assert all(p.find(XHTML + "code") is not None for p in pres)  # <pre><code>
    joined = "\n=====\n".join(texts)
    assert SHELL_RE.search(joined)
    # block with indentation and blank line preserved verbatim
    assert "def scan(host, ports):\n    for p in ports:\n        if probe(host, p):\n            print('open', p)\n\n    return None" in joined
    # hyphen at the end of a code line is kept, lines are not joined
    assert "cat /etc/pass-\nwd | grep root" in joined
    # column alignment kept
    assert "PORT    STATE  SERVICE" in joined
    # block continued over a page break is one <pre>
    assert "line_before_break_2\nline_after_break_0" in joined or "line_before_break_2\n\nline_after_break_0" in joined
    # prose stays prose
    paras = " ".join("".join(p.itertext()) for r in roots for p in r.iter(XHTML + "p"))
    assert "First we scan the target" in paras and "That is all for this chapter" in paras
    assert "def scan" not in paras and "nmap" not in paras
    # inline monospace -> <code> inside a <p>
    inline = [c for r in roots for p in r.iter(XHTML + "p") for c in p.iter(XHTML + "code")]
    assert any("ls -la" in "".join(c.itertext()) and (c.tail or "").startswith(" command") for c in inline)
    assert not [h for r in roots for h in r.iter(XHTML + "h2")]  # the lone heading is the chapter title, not duplicated
    css = z.read("OEBPS/style.css").decode()
    pre_rule = re.search(r"\npre\s*\{[^}]*\}", css).group(0)
    assert "white-space: pre-wrap" in pre_rule and "overflow-wrap: anywhere" in pre_rule
    assert not re.search(r"\d\s*(px|pt)\b", css)


SHELL_RE = re.compile(r"\$ nmap -sV -p- --min-rate 5000 10\.10\.10\.5 -oN scan\.txt")


def test_code_blocks_and_inline_code(tmp_path):
    z, roots, _ = convert_fixture(tmp_path)
    check_code_output(z, roots)


@pytest.mark.skipif(code_fixture.mono_ttf() is None, reason="no monospace TrueType font on this machine")
def test_monospace_detected_from_advance_widths_not_names(tmp_path, backend):
    if backend != "pdfminer":
        pytest.skip("fixed-advance check needs per-glyph advances (pdfminer backend)")
    z, roots, _ = convert_fixture(tmp_path, aliased=True)
    check_code_output(z, roots)
