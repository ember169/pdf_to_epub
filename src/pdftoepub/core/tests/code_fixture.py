"""Generator for a PDF with prose, shell commands and code blocks (monospace detection tests)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

CODE = [
    "def scan(host, ports):",
    "    for p in ports:",
    "        if probe(host, p):",
    "            print('open', p)",
    "",
    "    return None",
]
SHELL = "$ nmap -sV -p- --min-rate 5000 10.10.10.5 -oN scan.txt"
HYPHEN_LINES = ["cat /etc/pass-", "wd | grep root"]
ALIGNED = "PORT    STATE  SERVICE"
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Courier New.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def mono_ttf() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def make(path: Path, aliased_font: bool = False) -> Path:
    """aliased_font=True draws the code in a TrueType monospace font registered under a neutral name ("Qx"),
    so only the fixed-advance check (not the font name) can identify it."""
    mono = "Courier"
    if aliased_font:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("Qx", mono_ttf()))
        mono = "Qx"
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4

    def prose(y, text, size=11):
        c.setFont("Times-Roman", size)
        c.drawString(72, y, text)
        return y - 15

    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, H - 90, "Enumeration notes")
    y = H - 130
    y = prose(y, "First we scan the target to see which services answer on the network.")
    y = prose(y, "The interesting part is the shell command that follows right below.")
    y -= 6
    c.setFont(mono, 10)
    c.drawString(90, y, SHELL)
    y -= 26
    y = prose(y, "Afterwards we run a small script to check every open port:")
    y -= 4
    c.setFont(mono, 10)
    for line in CODE:
        c.drawString(90, y, line)
        y -= 12.5
    y -= 14
    y = prose(y, "Line-end hyphens inside commands must survive untouched:")
    y -= 4
    c.setFont(mono, 10)
    for line in HYPHEN_LINES:
        c.drawString(90, y, line)
        y -= 12.5
    y -= 14
    c.setFont(mono, 10)
    c.drawString(90, y, ALIGNED)
    y -= 12.5
    c.drawString(90, y, "22/tcp  open   ssh")
    y -= 24
    # inline monospace inside a prose line
    c.setFont("Times-Roman", 11)
    c.drawString(72, y, "Use the")
    w = c.stringWidth("Use the ", "Times-Roman", 11)
    c.setFont(mono, 10)
    c.drawString(72 + w, y, "ls -la")
    w2 = c.stringWidth("ls -la", mono, 10)
    c.setFont("Times-Roman", 11)
    c.drawString(72 + w + w2 + 4, y, "command to list hidden files in the directory.")
    # code block continued on the next page
    y -= 40
    c.setFont(mono, 10)
    for i in range(3):
        c.drawString(90, 60 + 12.5 * (2 - i) if False else 80 + 12.5 * (2 - i), f"line_before_break_{i}")
    c.showPage()
    c.setFont(mono, 10)
    yy = H - 90
    for i in range(3):
        c.drawString(90, yy, f"line_after_break_{i}")
        yy -= 12.5
    c.setFont("Times-Roman", 11)
    c.drawString(72, yy - 20, "That is all for this chapter of the notes, thank you for reading.")
    c.showPage()
    c.save()
    return path
