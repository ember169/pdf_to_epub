"""Hand-written EPUB 3 packager (zipfile + string templates). All CSS lengths are relative (em / %)."""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .ir import Chapter, Document, Figure, Footnote, Heading, ListBlock, Paragraph, Run, Table

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"

CSS = """\
/* Reflowable stylesheet: relative units only; the body font size is left to the reading system. */
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; padding: 0 0.4em; line-height: 1.5; overflow-wrap: break-word; }
h1, h2, h3, h4 { line-height: 1.25; font-weight: bold; page-break-after: avoid; break-after: avoid; }
h1 { font-size: 1.7em; margin: 1.4em 0 0.8em 0; }
h2 { font-size: 1.4em; margin: 1.3em 0 0.6em 0; }
h3 { font-size: 1.2em; margin: 1.2em 0 0.5em 0; }
h4 { font-size: 1.05em; margin: 1.1em 0 0.4em 0; }
p { margin: 0 0 0.9em 0; orphans: 2; widows: 2; }
blockquote { margin: 1em 2em; }
blockquote p { margin: 0 0 0.6em 0; }
ul, ol { margin: 0 0 1em 0; padding-left: 2em; }
li { margin: 0 0 0.4em 0; }
figure { margin: 1.2em 0; text-align: center; page-break-inside: avoid; break-inside: avoid; }
img { max-width: 100%; height: auto; }
figcaption { font-size: 0.9em; font-style: italic; margin-top: 0.4em; }
table { border-collapse: collapse; max-width: 100%; margin: 1em 0; }
th, td { border: 0.06em solid; padding: 0.3em 0.5em; text-align: left; vertical-align: top; }
th { font-weight: bold; }
pre { white-space: pre-wrap; font-family: monospace; font-size: 0.9em; line-height: 1.35; margin: 1em 0; overflow-wrap: anywhere; tab-size: 4; }
pre code { font-size: 1em; }
code { font-family: monospace; font-size: 0.92em; overflow-wrap: anywhere; }
sup, sub { font-size: 0.75em; line-height: 0; }
span.dmath { display: block; text-align: center; text-indent: 0; margin: 0.6em 0; }
img.formula { vertical-align: middle; max-width: 100%; height: auto; }
span.eqno { margin-left: 1.5em; white-space: nowrap; }
hr { border: 0; border-top: 0.06em solid; margin: 2em 0 1em 0; }
section.footnotes { font-size: 0.9em; }
section.footnotes p { margin: 0 0 0.4em 0; }
nav ol { list-style-type: none; padding-left: 1.2em; }
"""

_TOC_LABEL = {
    "en": "Contents", "fr": "Table des matières", "es": "Índice", "de": "Inhaltsverzeichnis",
    "it": "Indice", "pt": "Índice", "nl": "Inhoud",
}
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def esc(t: str) -> str:
    return escape(_XML_BAD.sub("", t), quote=False)


def attr(t: str) -> str:
    return escape(_XML_BAD.sub("", t), quote=True)


def _ext(media_type: str) -> str:
    return "jpg" if media_type == "image/jpeg" else "png"


class Writer:
    def __init__(self, doc: Document, identifier: str):
        self.doc = doc
        self.identifier = identifier
        self.lang = doc.language
        self.anchor_file: dict[str, str] = {}
        self.image_files: dict[str, str] = {}
        for i, ch in enumerate(doc.chapters, 1):
            ch.filename = f"ch{i:03d}.xhtml"
            for b in ch.blocks:
                bid = getattr(b, "id", None)
                if bid:
                    self.anchor_file[bid] = ch.filename
        for iid, asset in doc.images.items():
            self.image_files[iid] = f"images/{iid}.{_ext(asset.media_type)}"

    # ---- inline -----------------------------------------------------------
    def runs(self, runs: list[Run]) -> str:
        out: list[str] = []
        i = 0
        while i < len(runs):
            r = runs[i]
            if r.display:  # a display formula: one centred block (picture or text, then its number)
                j = i
                while j < len(runs) and runs[j].display == r.display:
                    j += 1
                out.append(f'<span class="dmath">{"".join(self._math(x) for x in runs[i:j])}</span>')
                i = j
                continue
            if r.link and r.noteref is None:
                j = i
                grp = []
                while j < len(runs) and runs[j].link == r.link and runs[j].noteref is None:
                    grp.append(runs[j])
                    j += 1
                inner = "".join(self._styled(x, in_link=True) for x in grp)
                href = self._href(r.link)
                out.append(f'<a href="{attr(href)}">{inner}</a>' if href else inner)
                i = j
                continue
            out.append(self._styled(r))
            i += 1
        return "".join(out)

    def _math(self, r: Run) -> str:
        if r.image:
            src = self.image_files.get(r.image[0])
            if not src:
                return esc(r.text)
            width = f' style="width:{r.image[1]:.2f}em"' if r.image[1] else ""
            return f'<img class="formula" src="{attr(src)}" alt="{attr(r.text)}"{width}/>'
        if r.eqno:
            return f'<span class="eqno">{esc(r.text)}</span>'
        return self._styled(r)

    def _href(self, link) -> str | None:
        if link[0] == "url":
            return link[1]
        if link[0] == "anchor":
            f = self.anchor_file.get(link[1])
            return f"{f}#{link[1]}" if f else None
        return None

    def _styled(self, r: Run, in_link: bool = False) -> str:
        s = esc(r.text)
        if r.mono:
            s = f"<code>{s}</code>"
        if r.italic:
            s = f"<em>{s}</em>"
        if r.bold:
            s = f"<strong>{s}</strong>"
        if r.sub:
            s = f"<sub>{s}</sub>"
        if r.sup:
            s = f"<sup>{s}</sup>"
        if r.noteref:
            s = f'<a epub:type="noteref" id="ref-{r.noteref}" href="#{r.noteref}">{s}</a>'
        return s

    # ---- blocks -----------------------------------------------------------
    def _idattr(self, b, referenced: set[str]) -> str:
        bid = getattr(b, "id", None)
        return f' id="{attr(bid)}"' if bid and bid in referenced else ""

    def block(self, b, referenced: set[str]) -> str:
        ida = self._idattr(b, referenced)
        if isinstance(b, Heading):
            return f"<h{b.level}{ida}>{self.runs(b.runs)}</h{b.level}>"
        if isinstance(b, Paragraph):
            if b.kind == "pre":
                return f"<pre{ida}><code>{esc(''.join(r.text for r in b.runs))}</code></pre>"
            if b.kind == "blockquote":
                return f"<blockquote{ida}><p>{self.runs(b.runs)}</p></blockquote>"
            return f"<p{ida}>{self.runs(b.runs)}</p>"
        if isinstance(b, ListBlock):
            tag = "ol" if b.ordered else "ul"
            extra = ""
            if b.ordered and b.start == -1:
                extra = ' type="a"'
            elif b.ordered and b.start and b.start > 1:
                extra = f' start="{b.start}"'
            items = "".join(f"<li>{self.runs(it)}</li>" for it in b.items)
            return f"<{tag}{extra}{ida}>{items}</{tag}>"
        if isinstance(b, Table):
            rows = []
            for ri, row in enumerate(b.rows):
                cell = "th" if (b.header and ri == 0) else "td"
                rows.append("<tr>" + "".join(f"<{cell}>{self.runs(c)}</{cell}>" for c in row) + "</tr>")
            if b.header and len(rows) > 1:
                body = f"<thead>{rows[0]}</thead><tbody>{''.join(rows[1:])}</tbody>"
            else:
                body = f"<tbody>{''.join(rows)}</tbody>"
            return f"<table{ida}>{body}</table>"
        if isinstance(b, Figure):
            src = self.image_files.get(b.image_id)
            if not src:
                return ""
            cap = f"<figcaption>{self.runs(b.caption)}</figcaption>" if b.caption else ""
            return f'<figure{ida}><img src="{attr(src)}" alt="{attr(b.alt)}"/>{cap}</figure>'
        return ""

    # ---- documents --------------------------------------------------------
    def _head(self, title: str) -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" lang="{attr(self.lang)}" xml:lang="{attr(self.lang)}">\n'
            f'<head>\n<meta charset="utf-8"/>\n<title>{esc(title)}</title>\n'
            '<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n'
        )

    def chapter_xhtml(self, ch: Chapter) -> str:
        referenced: set[str] = {s[2] for s in ch.sections if s[2]}
        referenced |= self._all_link_targets()
        body = [self.block(b, referenced) for b in ch.blocks]
        refs = self._noterefs(ch)
        fns = [self.doc_footnotes[i] for i in refs if i in self.doc_footnotes] + ch.footnotes
        notes = ""
        if fns:
            items = []
            for fn in fns:
                mark = esc(fn.marker) if fn.orphan else f'<a href="#ref-{attr(fn.id)}">{esc(fn.marker)}</a>'
                items.append(f'<aside epub:type="footnote" id="{attr(fn.id)}"><p>{mark} {self.runs(fn.runs)}</p></aside>')
            notes = '<hr/>\n<section epub:type="footnotes" class="footnotes">\n' + "\n".join(items) + "\n</section>"
        return (self._head(ch.title) + '<body>\n<section epub:type="chapter">\n' + "\n".join(x for x in body if x)
                + "\n</section>\n" + notes + "\n</body>\n</html>\n")

    doc_footnotes: dict[str, Footnote] = {}

    def _noterefs(self, ch: Chapter) -> list[str]:
        found: list[str] = []

        def scan(runs):
            for r in runs:
                if r.noteref and r.noteref not in found:
                    found.append(r.noteref)

        for b in ch.blocks:
            if isinstance(b, (Paragraph, Heading)):
                scan(b.runs)
            elif isinstance(b, ListBlock):
                for it in b.items:
                    scan(it)
        return found

    _link_targets: set[str] | None = None

    def _all_link_targets(self) -> set[str]:
        if self._link_targets is None:
            t: set[str] = set()

            def scan(runs):
                for r in runs or []:
                    if r.link and r.link[0] == "anchor":
                        t.add(r.link[1])

            for ch in self.doc.chapters:
                for b in ch.blocks:
                    if isinstance(b, (Paragraph, Heading)):
                        scan(b.runs)
                    elif isinstance(b, ListBlock):
                        for it in b.items:
                            scan(it)
                    elif isinstance(b, Table):
                        for row in b.rows:
                            for c in row:
                                scan(c)
                    elif isinstance(b, Figure):
                        scan(b.caption)
            self._link_targets = t
        return self._link_targets

    def _nav_tree(self) -> list[tuple[int, str, str]]:
        """Flat list of (depth, title, href) for chapters (depth 1) and their sections (depth 2..)."""
        flat: list[tuple[int, str, str]] = []
        for ch in self.doc.chapters:
            flat.append((1, ch.title, ch.filename))
            for lvl, title, anchor in ch.sections:
                if not anchor:
                    continue
                if ch.blocks and isinstance(ch.blocks[0], Heading) and plain_title(ch.blocks[0]) == title and ch.blocks[0].level == 1:
                    continue
                flat.append((min(max(lvl, 2), 3), title, f"{ch.filename}#{anchor}"))
        return flat

    def nav_xhtml(self) -> str:
        label = _TOC_LABEL.get(self.lang.split("-")[0].lower(), "Contents")
        flat = self._nav_tree()
        lines = ['<ol>']
        depth = 1
        open_li = False
        for d, title, href in flat:
            d = min(d, depth + 1)
            if d > depth:
                lines.append("<ol>")
                depth = d
            else:
                if open_li:
                    lines.append("</li>")
                while depth > d:
                    lines.append("</ol></li>")
                    depth -= 1
            lines.append(f'<li><a href="{attr(href)}">{esc(title)}</a>')
            open_li = True
        if open_li:
            lines.append("</li>")
        while depth > 1:
            lines.append("</ol></li>")
            depth -= 1
        lines.append("</ol>")
        first = self.doc.chapters[0].filename
        return (
            self._head(label).replace('href="style.css"', 'href="style.css"')
            + '<body>\n<nav epub:type="toc" id="toc">\n'
            + f"<h1>{esc(label)}</h1>\n" + "\n".join(lines) + "\n</nav>\n"
            + '<nav epub:type="landmarks" hidden="hidden">\n<h2>Landmarks</h2>\n<ol>\n'
            + f'<li><a epub:type="bodymatter" href="{first}">{esc(self.doc.title)}</a></li>\n</ol>\n</nav>\n</body>\n</html>\n'
        )

    def ncx(self) -> str:
        flat = self._nav_tree()
        order = 0

        def point(d_title_href) -> str:
            nonlocal order
            order += 1
            _, title, href = d_title_href
            return (f'<navPoint id="np{order}" playOrder="{order}"><navLabel><text>{esc(title)}</text></navLabel>'
                    f'<content src="{attr(href)}"/>')

        out: list[str] = []
        depth = 0
        for item in flat:
            d = min(item[0], depth + 1)
            while depth >= d and depth > 0:
                out.append("</navPoint>")
                depth -= 1
            out.append(point(item))
            depth += 1
        out.append("</navPoint>" * depth)
        maxd = max((f[0] for f in flat), default=1)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="' + attr(self.lang) + '">\n'
            f'<head><meta name="dtb:uid" content="{attr(self.identifier)}"/><meta name="dtb:depth" content="{maxd}"/>'
            '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>\n'
            f"<docTitle><text>{esc(self.doc.title)}</text></docTitle>\n<navMap>\n" + "\n".join(out) + "\n</navMap>\n</ncx>\n"
        )

    def opf(self) -> str:
        d = self.doc
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = [
            f'<dc:identifier id="bookid">{esc(self.identifier)}</dc:identifier>',
            f"<dc:title>{esc(d.title)}</dc:title>",
            f"<dc:language>{esc(self.lang)}</dc:language>",
        ]
        if d.author:
            meta.append(f'<dc:creator id="creator">{esc(d.author)}</dc:creator>')
        meta.append(f'<meta property="dcterms:modified">{now}</meta>')
        meta.append('<meta property="rendition:layout">reflowable</meta>')
        if d.cover:
            meta.append('<meta name="cover" content="cover-image"/>')
        man = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '<item id="css" href="style.css" media-type="text/css"/>',
        ]
        spine = []
        for i, ch in enumerate(d.chapters, 1):
            man.append(f'<item id="c{i:03d}" href="{ch.filename}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{i:03d}"/>')
        for iid, asset in d.images.items():
            man.append(f'<item id="{iid}" href="{self.image_files[iid]}" media-type="{asset.media_type}"/>')
        if d.cover:
            man.append(f'<item id="cover-image" href="images/cover.{_ext(d.cover.media_type)}" '
                       f'media-type="{d.cover.media_type}" properties="cover-image"/>')
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{attr(self.lang)}">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n' + "\n".join(meta) + "\n</metadata>\n"
            "<manifest>\n" + "\n".join(man) + "\n</manifest>\n"
            '<spine toc="ncx">\n' + "\n".join(spine) + "\n</spine>\n</package>\n"
        )


def plain_title(h: Heading) -> str:
    return "".join(r.text for r in h.runs).strip()


CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n'
    "</container>\n"
)


def write_epub(doc: Document, footnotes: dict[str, Footnote], path: Path, identifier: str) -> None:
    w = Writer(doc, identifier)
    w.doc_footnotes = footnotes
    tmp = Path(str(path) + ".part")
    with zipfile.ZipFile(tmp, "w") as z:
        def put(name: str, data: str | bytes, deflate: bool = True):
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data.encode("utf-8") if isinstance(data, str) else data)

        put("mimetype", "application/epub+zip", deflate=False)
        put("META-INF/container.xml", CONTAINER)
        put("OEBPS/content.opf", w.opf())
        put("OEBPS/nav.xhtml", w.nav_xhtml())
        put("OEBPS/toc.ncx", w.ncx())
        put("OEBPS/style.css", CSS)
        for ch in doc.chapters:
            put(f"OEBPS/{ch.filename}", w.chapter_xhtml(ch))
        for iid, asset in doc.images.items():
            put(f"OEBPS/{w.image_files[iid]}", asset.data, deflate=False)
        if doc.cover:
            put(f"OEBPS/images/cover.{_ext(doc.cover.media_type)}", doc.cover.data, deflate=False)
    tmp.replace(path)
